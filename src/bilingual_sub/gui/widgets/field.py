from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class WorkspaceScroll(QScrollArea):
    def ensureWidgetVisible(self, child, xMargin=8, yMargin=12):  # noqa: N802, N803
        """Expose the whole control, not just a line edit's input-method cursor."""
        content = self.widget()
        if content is None or not content.isAncestorOf(child):
            return
        rect = child.rect().translated(child.mapTo(content, QPoint(0, 0)))
        self.ensureVisible(rect.center().x(), rect.center().y(),
                           rect.width() // 2 + xMargin, rect.height() // 2 + yMargin)


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
    label.setBuddy(widget)
    widget.setAccessibleName(label.text())
    return box


def expanding(widget: QWidget) -> QWidget:
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return widget


class _ComboScrollGuard(QObject):
    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() == QEvent.Type.Wheel and not watched.view().isVisible():
            event.ignore()
            return True
        return super().eventFilter(watched, event)


def protect_combo_scroll(win: QWidget) -> None:
    """Wheel scrolls the form; an open combo popup still scrolls its options."""
    guard = _ComboScrollGuard(win)
    for combo in win.findChildren(QComboBox):
        combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        combo.installEventFilter(guard)
