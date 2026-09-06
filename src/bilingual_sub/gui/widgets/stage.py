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
    QVBoxLayout,
    QWidget,
)

from bilingual_sub.gui.progress import format_pct
from bilingual_sub.gui.theme import type_font
from bilingual_sub.gui.widgets.section import section_head
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
    layout.setContentsMargins(18, 18, 18, 12)
    layout.setSpacing(10)
    win.task_activity = QWidget()
    layout.addWidget(win.task_activity, 1)
    layout = QVBoxLayout(win.task_activity)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    layout.addWidget(section_head(win, "ui_task"))

    head_w = QWidget()
    head_w.setMinimumHeight(44)
    head = QHBoxLayout(head_w)
    head.setContentsMargins(0, 0, 0, 0)
    head.setSpacing(12)
    win.stage_label = QLabel(tr("waiting"))
    win.stage_label.setObjectName("stageNow")
    win.stage_label.setWordWrap(True)
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
    win.progress.setAccessibleName(tr("ui_task"))
    layout.addWidget(win.progress)

    win.log = QPlainTextEdit()
    win.log.setReadOnly(True)
    win.log.setAccessibleName(tr("ui_log"))
    win.log.setMaximumBlockCount(5000)
    win.log.setPlaceholderText("")
    win.log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
    win.log.setMinimumHeight(48)
    layout.addWidget(win.log, 1)
    # Keep the waiting status and progress bar visible. Only the log box has
    # an idle hardware view, which disappears as soon as a task starts.
    idle = QVBoxLayout(win.log.viewport())
    idle.setContentsMargins(12, 8, 12, 8)
    idle.addStretch(1)
    win.gpu_status = QLabel(tr("gpu_checking"))
    win.gpu_status.setObjectName("gpuStatus")
    win.gpu_status.setWordWrap(True)
    win.gpu_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
    idle.addWidget(win.gpu_status)
    idle.addStretch(1)

    return frame
