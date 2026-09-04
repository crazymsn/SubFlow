from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bilingual_sub.gui.progress import format_pct
from bilingual_sub.gui.theme import type_font
from bilingual_sub.i18n import tr


def _pct_font() -> QFont:
    font = type_font(size=32, weight=QFont.Weight.Medium, display=True)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
    return font


def build_stage(win) -> QWidget:
    frame = QFrame()
    frame.setObjectName("stage")
    frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(4, 8, 4, 0)
    layout.setSpacing(10)

    head_w = QWidget()
    head_w.setMinimumHeight(44)
    head = QHBoxLayout(head_w)
    head.setContentsMargins(0, 0, 0, 0)
    head.setSpacing(12)
    win.stage_label = QLabel(tr("waiting"))
    win.stage_label.setObjectName("stageNow")
    win.stage_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    head.addWidget(win.stage_label, 1)
    win.pct_label = QLabel(format_pct(0))
    win.pct_label.setObjectName("pct")
    win.pct_label.setFont(_pct_font())
    win.pct_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    head.addWidget(win.pct_label, 0, Qt.AlignmentFlag.AlignVCenter)
    layout.addWidget(head_w)

    win.progress = QProgressBar()
    win.progress.setRange(0, 100)
    win.progress.setValue(0)
    win.progress.setTextVisible(False)
    layout.addWidget(win.progress)

    win.log = QPlainTextEdit()
    win.log.setReadOnly(True)
    win.log.setPlaceholderText(tr("log_ph"))
    win.log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
    win.log.setMinimumHeight(48)
    layout.addWidget(win.log, 1)

    foot = QHBoxLayout()
    foot.setContentsMargins(0, 0, 0, 0)
    foot.addStretch(1)
    win.github_btn = QToolButton()
    win.github_btn.setObjectName("githubBtn")
    win.github_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    win.github_btn.setAutoRaise(True)
    win.github_btn.setFixedSize(40, 40)
    win.github_btn.setToolTip("GitHub")
    win.github_btn.clicked.connect(win._open_github)
    foot.addWidget(win.github_btn, 0, Qt.AlignmentFlag.AlignRight)
    layout.addLayout(foot)
    return frame
