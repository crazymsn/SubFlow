from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton

from bilingual_sub.gui.theme import tokens_for, type_font

RADIUS = 6


class FilamentButton(QPushButton):
    """Cursor Build key: flat apricot plate, same in light and dark."""

    def __init__(self, text: str = "", *, object_name: str = "primary") -> None:
        super().__init__(text)
        self._theme = "light"
        self.setObjectName(object_name)
        self.setFlat(True)
        self.setAutoDefault(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFont(type_font(size=14, weight=QFont.Weight.DemiBold))

    def apply_theme(self, theme: str) -> None:
        self._theme = theme or "light"
        self.update()

    def _active_theme(self) -> str:
        window = self.window()
        return str(getattr(window, "_theme", self._theme) or self._theme)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        if event.type() == QEvent.Type.EnabledChange:
            armed = self.isEnabled()
            self.setCursor(Qt.CursorShape.PointingHandCursor if armed else Qt.CursorShape.ArrowCursor)
        super().changeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        tones = tokens_for(self._active_theme())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        pressed = self.isEnabled() and self.isDown()

        if not self.isEnabled():
            fill = tones.disabledFill
            ink = tones.disabledFg
        elif pressed:
            fill = tones.filamentPressed
            ink = tones.filamentInk
        elif self.underMouse():
            fill = tones.filamentHover
            ink = tones.filamentInk
        else:
            fill = tones.filament
            ink = tones.filamentInk

        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS, RADIUS)
        painter.fillPath(path, QColor(fill))

        if self.hasFocus() and self.isEnabled() and not pressed:
            ring = QColor(tones.filamentInk)
            ring.setAlpha(70)
            painter.setPen(QPen(ring, 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), RADIUS - 1, RADIUS - 1)

        painter.setPen(QColor(ink))
        painter.setFont(type_font(size=14, weight=QFont.Weight.DemiBold))
        text_rect = self.rect()
        if pressed:
            text_rect.translate(0, 1)
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignCenter), self.text())
