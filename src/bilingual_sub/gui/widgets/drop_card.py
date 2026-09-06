from __future__ import annotations

from html import escape as html_escape
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QFileDialog, QLabel, QSizePolicy

from bilingual_sub.gui.theme import STACKS, TYPE, tokens_for
from bilingual_sub.i18n import tr

VIDEO_FILTER = "Video (*.mp4 *.mkv *.mov *.avi *.webm *.m4v)"
RAIL_H = 72


class DropCard(QLabel):
    file_dropped = Signal(Path)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("drop")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setMinimumWidth(180)
        self.setFixedHeight(RAIL_H)
        self.setMaximumHeight(RAIL_H)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("active", False)
        self.setAccessibleName(tr("drop"))
        tones = tokens_for("light")
        self.set_prompt(tr("drop"), title_color=tones.ink, hint_color=tones.muted)

    def set_prompt(self, title: str, hint: str = "", *, title_color: str, hint_color: str) -> None:
        self._full_title = title
        self.setToolTip(title)
        if hint:
            self.setTextFormat(Qt.TextFormat.RichText)
            self.setText(
                f'<div style="line-height:138%;font-family:{STACKS.uiFamily};">'
                f'<div style="font-size:{TYPE.ui};font-weight:600;letter-spacing:0.2px;color:{title_color};">{html_escape(title)}</div>'
                f'<div style="margin-top:8px;font-size:{TYPE.caption};font-weight:500;letter-spacing:0.4px;color:{hint_color};">{html_escape(hint)}</div>'
                f"</div>"
            )
        else:
            self.setTextFormat(Qt.TextFormat.PlainText)
            self._fit_title()

    def _fit_title(self) -> None:
        self.setText(self.fontMetrics().elidedText(self._full_title, Qt.TextElideMode.ElideMiddle,
                                                  max(40, self.width() - 44)))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_full_title") and self.textFormat() == Qt.TextFormat.PlainText:
            self._fit_title()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._choose_file()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._choose_file()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("select_video"), "", VIDEO_FILTER)
        if path:
            self.file_dropped.emit(Path(path))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            self.setProperty("active", True)
            self.style().unpolish(self)
            self.style().polish(self)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.setProperty("active", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self.setProperty("active", False)
        self.style().unpolish(self)
        self.style().polish(self)
        urls = event.mimeData().urls()
        if urls:
            path = Path(urls[0].toLocalFile())
            if path.is_file():
                self.file_dropped.emit(path)
