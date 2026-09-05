"""Hi-DPI pixmap loading — always rasterize at ≥3x for 超高清."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QImage, QPixmap
from PySide6.QtWidgets import QWidget

from bilingual_sub.brand import brand_dir, icon_path, logo_path, mark_path
from bilingual_sub.gui.theme import tokens_for

HEADER_MARK_PX = 48
GITHUB_MARK_PX = 28
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


def _knockout_mark(img: QImage, theme: str) -> QImage:
    """Official mark is black ink on white. Punch the plate; recolor strokes to theme ink."""
    out = img.convertToFormat(QImage.Format.Format_ARGB32)
    ink = QColor(tokens_for(theme).ink)
    for y in range(out.height()):
        for x in range(out.width()):
            c = QColor.fromRgba(out.pixel(x, y))
            if c.alpha() < 16:
                continue
            lum = 0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue()
            if lum > 220:
                c.setAlpha(0)
                out.setPixelColor(x, y, c)
            else:
                ink.setAlpha(max(c.alpha(), min(255, int(255 - lum))))
                out.setPixelColor(x, y, ink)
    return out


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


_MARK_CACHE: dict[str, QImage] = {}


def _prepared_mark(theme: str) -> QImage:
    cached = _MARK_CACHE.get(theme)
    if cached is not None and not cached.isNull():
        return cached
    img = QImage(str(mark_path()))
    if img.isNull():
        img = QImage(str(logo_path()))
    if img.isNull():
        return img
    prepared = _knockout_mark(img, theme)
    _MARK_CACHE[theme] = prepared
    return prepared


def load_brand_mark(logical_px: int, host: QWidget | None = None, theme: str = "light") -> QPixmap:
    img = _prepared_mark(theme)
    if img.isNull() or logical_px <= 0:
        return QPixmap()
    prepared = img
    dpr = max(device_pixel_ratio(host), ULTRA_HD_MIN)
    target = max(1, int(logical_px * dpr))
    scaled = prepared.scaled(
        target,
        target,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pix = QPixmap.fromImage(scaled)
    pix.setDevicePixelRatio(dpr)
    return pix


def github_mark_path() -> Path:
    mark = brand_dir() / "github-mark.png"
    return mark


def load_github_mark(logical_px: int, host: QWidget | None = None, theme: str = "dark") -> QPixmap:
    path = github_mark_path()
    if not path.is_file():
        return QPixmap()
    img = QImage(str(path))
    if img.isNull():
        return QPixmap()
    prepared = _knockout_mark(img, theme)
    dpr = max(device_pixel_ratio(host), ULTRA_HD_MIN)
    target = max(1, int(logical_px * dpr))
    scaled = prepared.scaled(
        target,
        target,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pix = QPixmap.fromImage(scaled)
    pix.setDevicePixelRatio(dpr)
    return pix


def load_app_icon(host: QWidget | None = None) -> QIcon:
    """Taskbar / window icon: official lockup on a white plate."""
    icon = QIcon()
    ico = icon_path()
    if ico.suffix.lower() == ".ico" and ico.is_file():
        icon.addFile(str(ico))
    badge = brand_dir() / "subflow-icon.png"
    source = badge if badge.is_file() else ico
    if source.is_file():
        for logical in (16, 20, 24, 32, 40, 48, 64, 128, 256):
            pix = load_pixmap(source, logical, host)
            if not pix.isNull():
                icon.addPixmap(pix)
    return icon
