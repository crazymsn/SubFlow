from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QColorDialog, QPushButton

from bilingual_sub.core.render import normalize_hex
from bilingual_sub.gui.theme import tokens_for


class ColorChip(QPushButton):
    """Sheet button with a live swatch; opens the system color dialog."""

    color_changed = Signal(str)

    def __init__(self, hex_color: str = "#FFFFFF", *, object_name: str = "colorChip") -> None:
        super().__init__()
        self._theme = "light"
        self._hex = normalize_hex(hex_color)
        self.setObjectName(object_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMinimumHeight(36)
        self.setMaximumHeight(36)
        self.clicked.connect(self._pick)
        self._sync_caption()

    def hex(self) -> str:
        return self._hex

    def set_hex(self, hex_color: str) -> None:
        self._hex = normalize_hex(hex_color, self._hex)
        self._sync_caption()
        self.update()

    def apply_theme(self, theme: str) -> None:
        self._theme = theme or "light"
        self.update()

    def _sync_caption(self) -> None:
        self.setText(f"  {self._hex}")

    def _pick(self) -> None:
        picked = QColorDialog.getColor(QColor(self._hex), self.window(), self.text().strip())
        if not picked.isValid():
            return
        name = picked.name().upper()
        if name == self._hex:
            return
        self.set_hex(name)
        self.color_changed.emit(self._hex)

    def paintEvent(self, event) -> None:  # noqa: N802
        tones = tokens_for(self._theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        fill = QColor(tones.filamentWash if self.underMouse() else tones.sheet)
        border = QColor(tones.filament if self.underMouse() or self.hasFocus() else tones.line)
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        painter.fillPath(path, fill)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        swatch = QRectF(10, (rect.height() - 16) / 2 + rect.top(), 16, 16)
        painter.setPen(QPen(QColor(tones.lineStrong), 1.0))
        painter.setBrush(QColor(self._hex))
        painter.drawRoundedRect(swatch, 3, 3)

        painter.setPen(QColor(tones.ink))
        painter.drawText(
            rect.adjusted(34, 0, -8, 0),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self._hex,
        )
