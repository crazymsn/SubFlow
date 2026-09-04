"""Hi-DPI pixmap loading — always rasterize at ≥3x for 超高清."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import QWidget

from bilingual_sub.brand import icon_path, mark_path

HEADER_MARK_PX = 56
ULTRA_HD_MIN = 3.0


def device_pixel_ratio(host: QWidget | None = None) -> float:
    if host is not None:
        ratio = float(host.devicePixelRatio())
        if ratio > 0:
            return ratio
    app = QGuiApplication.instance()
    if app is not None:
        ratio = float(app.devicePixelRatio())
        if ratio > 0:
            return ratio
    return 1.0


def load_pixmap(path: Path, logical_px: int, host: QWidget | None = None) -> QPixmap:
    pix = QPixmap(str(path))
    if pix.isNull() or logical_px <= 0:
        return pix
    dpr = max(device_pixel_ratio(host), ULTRA_HD_MIN)
    target = max(1, int(logical_px * dpr))
    scaled = pix.scaled(
        target,
        target,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    scaled.setDevicePixelRatio(dpr)
    return scaled


def load_app_icon(host: QWidget | None = None) -> QIcon:
    icon = QIcon()
    source = mark_path() if mark_path().is_file() else icon_path()
    for logical in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        pix = load_pixmap(source, logical, host)
        if not pix.isNull():
            icon.addPixmap(pix)
            icon.addFile(str(source), QSize(logical, logical))
    ico = icon_path()
    if ico.suffix.lower() == ".ico" and ico.is_file():
        icon.addFile(str(ico))
    return icon
