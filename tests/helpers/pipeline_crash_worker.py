"""An owned test subprocess; abrupt exit deliberately bypasses cleanup."""
import json
import os
import sys
from pathlib import Path

from bilingual_sub import pipeline as p
from bilingual_sub.config import AppSettings
from bilingual_sub.models import JobConfig, Segment


def main() -> None:
    root, phase, step = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    source = root / "input.mp4"
    if not source.exists():
        source.write_bytes(b"fixed input identity")
    cfg = JobConfig(source, None, root / "out.srt", root / "work", burn=False,
                    source_lang="en", target_lang="en", subtitle_mode="single:en", enable_dub=False)
    if step != "seed":
        if phase == "subtitle":
            cfg.subtitle_en_color = "#ABCDEF"
        if phase == "completion":
            cfg.output_srt = root / "new.srt"
        cfg.resume_from = {"transcribe": "transcribe", "subtitle": "render", "completion": "done"}[phase]
        if step == "reject":
            cfg.resume_from = {"transcribe": "build_cues", "subtitle": "burn"}[phase]

    p.last_job_pointer = lambda: root / "last.json"
    p.get_api_key = lambda: None
    p.setup_logging = lambda **kwargs: None
    p.probe_video = lambda path: {"duration": 3, "has_audio": True, "width": 640, "height": 480}
    p.extract_wav = lambda source, path, **kwargs: path.write_bytes(b"fixed audio fixture")
    p.detect_silences = lambda *args, **kwargs: []

    def transcribe(wav, **kwargs):
        counter = root / "asr-count.txt"
        count = int(counter.read_text(encoding="ascii")) + 1 if counter.exists() else 1
        counter.write_text(str(count), encoding="ascii")
        segment = Segment(.2, 1.6, f"recognized version {count}")
        kwargs["out_json"].write_text(json.dumps({"language": "en", "segments": [segment.__dict__]}),
                                       encoding="utf-8")
        if phase == "transcribe" and step == "crash":
            os._exit(77)
        return [segment]

    p.transcribe = transcribe
    replace = Path.replace

    def crash_after_replace(path, destination):
        result = replace(path, destination)
        boundary = cfg.output_srt.with_suffix(".ass") if phase == "subtitle" else cfg.work_dir / "report.json"
        if step == "crash" and phase != "transcribe" and destination == boundary:
            os._exit(77)
        return result

    Path.replace = crash_after_replace
    p.run(cfg, AppSettings())


if __name__ == "__main__":
    main()
