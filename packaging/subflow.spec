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

hidden = [
    "bilingual_sub",
    "bilingual_sub.gui.app",
    "bilingual_sub.gui.styles",
    "bilingual_sub.gui.brand_rc",
    "bilingual_sub.gui.output_path",
    "bilingual_sub.adapters.meding",
    "bilingual_sub.adapters.ffmpeg",
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
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
    "shiboken6",
]

excludes = [
    "tkinter",
    "matplotlib",
    "torch",
    "torchvision",
    "torchaudio",
    "whisper",
    "openai_whisper",
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
    binaries=[],
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
