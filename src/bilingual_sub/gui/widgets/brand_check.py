from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QSizePolicy, QWidget

from bilingual_sub.gui.theme import mix_hex, tokens_for, type_font

BOX = 18
RADIUS = 5
GAP = 8
ROW = 36
# After the measured face sits on the well, CJK still reads a hair high next to a square.
CAPTION_SETTLE = 1.0
_FACE_CACHE: dict[tuple, float] = {}


def _typeface() -> QFont:
    return type_font(size=14, weight=QFont.Weight.Medium)


def _has_cjk(text: str) -> bool:
    return any(ord(char) >= 0x2E80 for char in text)


def _snap(value: float, dpr: float) -> float:
    if dpr <= 0:
        return value
    return round(value * dpr) / dpr


def _face_offset_from_baseline(font: QFont, text: str, dpr: float) -> float:
    """Optical character-face center relative to the baseline, in logical pixels."""
    key = (text, font.family(), font.pixelSize(), int(font.weight()), round(max(dpr, 0.01), 3))
    cached = _FACE_CACHE.get(key)
    if cached is not None:
        return cached
    metrics = QFontMetricsF(font)
    tight = metrics.tightBoundingRect(text)
    width = max(16.0, tight.width() + 8.0)
    height = max(24.0, metrics.height() + 20.0)
    origin = height * 0.65
    image = QImage(
        max(1, int(round(width * max(dpr, 0.01)))),
        max(1, int(round(height * max(dpr, 0.01)))),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    image.fill(0)
    image.setDevicePixelRatio(max(dpr, 0.01))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setFont(font)
    painter.setPen(QColor(0, 0, 0))
    painter.drawText(QPointF(2.0, origin), text)
    painter.end()

    scale = max(dpr, 0.01)
    ink: list[float] = []
    for y in range(image.height()):
        for x in range(image.width()):
            color = QColor.fromRgba(image.pixel(x, y))
            if color.alpha() > 80 and color.red() + color.green() + color.blue() < 400:
                ink.append(y / scale)
    if ink:
        lo, hi = min(ink), max(ink)
        cut = lo + 0.84 * (hi - lo)
        face = [y for y in ink if y <= cut]
        offset = (sum(face) / len(face) if face else sum(ink) / len(ink)) - origin
    else:
        hook = min(2.4, tight.height() * 0.16) if _has_cjk(text) else 0.0
        offset = (tight.y() + tight.height() - hook + tight.y()) / 2.0
    _FACE_CACHE[key] = offset
    return offset


def caption_baseline(font: QFont, text: str, mid_y: float, dpr: float = 1.0) -> float:
    """Baseline that puts the measured CJK character-face on the well mid-line."""
    if not text:
        return mid_y
    face = _face_offset_from_baseline(font, text, dpr)
    settle = CAPTION_SETTLE if _has_cjk(text) else 0.0
    return _snap(mid_y - face + settle, dpr)


class _CheckLabel(QLabel):
    """Layout slot only — BrandCheck paints the caption itself."""

    def paintEvent(self, event) -> None:  # noqa: N802
        return


class _Well(QWidget):
    def __init__(self, owner: BrandCheck) -> None:
        super().__init__(owner)
        self.setFixedSize(BOX, BOX)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, event) -> None:  # noqa: N802
        return


class BrandCheck(QCheckBox):
    """Apricot checkbox: well and caption share one painter and one mid-line."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self._theme = "light"
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(ROW)
        self.setFont(_typeface())
        self.setStyleSheet(
            "QCheckBox{background:transparent;padding:0;margin:0;min-height:0;spacing:0;}"
            "QCheckBox::indicator{width:0;height:0;border:none;image:none;}"
        )

        self._well = _Well(self)
        self._label = _CheckLabel(text, self)
        self._label.setFont(_typeface())
        self._label.setFixedHeight(ROW)
        self._label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 2, 0)
        row.setSpacing(GAP)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._well, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.apply_theme(self._theme)

    def apply_theme(self, theme: str) -> None:
        self._theme = theme or "light"
        tones = tokens_for(self._theme)
        ink = tones.ink if self.isEnabled() else tones.disabledFg
        self._label.setStyleSheet(f"QLabel{{color:{ink};background:transparent;padding:0;margin:0;border:none;}}")
        self._label.setFont(_typeface())
        self.update()

    def _active_theme(self) -> str:
        window = self.window()
        return str(getattr(window, "_theme", self._theme) or self._theme)

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        if hasattr(self, "_label"):
            self._label.setText(text)
        self.update()

    def sizeHint(self) -> QSize:
        label = self._label.sizeHint() if hasattr(self, "_label") else QSize(0, 0)
        return QSize(BOX + GAP + label.width() + 6, ROW)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self.update()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        if event.type() == QEvent.Type.EnabledChange and hasattr(self, "_label"):
            armed = self.isEnabled()
            self.setCursor(Qt.CursorShape.PointingHandCursor if armed else Qt.CursorShape.ArrowCursor)
            self.apply_theme(self._theme)
        super().changeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        well = QRectF(self._well.geometry()) if hasattr(self, "_well") else QRectF(0, (self.height() - BOX) / 2.0, BOX, BOX)
        self._paint_well(painter, well)
        if hasattr(self, "_label"):
            self._paint_caption(painter, QRectF(self._label.geometry()), well.center().y())

    def _paint_well(self, painter: QPainter, well: QRectF) -> None:
        tones = tokens_for(self._active_theme())
        dpr = self.devicePixelRatioF()
        box = QRectF(
            _snap(well.x() + 1.0, dpr),
            _snap(well.y() + 1.0, dpr),
            well.width() - 2.0,
            well.height() - 2.0,
        )
        checked = self.isChecked()
        hover = self.underMouse() and self.isEnabled()
        pressed = self.isDown() and self.isEnabled()

        if not self.isEnabled():
            fill = ""
            stroke = tones.line
            mark = tones.disabledFg
        elif checked:
            fill = tones.filamentPressed if pressed else tones.filamentHover if hover else tones.filament
            stroke = fill
            mark = tones.filamentInk
        elif hover or self.hasFocus():
            fill = tones.filamentWash
            stroke = tones.filament
            mark = tones.filamentInk
        else:
            fill = mix_hex(tones.sheet, tones.ink, 0.05)
            stroke = tones.muted
            mark = tones.filamentInk

        path = QPainterPath()
        path.addRoundedRect(box.x() + 0.5, box.y() + 0.5, box.width() - 1.0, box.height() - 1.0, RADIUS, RADIUS)
        if fill:
            painter.fillPath(path, QColor(fill))
        painter.setPen(QPen(QColor(stroke), 1.5))
        painter.drawPath(path)

        if checked or (hover and pressed):
            ox, oy = well.x(), well.y()
            tick = QPainterPath()
            tick.moveTo(ox + BOX * 0.22, oy + BOX * 0.52)
            tick.lineTo(ox + BOX * 0.42, oy + BOX * 0.72)
            tick.lineTo(ox + BOX * 0.78, oy + BOX * 0.30)
            painter.setPen(
                QPen(QColor(mark), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(tick)

        if self.hasFocus() and self.isEnabled():
            ring = QColor(tones.filament)
            ring.setAlpha(120)
            painter.setPen(QPen(ring, 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(box.adjusted(-2, -2, 2, 2), RADIUS + 1, RADIUS + 1)

    def _paint_caption(self, painter: QPainter, rect: QRectF, mid_y: float) -> None:
        text = self._label.text() if hasattr(self, "_label") else self.text()
        if not text:
            return
        tones = tokens_for(self._active_theme())
        ink = tones.ink if self.isEnabled() else tones.disabledFg
        font = _typeface()
        painter.setFont(font)
        painter.setPen(QColor(ink))
        baseline = caption_baseline(font, text, mid_y, self.devicePixelRatioF())
        painter.drawText(QPointF(rect.x(), baseline), text)
