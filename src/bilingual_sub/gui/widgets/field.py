from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

SCROLL_FLOOR = 96


class FitScroll(QScrollArea):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._floor = SCROLL_FLOOR

    def set_floor(self, height: int) -> None:
        self._floor = max(0, height)
        self.updateGeometry()

    def sizeHint(self):
        inner = self.widget()
        if inner is None:
            return super().sizeHint()
        layout = inner.layout()
        if layout is not None:
            hint = layout.sizeHint().expandedTo(layout.minimumSize())
        else:
            hint = inner.sizeHint().expandedTo(inner.minimumSizeHint())
        return hint

    def minimumSizeHint(self):
        hint = self.sizeHint()
        return QSize(hint.width(), min(hint.height(), self._floor))


def hairline(name: str = "rule", height: int = 1) -> QFrame:
    line = QFrame()
    line.setObjectName(name)
    line.setFixedHeight(height)
    return line


def field_col(label: QLabel, widget: QWidget) -> QWidget:
    box = QWidget()
    box.setObjectName("fieldCol")
    box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    col = QVBoxLayout(box)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(6)
    col.addWidget(label)
    col.addWidget(widget)
    return box


def expanding(widget: QWidget) -> QWidget:
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return widget
