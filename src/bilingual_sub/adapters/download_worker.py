"""Run the downloader outside the GUI, with progress and result files."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from bilingual_sub.adapters.owned_process import owned_process
from bilingual_sub.core.control import wait_for_process


def worker_command(job: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--download-worker", str(job)]
    return [sys.executable, "-m", "bilingual_sub.adapters.download_worker", str(job)]


def run_download_worker(url, staging, *, on_progress, control, progress_range, source_lang):
    from bilingual_sub.adapters.ytdlp import DownloadError

    staging = staging.resolve()
    job = staging / "download-job.json"
    job.write_text(json.dumps({"url": url, "dest": str(staging), "progress_range": progress_range,
                               "source_lang": source_lang}, ensure_ascii=False), encoding="utf-8")
    progress = staging / "download-progress.jsonl"
    progress.touch()
    result_file = staging / "download-result.json"
    env = dict(os.environ)
    env["SUBFLOW_WORKER_PROCESS_GROUP"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if getattr(sys, "frozen", False):
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    else:
        root = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")

    with progress.open("rb") as events, (staging / "worker.log").open("wb") as log:
        pending = b""
        def drain():
            nonlocal pending
            pending += events.read()
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                event = json.loads(line)
                if on_progress:
                    on_progress(event["stage"], float(event["progress"]))

        with owned_process(worker_command(job), stdout=log, stderr=subprocess.STDOUT, env=env) as proc:
            code = wait_for_process(proc, control=control, on_tick=drain, interval=0.1)
            drain()
    if control:
        control.wait_if_paused()
    try:
        result = json.loads(result_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DownloadError(f"下载进程异常退出（{code}），未返回结果") from exc
    if code or result.get("error"):
        raise DownloadError(str(result.get("error") or f"下载进程退出码：{code}"))
    path = Path(result["path"])
    if path.resolve() != (staging / "source.mp4").resolve():
        raise DownloadError("下载进程返回了无效的输出路径")
    return path


def main(job_path: Path) -> int:
    from bilingual_sub.adapters.ytdlp import _download_into

    payload = json.loads(job_path.read_text(encoding="utf-8"))
    dest = Path(payload["dest"])
    result_file = dest / "download-result.json"
    with (dest / "download-progress.jsonl").open("a", encoding="utf-8") as progress:
        def emit(stage, value):
            progress.write(json.dumps({"stage": stage, "progress": value}) + "\n")
            progress.flush()
        try:
            path = _download_into(payload["url"], dest, on_progress=emit,
                                  progress_range=tuple(payload["progress_range"]),
                                  source_lang=payload["source_lang"])
            result = {"path": str(path.resolve())}
            code = 0
        except Exception as exc:
            result = {"error": str(exc)}
            code = 1
    pending = result_file.with_suffix(".pending")
    pending.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    pending.replace(result_file)
    return code


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
