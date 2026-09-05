"""Exercise actual postprocessing and codecs without downloading neural weights."""
from __future__ import annotations

import argparse
import ast
import io
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load_functions(path: Path, names: set[str], namespace: dict, class_name: str = ""):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = next(node.body for node in tree.body if isinstance(node, ast.ClassDef)
                and node.name == class_name) if class_name else tree.body
    functions = [node for node in body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in functions} != names:
        raise RuntimeError("Audio checks cannot locate the implementation functions")
    unit = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                           *functions], type_ignores=[])
    exec(compile(ast.fix_missing_locations(unit), str(path), "exec"), namespace)
    return namespace


def worker(home: Path):
    import numpy as np
    import soundfile as sf
    import torch

    sys.path.insert(0, str(home))
    from tools.subflow_audio import InvalidAudioError, float_to_pcm16, validate_sample_rate

    env = dict(torch=torch, np=np, time=time, i18n=lambda text: text, InvalidAudioError=InvalidAudioError,
               float_to_pcm16=float_to_pcm16, validate_sample_rate=validate_sample_rate)
    process = load_functions(home / "GPT_SoVITS/TTS_infer_pack/TTS.py", {"audio_postprocess"}, env, "TTS")["audio_postprocess"]
    model = SimpleNamespace(configs=SimpleNamespace(device="cpu", sampling_rate=32000), precision=torch.float32,
                            init_sr_model=lambda: None, sr_model_not_exist=False,
                            sr_model=lambda data, rate: (np.array([-2., 0., 2.], dtype=np.float32), 48000))
    tensor = torch.tensor([-2., 0., 2.])
    rate, pcm = process(model, [[tensor]], 24000, split_bucket=False, fragment_interval=.3)
    assert rate == 24000 and len(pcm) == 7203
    assert pcm[:3].tolist() == [-32768, 0, 32767] and not np.any(pcm[3:])
    assert tensor.tolist() == [-2., 0., 2.]
    for missing in (False, True):
        model.sr_model_not_exist = missing
        rate, pcm = process(model, [[tensor]], 24000, split_bucket=False, fragment_interval=0, super_sampling=True)
        assert rate == (24000 if missing else 48000) and pcm.tolist() == [-32768, 0, 32767]
    for bad in (torch.tensor([float("nan")]), torch.tensor([float("inf")]), torch.tensor([])):
        try:
            process(model, [[bad]], 24000, split_bucket=False, fragment_interval=0)
        except InvalidAudioError:
            pass
        else:
            raise AssertionError("Invalid model audio was accepted")
    encoders = load_functions(home / "api_v2.py", {"pack_raw", "pack_wav", "pack_ogg", "pack_aac", "pack_audio"},
                             dict(np=np, sf=sf, threading=threading, subprocess=subprocess, os=os, BytesIO=io.BytesIO))
    rate = 32000
    pcm = float_to_pcm16(np.sin(np.arange(3200, dtype=np.float32) * (2 * np.pi * 440 / rate)))
    codecs = {}
    for codec in ("raw", "wav", "ogg", "aac"):
        data = encoders["pack_audio"](io.BytesIO(), pcm, rate, codec).getvalue()
        if codec == "raw":
            assert data == pcm.tobytes()
            decoded = pcm
        elif codec == "aac":
            result = subprocess.run(["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "s16le", "pipe:1"],
                                    input=data, capture_output=True, check=True, timeout=30,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            decoded = np.frombuffer(result.stdout, dtype="<i2")
        else:
            decoded, decoded_rate = sf.read(io.BytesIO(data), dtype="int16")
            assert decoded_rate == rate
            if codec == "wav":
                np.testing.assert_array_equal(decoded, pcm)
        assert len(decoded) > 0 and np.any(decoded)
        codecs[codec] = {"bytes": len(data), "frames": len(decoded)}
    return {"torch": torch.__version__, "device": "cpu", "weights_loaded": False,
            "postprocess_boundaries": True, "codecs": codecs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--home", type=Path)
    parser.add_argument("--report", type=Path, default=Path("sovits-audio-report.json"))
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.home or ROOT / "third_party/GPT-SoVITS")))
        return
    from bilingual_sub.adapters.runtime_bootstrap import ensure_python_env, inference_env
    from bilingual_sub.adapters.tts.gptsovits_runtime import discover_home

    home = args.home or discover_home()
    if home is None:
        raise RuntimeError("Prepare the GPT-SoVITS runtime before running audio checks")
    python = ensure_python_env("gptsovits")
    result = subprocess.run([str(python), str(Path(__file__).resolve()), "--worker", "--home", str(home)],
                            env=inference_env(), capture_output=True, text=True, encoding="utf-8", timeout=180,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise RuntimeError(result.stderr[-5000:] or result.stdout[-5000:])
    report = json.loads(result.stdout.strip().splitlines()[-1])
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
