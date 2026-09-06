from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from bilingual_sub.gui.error_dialog import ErrorDialog, show_error
from bilingual_sub.gui.theme import contrast_ratio, tokens_for
from bilingual_sub.i18n import available_locales, tr


def test_error_details_are_plain_bounded_copyable_and_redacted(monkeypatch):
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent._theme = "dark"
    monkeypatch.setattr("bilingual_sub.gui.error_dialog.get_api_key", lambda: "private-api-token")
    raw = 'GPT-SoVITS 失败：<a href="https://example.invalid">tts failed</a> private-api-token\n' + 'C:/very-long-path/' * 1000
    dialog = show_error(parent, raw, preview=True)
    app.processEvents()
    assert dialog.heading.textFormat() == Qt.TextFormat.PlainText
    assert dialog.width() <= 600
    assert not dialog.details.isVisible()
    dialog.details_toggle.click()
    app.processEvents()
    assert dialog.details.isVisible()
    assert dialog.width() <= 600 and dialog.height() <= parent.screen().availableGeometry().height()
    assert 'private-api-token' not in dialog.details.toPlainText()
    assert '<a href=' in dialog.details.toPlainText()
    dialog.copy_button.click()
    assert app.clipboard().text() == dialog.safe_details
    assert 'private-api-token' not in app.clipboard().text()
    dialog.action.click()
    assert not dialog.isVisible()
    app.clipboard().clear()
    parent.close()


def test_reference_error_action_closes_before_browsing():
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    selected = []
    parent._browse_ref_audio = lambda: selected.append(not dialog.isVisible())
    dialog = show_error(parent, "参考音频不存在：C:/gone.wav", preview=True)
    app.processEvents()
    assert dialog.heading.text() == tr("error_reference_title")
    dialog.action.click()
    assert selected == [True]
    parent.close()


def test_dialog_copy_is_translated_and_buttons_have_contrast():
    for locale in available_locales():
        assert tr("error_copy", locale) not in {"error_copy", ""}
    for mode in ("dark", "light"):
        t = tokens_for(mode)
        assert contrast_ratio(t.ink, t.sheet) >= 4.5
        assert contrast_ratio(t.muted, t.sheet) >= 4.5
        assert contrast_ratio(t.filamentInk, t.filament) >= 4.5


def test_repeated_error_replaces_previous_dialog():
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    old = show_error(parent, "first")
    new = show_error(parent, "second")
    assert not old.isVisible()
    assert isinstance(parent._error_dialog, ErrorDialog) and new.safe_details == "second"
    parent.close()
    app.processEvents()


def test_translation_error_offers_translation_retry_without_dubbing_advice():
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resume_btn = QPushButton()
    retried = []
    parent._resume = lambda: retried.append(not dialog.isVisible())
    dialog = show_error(parent, "API timeout", translation_retry=True)
    app.processEvents()
    assert dialog.heading.text() == tr("error_translation_title")
    assert dialog.summary.text() == tr("error_translation_help")
    assert dialog.action.text() == tr("error_translation_retry")
    dialog.action.click()
    assert retried == [True]
    parent.close()
