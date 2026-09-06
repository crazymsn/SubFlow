"""Build the shipped synthetic voice references; never run on client startup.

Run with the Qwen runtime and a local, verified VoiceDesign model. Generation is
deterministic for a fixed runtime/seed; hashes in the manifest identify actual
shipped WAVs. These are product assets, not recordings of identifiable people.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PROFILES = {
    "zh": ("Chinese", "standard Mandarin Chinese", "您好，欢迎来到这里。请告诉我您的想法，我们一起寻找合适的方法。"),
    "en": ("English", "General American English", "Hello, welcome. Please tell me what you have in mind, and we can find a helpful way forward together."),
    "ja": ("Japanese", "standard Tokyo Japanese", "こんにちは。今日はどのようなご用件でしょうか。ゆっくりお話しいただければ、一緒に考えます。"),
    "es": ("Spanish", "neutral European Spanish", "Hola, bienvenido. Cuénteme lo que necesita y encontraremos juntos una buena manera de ayudarle."),
    "fr": ("French", "standard metropolitan French", "Bonjour et bienvenue. Dites-moi ce dont vous avez besoin, et nous trouverons ensemble une solution adaptée."),
    "de": ("German", "standard German Hochdeutsch", "Guten Tag und herzlich willkommen. Erzählen Sie mir, was Sie brauchen, und wir finden gemeinsam eine passende Lösung."),
    "ru": ("Russian", "standard Russian", "Здравствуйте, добро пожаловать. Расскажите, что вам нужно, и мы вместе найдём подходящее решение."),
}


def main():
    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    device = "cuda:0" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    torch.set_num_threads(8)
    model = Qwen3TTSModel.from_pretrained(str(args.model), device_map=device,
        dtype=torch.bfloat16 if device.startswith("cuda") else torch.float32,
        attn_implementation="sdpa", local_files_only=True)
    voices = []
    for code, (language, accent, text) in PROFILES.items():
        for gender in ("female", "male"):
            voice_id = f"SubFlow_{code}_{gender}"
            seed = 1000 + len(voices)
            instruction = (f"A native {accent} speaker, adult {gender} voice. "
                + ("Clear warm mid-high register, smooth resonant tone. " if gender == "female" else "Warm medium-low register, calm resonant tone. ")
                + "Natural conversational delivery with native pronunciation and sentence intonation, moderate speaking pace, clear articulation. "
                "A friendly professional narrator. Clean dry studio speech, no music, no exaggerated emotion.")
            path = args.output / f"{voice_id}.wav"
            if not path.exists():
                for attempt in range(3):
                    torch.manual_seed(seed + attempt * 100)
                    wavs, rate = model.generate_voice_design(text=text, language=language,
                        instruct=instruction, max_new_tokens=400)
                    audio = np.asarray(wavs[0])
                    seconds = len(audio) / rate
                    if 3 <= seconds <= 10 and np.isfinite(audio).all() and np.max(np.abs(audio)) > 0.01:
                        sf.write(path, audio, rate, subtype="PCM_16")
                        break
                else:
                    raise RuntimeError(f"Invalid reference duration/amplitude: {voice_id}, {seconds}")
            info = sf.info(path)
            assert 3 <= info.duration <= 10
            voices.append(dict(id=voice_id, gender=gender, language=code, text=text,
                file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                seconds=round(info.duration, 3), seed=seed, instruction=instruction))
            print(json.dumps({"voice":voice_id, "device":device, "seconds":info.duration}), flush=True)
    manifest = dict(schema=1, model="Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        revision="5ecdb67327fd37bb2e042aab12ff7391903235d3",
        description="Synthetic voices designed for SubFlow; not official named Qwen speaker presets.", voices=voices)
    (args.output / "voices.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
