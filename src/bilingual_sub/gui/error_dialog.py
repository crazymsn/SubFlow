"""Theme-aware, bounded error feedback with actionable summaries and plain-text details."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFont, QTextOption
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from bilingual_sub.gui.theme import tokens_for, type_font
from bilingual_sub.i18n import tr
from bilingual_sub.logging_util import redact_api_key
from bilingual_sub.secrets.store import get_api_key


class ErrorDialog(QDialog):
    def __init__(self, parent, details: str, *, preview: bool = False, translation_retry: bool = False) -> None:
        super().__init__(parent)
        self.translation_retry = translation_retry
        self._theme = getattr(parent, "_theme", "dark")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(tr("error_preview_title") if preview else tr("error_title"))
        self.setWindowIcon(parent.windowIcon())
        self.safe_details = redact_api_key(details, get_api_key())
        lowered = self.safe_details.lower()
        reference = "参考音频" in lowered or "reference audio" in lowered or "ref_audio_path" in lowered
        summary = tr("error_reference_help") if reference else tr("error_generic_help")
        if not reference and ("超时" in lowered or "timeout" in lowered):
            summary = tr("error_timeout_help")
        if "成片仍是原声" in self.safe_details:
            summary += "\n" + tr("error_original_kept")
        title = tr("error_reference_title") if reference else self.windowTitle()
        if translation_retry:
            reference = False
            title = tr("error_translation_title")
            summary = tr("error_translation_help")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        card = QFrame()
        card.setObjectName("errorCard")
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(18)

        header = QHBoxLayout()
        brand = QLabel("SubFlow · " + tr("error_notice"))
        brand.setObjectName("errorEyebrow")
        brand.setTextFormat(Qt.TextFormat.PlainText)
        brand.installEventFilter(self)
        header.addWidget(brand)
        header.addStretch()
        close = QPushButton("×")
        close.setObjectName("errorDismiss")
        close.setAccessibleName(tr("error_close"))
        close.setToolTip(tr("error_close"))
        close.setFixedSize(32, 32)
        close.clicked.connect(self.reject)
        header.addWidget(close)
        layout.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(16)
        icon = QLabel("!")
        icon.setObjectName("errorIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(40, 40)
        body.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        copy = QVBoxLayout()
        copy.setSpacing(10)
        self.heading = QLabel(title)
        self.heading.setObjectName("errorHeading")
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.heading.setWordWrap(True)
        self.heading.setFont(type_font(size=20, weight=QFont.Weight.DemiBold))
        copy.addWidget(self.heading)
        self.summary = QLabel(summary)
        self.summary.setObjectName("errorSummary")
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        copy.addWidget(self.summary)
        body.addLayout(copy, 1)
        layout.addLayout(body)

        self.details_toggle = QPushButton(tr("error_details"))
        self.details_toggle.setObjectName("errorDetailsToggle")
        self.details_toggle.setCheckable(True)
        layout.addWidget(self.details_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.details = QPlainTextEdit()
        self.details.setObjectName("errorDetails")
        self.details.setReadOnly(True)
        self.details.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.details.setPlainText(self.safe_details)
        self.details.setAccessibleName(tr("error_details"))
        self.details.hide()
        layout.addWidget(self.details)
        self.details_toggle.toggled.connect(self._toggle_details)

        footer = QHBoxLayout()
        self.copy_button = QPushButton(tr("error_copy"))
        self.copy_button.clicked.connect(self._copy_details)
        footer.addWidget(self.copy_button)
        footer.addStretch()
        self.action = QPushButton(tr("error_choose_reference") if reference and hasattr(parent, "_browse_ref_audio") else tr("error_close"))
        self.action.setObjectName("errorPrimary")
        self.action.setDefault(True)
        if translation_retry:
            self.action.setText(tr("error_translation_retry"))
            self.action.setEnabled(parent.resume_btn.isEnabled())
            def retry() -> None:
                self.accept()
                parent._resume()
            self.action.clicked.connect(retry)
        elif reference and hasattr(parent, "_browse_ref_audio"):
            def choose_reference() -> None:
                self.accept()
                parent._browse_ref_audio()
            self.action.clicked.connect(choose_reference)
        else:
            self.action.clicked.connect(self.accept)
        footer.addWidget(self.action)
        layout.addLayout(footer)

        t = tokens_for(self._theme)
        self.setStyleSheet(f"""
            QFrame#errorCard {{ background: {t.sheet}; border: 1px solid {t.lineStrong}; border-radius: 14px; }}
            QLabel {{ background: transparent; color: {t.ink}; border: none; }}
            QLabel#errorEyebrow {{ color: {t.muted}; font-size: 12px; }}
            QLabel#errorHeading {{ font-size: 20px; font-weight: 600; }}
            QLabel#errorSummary {{ color: {t.muted}; font-size: 14px; }}
            QLabel#errorIcon {{ color: {t.danger}; background: {t.filamentWash}; border-radius: 20px; font-size: 24px; font-weight: 600; }}
            QPushButton {{ color: {t.ink}; background: {t.sheet}; border: 1px solid {t.lineStrong}; border-radius: 6px; padding: 8px 14px; font-size: 14px; }}
            QPushButton:hover {{ background: {t.filamentWash}; }}
            QPushButton:focus {{ border: 2px solid {t.filament}; }}
            QPushButton#errorPrimary {{ color: {t.filamentInk}; background: {t.filament}; border-color: {t.filament}; font-weight: 600; }}
            QPushButton#errorPrimary:hover {{ background: {t.filamentHover}; }}
            QPushButton#errorPrimary:focus {{ border-color: {t.ink}; }}
            QPushButton#errorDetailsToggle {{ color: {t.muted}; border: none; padding: 4px 0; text-align: left; }}
            QPushButton#errorDetailsToggle:focus {{ color: {t.ink}; text-decoration: underline; }}
            QPushButton#errorDismiss {{ border: none; padding: 0; font-size: 22px; }}
            QPlainTextEdit#errorDetails {{ color: {t.ink}; background: {t.paper}; border: 1px solid {t.line}; border-radius: 6px; padding: 10px; font-size: 13px; }}
        """)
        self.setFont(type_font(size=14))
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.action.setDefault(True)
        screen = parent.screen().availableGeometry()
        self.setFixedWidth(min(600, screen.width() - 32))
        self.details.setFixedHeight(min(200, max(80, screen.height() - 420)))
        self.action.setFocus()

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if handle:
                handle.startSystemMove()
        return super().eventFilter(watched, event)

    def _toggle_details(self, expanded: bool) -> None:
        self.details.setVisible(expanded)
        self.details_toggle.setText(tr("error_details_hide") if expanded else tr("error_details"))
        self.adjustSize()

    def _copy_details(self) -> None:
        QApplication.clipboard().setText(self.safe_details)
        self.copy_button.setText(tr("error_copied"))


def show_error(parent, details: str, *, preview: bool = False, translation_retry: bool = False) -> ErrorDialog:
    previous = getattr(parent, "_error_dialog", None)
    if previous is not None:
        previous.close()
        previous.deleteLater()
    dialog = ErrorDialog(parent, details, preview=preview, translation_retry=translation_retry)
    parent._error_dialog = dialog
    dialog.open()
    return dialog
