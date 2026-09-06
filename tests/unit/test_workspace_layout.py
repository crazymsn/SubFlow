"""Desktop layout regressions: usable controls at every supported window size."""
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFontDatabase, QWheelEvent
from PySide6.QtWidgets import QApplication, QBoxLayout, QComboBox, QLabel, QPushButton

from bilingual_sub.gui.app import MainWindow
from bilingual_sub.gui.theme import type_font


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    if not app.property("testFontsLoaded"):
        # Isolated Windows profiles do not expose the installed CJK font registry.
        for pattern in ("msyh*.ttc", "segoeui*.ttf"):
            for path in Path("C:/Windows/Fonts").glob(pattern):
                QFontDatabase.addApplicationFont(str(path))
        app.setProperty("testFontsLoaded", True)
    app.setFont(type_font(size=14))
    win = MainWindow()
    win.show()
    app.processEvents()
    yield app, win
    win.close()
    app.processEvents()


@pytest.mark.parametrize("size", [(960, 640), (1024, 768), (1280, 800), (1440, 900)])
@pytest.mark.parametrize("locale", ["zh-Hans", "zh-Hant", "en", "ja", "de", "es", "fr", "ru"])
def test_controls_reachable_without_overlap(window, size, locale):
    app, win = window
    win._on_progress("translate", 0.6)
    win.locale_combo.setCurrentIndex(win.locale_combo.findData(locale))
    win.target_lang_combo.setCurrentIndex(win.target_lang_combo.findData("en"))
    win.resize(*size)
    win.color_check.setChecked(True)
    for _ in range(3):
        app.processEvents()
    assert win.width() == size[0] and win.height() == size[1]
    company_center = win.company_lbl.mapTo(win, win.company_lbl.rect().center()).x()
    assert abs(company_center - win.width() / 2) <= 2
    assert win.product_lbl.mapTo(win, win.product_lbl.rect().topRight()).x() < win.company_lbl.mapTo(win, QPoint()).x()
    assert win.workspace_layout.direction() == (
        QBoxLayout.Direction.LeftToRight if size[0] >= 1180 else QBoxLayout.Direction.TopToBottom
    )
    viewport = win.form_scroll.viewport()
    viewport_bottom = viewport.mapTo(win, viewport.rect().bottomLeft()).y()
    panel_bottom = win.task_panel.mapTo(win, win.task_panel.rect().bottomLeft()).y()
    action_top = win.out_edit.mapTo(win, win.out_edit.rect().topLeft()).y()
    assert viewport_bottom < action_top and panel_bottom < action_top
    assert win.task_activity.isVisible() and win.gpu_status.isHidden()
    assert win.log.geometry().bottom() <= win.task_panel.height() - 12
    assert win.log.geometry().top() > win.progress.geometry().bottom()
    for field in (win.source_lang_combo, win.tts_voice_edit, win.tts_sample_edit,
                  win.key_edit, win.model_combo, win.tts_preview_btn, win.zh_color_btn):
        win.form_scroll.ensureWidgetVisible(field, 8, 8)
        app.processEvents()
        assert not field.visibleRegion().isEmpty(), (locale, size, field.objectName())
        field_rect = field.rect().translated(field.mapTo(viewport, QPoint(0, 0)))
        assert viewport.rect().contains(field_rect), (locale, size, field_rect, viewport.rect())
    assert win.form_scroll.horizontalScrollBar().maximum() == 0
    for button in (win.run_btn, win.pause_btn, win.resume_btn, win.stop_btn, win.browse_out_btn):
        assert not button.visibleRegion().isEmpty()
        assert button.mapTo(win, button.rect().bottomRight()).y() < win.height()
    # Labels and buttons must not lose their captions in translated layouts.
    for label in win.findChildren(QLabel, "fieldLabel"):
        if label.isVisible():
            assert label.width() >= label.sizeHint().width(), (locale, label.text())
    for button in win.findChildren(QPushButton):
        if button.isVisible():
            assert button.fontMetrics().horizontalAdvance(button.text()) + 12 <= button.width(), button.text()


def test_settings_missing_token_reveal_field(window, monkeypatch):
    app, win = window
    monkeypatch.setattr("bilingual_sub.gui.app.QMessageBox.warning", lambda *a: None)
    win.url_edit.setText("https://youtu.be/sample")
    win.target_lang_combo.setCurrentIndex(win.target_lang_combo.findData("en"))
    win._start()
    app.processEvents()
    app.processEvents()
    assert not win.more_box.isHidden()
    assert win.key_edit.hasFocus()
    assert not win.key_edit.visibleRegion().isEmpty()


def test_wheel_does_not_change_voice_or_language(window):
    app, win = window
    for combo in win.findChildren(QComboBox):
        before = combo.currentIndex()
        event = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(), QPoint(0, -120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                            Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(combo, event)
        assert combo.currentIndex() == before


def test_changing_engine_clears_previous_device_status(window):
    _, win = window
    win.target_lang_combo.setCurrentIndex(win.target_lang_combo.findData("en"))
    win._on_sovits_probe(True, "cuda:0")
    assert "CUDA" in win.tts_sovits_status.text()
    win.tts_combo.setCurrentIndex(win.tts_combo.findData("gptsovits"))
    assert not win.tts_sovits_status.text()


def test_drop_card_supports_keyboard_file_selection(window, monkeypatch, tmp_path):
    from PySide6.QtTest import QTest
    _, win = window
    path = tmp_path / "sample.mp4"
    path.write_bytes(b"sample")
    monkeypatch.setattr("bilingual_sub.gui.widgets.drop_card.QFileDialog.getOpenFileName",
                        lambda *a: (str(path), ""))
    QTest.keyClick(win.drop, Qt.Key.Key_Return)
    assert win._video == path


def test_locale_change_preserves_live_and_completed_task_status(window):
    _, win = window
    win._on_progress("dub|synth|3|8|67", 0.94)
    win.locale_combo.setCurrentIndex(win.locale_combo.findData("en"))
    assert "3/8" in win.stage_label.text()
    assert win.pct_label.text() == "94%"
    win._show_stage("done_stage", n=19)
    win.locale_combo.setCurrentIndex(win.locale_combo.findData("de"))
    assert "19" in win.stage_label.text()


def test_task_buttons_and_options_accept_keyboard_focus(window):
    _, win = window
    for field in (win.run_btn, win.download_btn, win.drop, win.burn_check, win.color_check):
        assert field.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_long_filename_keeps_extension_and_full_path_tooltip(window, tmp_path):
    app, win = window
    path = tmp_path / ("long-video-title-" * 14 + ".mp4")
    win._set_video(path)
    app.processEvents()
    assert win.drop.text().endswith(".mp4")
    assert win.drop.toolTip() == str(path)
    assert win.drop.fontMetrics().horizontalAdvance(win.drop.text()) <= win.drop.width() - 40
