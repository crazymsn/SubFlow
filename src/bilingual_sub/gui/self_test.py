"""Packaged-client smoke check used by release CI."""
import json
import os
import tempfile
import threading
from pathlib import Path


def run(report: Path) -> None:
    os.environ["SUBFLOW_SOVITS_AUTOSTART"] = "0"
    os.environ["SUBFLOW_AUTO_INSTALL"] = "0"
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.adapters.ffmpeg import find_ffmpeg, find_ffprobe, run_cmd
    from bilingual_sub.adapters.runtime_bootstrap import bootstrap_assets, find_uv
    from bilingual_sub.adapters.tts.gptsovits_runtime import bundled_src
    from bilingual_sub.gui.app import MainWindow

    app = QApplication([])
    win = MainWindow()
    win.source_lang_combo.setCurrentIndex(win.source_lang_combo.findData("zh"))
    win.target_lang_combo.setCurrentIndex(win.target_lang_combo.findData("zh-Hant"))
    assert not win.dub_check.isChecked()
    source = bundled_src()
    assert source is not None and (source / "api_v2.py").is_file()
    assert (bootstrap_assets() / "download_assets.py").is_file()
    checks: dict[str, object] = {}
    from bilingual_sub.adapters.whisper_backend import worker_script as whisper_script
    from bilingual_sub.adapters.whisperx_backend import worker_script as whisperx_script

    workers = [whisper_script(), whisperx_script()]
    assert all(path.with_name("transcript_io.py").is_file() for path in workers)
    checks["asr_worker_scripts"] = [str(path) for path in workers]
    for name, binary in (("ffmpeg", find_ffmpeg()), ("ffprobe", find_ffprobe()), ("uv", str(find_uv()))):
        checks[name] = run_cmd([binary, "--version" if name == "uv" else "-version"]).stdout.splitlines()[0]
    from bilingual_sub.adapters.download_worker import run_download_worker
    from bilingual_sub.adapters.ytdlp import DownloadError
    from bilingual_sub.core.control import JobControl

    with tempfile.TemporaryDirectory(prefix="subflow-worker-smoke-") as scratch:
        control = JobControl()
        deadline = threading.Timer(30, control.stop)
        deadline.start()
        try:
            try:
                run_download_worker("invalid://subflow-smoke", Path(scratch), on_progress=None,
                                    control=control, progress_range=(0, 1), source_lang="zh")
            except DownloadError:
                result = json.loads((Path(scratch) / "download-result.json").read_text(encoding="utf-8"))
                assert result.get("error"), "worker did not return a structured download error"
            else:
                raise AssertionError("invalid URL unexpectedly succeeded")
        finally:
            deadline.cancel()
        checks["download_worker"] = "isolated worker started and returned a structured error"
    win.close()
    app.processEvents()
    report.write_text(json.dumps({"ok": True, "checks": checks}, indent=2), encoding="utf-8")
