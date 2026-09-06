"""Small, translated section headings shared by the desktop workspace."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from bilingual_sub.i18n import tr


def section_head(win, key: str, number: str = "", hint: str = "") -> QWidget:
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(10)
    if number:
        badge = QLabel(number)
        badge.setObjectName("stepBadge")
        badge.setFixedSize(28, 28)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
    text = QVBoxLayout()
    text.setSpacing(3)
    title = QLabel(tr(key))
    title.setObjectName("sectionTitle")
    if number:
        title.setMinimumHeight(28)
    title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    win._section_labels[key] = title
    text.addWidget(title)
    if hint:
        caption = QLabel(tr(hint))
        caption.setObjectName("help")
        caption.setWordWrap(True)
        win._section_labels[hint] = caption
        text.addWidget(caption)
    row.addLayout(text, 1)
    row.setAlignment(text, Qt.AlignmentFlag.AlignTop)
    return box
