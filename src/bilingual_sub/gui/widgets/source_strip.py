from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bilingual_sub.gui.widgets.drop_card import RAIL_H, DropCard
from bilingual_sub.gui.widgets.filament_btn import FilamentButton
from bilingual_sub.i18n import tr


def _station(label: QLabel, body: QWidget) -> QWidget:
    box = QWidget()
    box.setObjectName("sourceStation")
    box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    col = QVBoxLayout(box)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(6)
    col.addWidget(label)
    col.addWidget(body)
    return box


def build_source(win) -> QWidget:
    strip = QFrame()
    strip.setObjectName("sourceStrip")
    shell = QVBoxLayout(strip)
    shell.setContentsMargins(18, 16, 18, 16)
    shell.setSpacing(8)

    rail = QHBoxLayout()
    rail.setContentsMargins(0, 0, 0, 0)
    rail.setSpacing(16)

    win.lbl_source_file = QLabel(tr("source_file"))
    win.lbl_source_file.setObjectName("fieldLabel")
    win.drop = DropCard()
    win.drop.file_dropped.connect(win._set_video)
    rail.addWidget(_station(win.lbl_source_file, win.drop), 1)

    win.lbl_source_url = QLabel(tr("source_url"))
    win.lbl_source_url.setObjectName("fieldLabel")
    compose = QFrame()
    compose.setObjectName("urlCompose")
    compose.setFixedHeight(RAIL_H)
    compose.setMaximumHeight(RAIL_H)
    compose.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    well = QVBoxLayout(compose)
    well.setContentsMargins(18, 0, 18, 0)
    well.setSpacing(0)

    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(10)

    win.url_edit = QLineEdit()
    win.url_edit.setObjectName("urlEdit")
    win.url_edit.setPlaceholderText(tr("url_ph"))
    win.url_edit.setFixedHeight(44)
    win.url_edit.setMaximumHeight(44)
    win.url_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    win.url_edit.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    win.url_edit.textChanged.connect(win._sync_download)
    row.addWidget(win.url_edit, 1)

    win.download_btn = FilamentButton(tr("download"), object_name="composeGo")
    win.download_btn.setFixedSize(124, 44)
    win.download_btn.setEnabled(False)
    win.download_btn.clicked.connect(win._download)
    row.addWidget(win.download_btn, 0)

    well.addStretch(1)
    well.addLayout(row)
    well.addStretch(1)
    rail.addWidget(_station(win.lbl_source_url, compose), 1)
    shell.addLayout(rail)

    win.video_name = QLabel("")
    win.video_name.setObjectName("videoChip")
    win.video_name.hide()
    return strip
