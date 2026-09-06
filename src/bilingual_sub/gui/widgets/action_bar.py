from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bilingual_sub.gui.widgets.field import expanding
from bilingual_sub.gui.widgets.filament_btn import FilamentButton
from bilingual_sub.i18n import tr


def build_action_bar(win) -> QWidget:
    dock = QFrame()
    dock.setObjectName("actionBar")
    dock.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    shell = QVBoxLayout(dock)
    shell.setContentsMargins(18, 12, 18, 12)
    shell.setSpacing(10)
    row = QHBoxLayout()
    row.setSpacing(8)

    win.run_btn = FilamentButton(tr("start"), object_name="primary")
    win.run_btn.setMinimumWidth(156)
    win.run_btn.setFixedHeight(40)
    win.run_btn.clicked.connect(win._start)
    win.start_btn = win.run_btn

    win.pause_btn = QPushButton(tr("pause"))
    win.resume_btn = QPushButton(tr("resume"))
    win.stop_btn = QPushButton(tr("stop"))
    win.pause_btn.setObjectName("quiet")
    win.resume_btn.setObjectName("quiet")
    win.stop_btn.setObjectName("danger")
    for btn in (win.pause_btn, win.resume_btn, win.stop_btn):
        btn.setMinimumHeight(36)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
    win.pause_btn.setEnabled(False)
    win.resume_btn.setEnabled(False)
    win.stop_btn.setEnabled(False)
    win.pause_btn.clicked.connect(win._pause)
    win.resume_btn.clicked.connect(win._resume)
    win.stop_btn.clicked.connect(win._stop)

    win.lbl_out = QLabel(tr("out"))
    win.lbl_out.setObjectName("outLabel")
    win._section_labels["out"] = win.lbl_out
    win.out_edit = QLineEdit()
    win.out_edit.setObjectName("outEdit")
    win.out_edit.setAccessibleName(tr("out"))
    win.out_edit.setReadOnly(False)
    win.out_edit.setEnabled(True)
    win.out_edit.setClearButtonEnabled(True)
    win.out_edit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    win.out_edit.setPlaceholderText(tr("out_ph"))
    win.out_edit.setFixedHeight(36)
    win.out_edit.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    win.out_edit.editingFinished.connect(win._on_out_path_committed)
    win.browse_out_btn = QPushButton(tr("browse"))
    win.browse_out_btn.setObjectName("ghost")
    win.browse_out_btn.setFixedHeight(36)
    win.browse_out_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    win.browse_out_btn.clicked.connect(win._browse_output)

    win.open_btn = QPushButton(tr("open"))
    win.open_btn.setObjectName("ghost")
    win.open_btn.setMinimumHeight(36)
    win.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    win.open_btn.setEnabled(False)
    win.open_btn.hide()
    win.open_btn.clicked.connect(win._open_folder)

    cluster = QWidget()
    cluster.setObjectName("outCluster")
    cluster.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    path = QHBoxLayout(cluster)
    path.setContentsMargins(0, 0, 0, 0)
    path.setSpacing(8)
    path.addWidget(win.lbl_out, 0, Qt.AlignmentFlag.AlignVCenter)
    path.addWidget(expanding(win.out_edit), 1)
    path.addWidget(win.browse_out_btn, 0, Qt.AlignmentFlag.AlignVCenter)
    path.addWidget(win.open_btn, 0, Qt.AlignmentFlag.AlignVCenter)

    shell.addWidget(cluster)
    shell.addLayout(row)
    row.addWidget(win.pause_btn)
    row.addWidget(win.resume_btn)
    row.addWidget(win.stop_btn)
    row.addStretch(1)
    row.addWidget(win.run_btn)
    return dock
