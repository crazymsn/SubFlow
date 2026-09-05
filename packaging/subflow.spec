# -*- mode: python ; coding: utf-8 -*-
# 语幕 SubFlow desktop client — slim, no Torch/UPX/ICU (they break Qt6Core on Windows)
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"

datas = []
if (ROOT / "config").is_dir():
    datas.append((str(ROOT / "config"), "bilingual_sub/_data/config"))
if (ROOT / "fonts").is_dir():
    datas.append((str(ROOT / "fonts"), "bilingual_sub/_data/fonts"))
if (ROOT / "assets" / "brand").is_dir():
    datas.append((str(ROOT / "assets" / "brand"), "bilingual_sub/_data/brand"))
worker = SRC / "bilingual_sub" / "adapters" / "whisper_worker.py"
if worker.is_file():
    datas.append((str(worker), "bilingual_sub/adapters"))
wx_worker = SRC / "bilingual_sub" / "adapters" / "whisperx_worker.py"
if wx_worker.is_file():
    datas.append((str(wx_worker), "bilingual_sub/adapters"))
locales = SRC / "bilingual_sub" / "i18n" / "locales"
if locales.is_dir():
    datas.append((str(locales), "bilingual_sub/i18n/locales"))

hidden = [
    "bilingual_sub",
    "bilingual_sub.gui.app",
    "bilingual_sub.gui.styles",
    "bilingual_sub.gui.theme",
    "bilingual_sub.gui.workers",
    "bilingual_sub.gui.assets",
    "bilingual_sub.gui.model_choice",
    "bilingual_sub.gui.brand_rc",
    "bilingual_sub.gui.output_path",
    "bilingual_sub.gui.progress",
    "bilingual_sub.gui.widgets",
    "bilingual_sub.gui.widgets.drop_card",
    "bilingual_sub.gui.widgets.field",
    "bilingual_sub.gui.widgets.header",
    "bilingual_sub.gui.widgets.source_strip",
    "bilingual_sub.gui.widgets.deck",
    "bilingual_sub.gui.widgets.action_bar",
    "bilingual_sub.gui.widgets.filament_btn",
    "bilingual_sub.gui.widgets.brand_check",
    "bilingual_sub.gui.widgets.color_chip",
    "bilingual_sub.gui.widgets.stage",
    "bilingual_sub.adapters.meding",
    "bilingual_sub.adapters.ffmpeg",
    "bilingual_sub.adapters.procwin",
    "bilingual_sub.adapters.whisper_backend",
    "bilingual_sub.adapters.whisperx_backend",
    "bilingual_sub.adapters.ytdlp",
    "bilingual_sub.adapters.tts",
    "bilingual_sub.adapters.tts.base",
    "bilingual_sub.adapters.tts.openai_tts",
    "bilingual_sub.adapters.tts.azure_tts",
    "bilingual_sub.adapters.tts.gptsovits",
    "bilingual_sub.i18n",
    "bilingual_sub.core.control",
    "bilingual_sub.core.langs",
    "bilingual_sub.core.netflix",
    "bilingual_sub.core.glossary_ai",
    "bilingual_sub.core.prompts",
    "bilingual_sub.core.translate_refine",
    "bilingual_sub.core.dub",
    "yt_dlp",
    "json_repair",
    "httpx",
    "bilingual_sub.brand",
    "bilingual_sub.config",
    "bilingual_sub.secrets.store",
    "keyring",
    "keyring.backends",
    "keyring.backends.Windows",
    "keyring.backends.macOS",
    "keyring.backends.macOS.api",
    "openai",
    "yaml",
    "opencc",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
    "shiboken6",
]

occ_bins = []
try:
    from PyInstaller.utils.hooks import collect_all, collect_submodules

    hidden += collect_submodules("yt_dlp")
    occ_datas, occ_bins, occ_hidden = collect_all("opencc")
    datas += occ_datas
    hidden += occ_hidden
except Exception:
    pass

excludes = [
    "tkinter",
    "matplotlib",
    "torch",
    "torchvision",
    "torchaudio",
    "whisper",
    "openai_whisper",
    "whisperx",
    "pandas",
    "pyarrow",
    "tensorflow",
    "IPython",
    "notebook",
    "scipy",
    "cv2",
    "numba",
    "llvmlite",
    "PySide6.QtWebEngine",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.Qt3DCore",
    "PySide6.QtBluetooth",
    "PySide6.QtQml",
    "PySide6.QtQuick",
]

a = Analysis(
    [str(ROOT / "packaging" / "gui_entry.py")],
    pathex=[str(SRC)],
    binaries=occ_bins,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)


def _is_icu(dest: str) -> bool:
    name = Path(str(dest)).name.lower()
    return name.startswith("icuuc") or name.startswith("icudt") or name.startswith("icuin")


a.binaries = [item for item in a.binaries if not _is_icu(item[0])]

pyz = PYZ(a.pure)

ICON = ROOT / "assets" / "brand" / "subflow.ico"

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SubFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ICON) if ICON.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="SubFlow",
)
