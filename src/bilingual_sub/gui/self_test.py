"""Packaged-client smoke check used by release CI."""
import json
import os
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
    checks = {}
    for name, binary in (("ffmpeg", find_ffmpeg()), ("ffprobe", find_ffprobe()), ("uv", str(find_uv()))):
        checks[name] = run_cmd([binary, "--version" if name == "uv" else "-version"]).stdout.splitlines()[0]
    win.close()
    app.processEvents()
    report.write_text(json.dumps({"ok": True, "checks": checks}, indent=2), encoding="utf-8")
