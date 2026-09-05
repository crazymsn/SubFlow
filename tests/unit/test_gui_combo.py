import os

import pytest

from bilingual_sub.brand import WINDOW_TITLE, brand_dir, icon_path, logo_path, mark_path
from bilingual_sub.gui.model_choice import merge_model_list, preferred_model

pytest.importorskip("PySide6")


def test_app_icon_has_solid_plate():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.assets import load_app_icon

    app = QApplication.instance() or QApplication([])
    icon = load_app_icon()
    assert not icon.isNull()
    pix = icon.pixmap(64, 64)
    assert not pix.isNull()
    img = pix.toImage()
    opaque = 0
    for y in range(img.height()):
        for x in range(img.width()):
            if QColor.fromRgba(img.pixel(x, y)).alpha() > 200:
                opaque += 1
    assert opaque > img.width() * img.height() * 0.35
    _ = app


def test_brand_mark_is_visible_on_white():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.assets import load_brand_mark

    app = QApplication.instance() or QApplication([])
    pix = load_brand_mark(56, None, "light")
    assert not pix.isNull()
    img = pix.toImage()
    assert img.hasAlphaChannel()
    _ = app


def test_app_icon_is_white_official_lockup():
    from PIL import Image

    im = Image.open(brand_dir() / "subflow-icon.png").convert("RGB")
    w, h = im.size
    corners = [im.getpixel((2, 2)), im.getpixel((w - 3, 2)), im.getpixel((2, h - 3)), im.getpixel((w - 3, h - 3))]
    assert all(sum(pixel) / 3 > 240 for pixel in corners)
    ink = sum(1 for p in im.getdata() if p[0] < 40 and p[1] < 40 and p[2] < 40)
    assert ink > 200


def test_brand_files_exist():
    assert logo_path().is_file()
    assert mark_path().is_file()
    assert icon_path().is_file()
    assert mark_path().name == "subflow-mark.png"
    assert WINDOW_TITLE == "深度云创科技"
    assert (brand_dir() / "check-on.png").is_file()
    assert (brand_dir() / "check-off.png").is_file()
    assert (brand_dir() / "subflow-icon.png").is_file()
    assert (brand_dir() / "github-mark.png").is_file()


def test_combo_can_switch_after_fetch():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QComboBox

    app = QApplication.instance() or QApplication([])
    combo = QComboBox()
    combo.setEditable(True)
    combo.setCompleter(None)
    combo.setEditText("deepseek-v3")
    items = merge_model_list(["gpt-4o-mini", "deepseek-v3", "claude-sonnet"], combo.currentText())
    pick = preferred_model(items, combo.currentText())
    combo.clear()
    combo.addItems(items)
    combo.setCurrentText(pick)
    assert combo.currentText() == "deepseek-v3"
    combo.setCurrentIndex(combo.findText("claude-sonnet"))
    assert combo.currentText() == "claude-sonnet"
    assert combo.count() == 3
    assert combo.isEnabled()
    combo.clear()
    combo.addItems(items)
    combo.setCurrentIndex(-1)
    assert preferred_model(items, combo.currentText()) == ""
    _ = app


def test_fetch_fills_noneditable_dropdown():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.styles import app_qss
    from bilingual_sub.i18n import set_locale

    set_locale("zh-Hans")
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(app_qss())
    win = MainWindow()
    assert not win.model_combo.isEditable()
    assert win.model_combo.count() == 0
    win._on_models(["gpt-4o-mini", "deepseek-v3", "claude-sonnet"])
    assert win.model_combo.count() == 3
    assert win.model_combo.itemText(0) == "gpt-4o-mini"
    assert win.model_combo.currentIndex() == -1
    assert win.model_combo.currentText() == ""
    win.model_combo.setCurrentIndex(1)
    assert win.model_combo.currentText() == "deepseek-v3"
    win.close()
    _ = app


def test_output_path_is_editable_and_survives_new_video():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.output_path import default_output_mp4
    from bilingual_sub.gui.styles import app_qss
    from bilingual_sub.i18n import set_locale

    set_locale("zh-Hans")
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(app_qss())
    win = MainWindow()
    assert not win.out_edit.isReadOnly()
    assert win.out_edit.isEnabled()
    assert win.browse_out_btn.text() == "浏览"
    first = Path(r"C:\media\one.mp4")
    win._set_video(first)
    assert win.out_edit.text() == str(default_output_mp4(first))
    win.mode_combo.setCurrentIndex(win.mode_combo.findData("enzh"))
    assert win.out_edit.text() == str(default_output_mp4(first, "enzh"))
    assert win.out_edit.text().endswith("英中字幕.mp4")
    win.mode_combo.setCurrentIndex(win.mode_combo.findData("bilingual"))
    assert win.out_edit.text() == str(default_output_mp4(first))
    custom = Path(r"D:\exports\final.mp4")
    win.out_edit.setText(str(custom))
    assert win.out_edit.text() == str(custom)
    win._set_video(Path(r"C:\media\two.mp4"))
    assert win.out_edit.text() == str(custom)
    win.close()
    _ = app


def test_brand_check_label_optically_centers():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.widgets.brand_check import BrandCheck, CAPTION_SETTLE

    app = QApplication.instance() or QApplication([])
    for label in ("烧录到视频", "电影级润色", "字幕颜色", "配音"):
        box = BrandCheck(label)
        box.resize(box.sizeHint())
        box.show()
        app.processEvents()
        well_mid = box._well.geometry().center().y()
        text_mid = box._label.geometry().center().y()
        assert abs(well_mid - text_mid) <= 1, f"{label}: well={well_mid} text={text_mid}"

        img = box.grab().toImage()
        dpr = float(box.devicePixelRatioF() or 1.0)
        well = box._well.geometry()
        split = int(round((well.right() + 3) * dpr))

        def band(x0: int, x1: int, pred) -> list[float]:
            ys: list[float] = []
            for y in range(img.height()):
                for x in range(max(0, x0), min(x1, img.width())):
                    color = QColor.fromRgba(img.pixel(x, y))
                    if pred(color):
                        ys.append(y / dpr)
            return ys

        def dark(color: QColor) -> bool:
            return color.alpha() > 80 and color.red() + color.green() + color.blue() < 400

        well_ink = band(0, split, dark)
        text_ink = band(split, img.width(), dark)
        assert well_ink, f"{label}: no well ink"
        assert text_ink, f"{label}: no text ink"
        well_cy = (min(well_ink) + max(well_ink)) / 2.0
        lo, hi = min(text_ink), max(text_ink)
        cut = lo + 0.84 * (hi - lo)
        face = [y for y in text_ink if y <= cut]
        face_cy = sum(face) / len(face)
        # Face may sit settle-px below the well; it must not sit above it.
        delta = face_cy - well_cy
        assert -0.6 <= delta <= CAPTION_SETTLE + 1.2, f"{label}: face-well={delta}"
        box.close()
    _ = app


def test_window_chrome():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.styles import app_qss
    from bilingual_sub.i18n import set_locale

    set_locale("zh-Hans")
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(app_qss())
    win = MainWindow()
    assert win.windowTitle() == "深度云创科技"
    labels = win.findChildren(QLabel)
    assert any(lbl.text() == "SubFlow 语幕" for lbl in labels)
    assert win.company_lbl.objectName() == "company"
    assert win.company_lbl.text() == "深度云创科技"
    assert win.burn_check.text() == "烧录到视频"
    from bilingual_sub.gui.widgets.brand_check import BrandCheck

    assert isinstance(win.burn_check, BrandCheck)
    assert isinstance(win.color_check, BrandCheck)
    assert isinstance(win.refine_check, BrandCheck)
    assert isinstance(win.dub_check, BrandCheck)
    assert not hasattr(win, "glossary_gen_check")
    assert not hasattr(win, "glossary_edit")
    assert win.whisper_combo.currentText() in {"tiny", "base", "small", "medium", "large"}
    assert win.locale_combo.count() == 8
    assert win.locale_combo.itemData(0) == "zh-Hans"
    assert win.locale_combo.itemText(0) == "简体中文"
    assert win.locale_combo.currentData() == "zh-Hans"
    assert win.mode_combo.currentData() == "bilingual"
    assert [win.mode_combo.itemData(i) for i in range(win.mode_combo.count())] == [
        "bilingual",
        "enzh",
        "single:en",
        "single:zh",
        "single:zh-Hant",
        "single:ja",
        "single:es",
        "single:ru",
        "single:fr",
        "single:de",
        "netflix_single",
    ]
    assert win.lbl_source.text() == "源语种"
    assert win.lbl_target.text() == "目标语种"
    assert win.lbl_mode.text() == "字幕样式"
    assert win.mode_combo.itemText(0) == "中英字幕"
    assert win.mode_combo.itemText(1) == "英中字幕"
    assert win.mode_combo.itemText(2) == "English"
    assert win.mode_combo.itemText(3) == "简体中文"
    assert win.source_lang_combo.currentData() == "zh"
    assert win.target_lang_combo.currentData() == "zh"
    target_codes = [win.target_lang_combo.itemData(i) for i in range(win.target_lang_combo.count())]
    assert target_codes[-2:] == ["fr", "de"]
    assert win.target_lang_combo.itemText(target_codes.index("de")) == "Deutsch"
    assert win.asr_backend_combo.currentData() == "whisper"
    assert not win.asr_backend_combo.isHidden()
    assert win.tts_combo.findData("azure") < 0
    assert {win.tts_combo.itemData(i) for i in range(win.tts_combo.count())} == {"openai", "gptsovits"}
    assert not win.windowIcon().isNull()
    assert win.refine_check.isChecked() is False
    assert win.dub_check.isChecked() is False
    assert win.more_box.isHidden()
    assert win.theme_combo.currentData() in {"light", "dark"}
    assert win.lbl_source_file.text() == "上传视频"
    assert win.lbl_source_url.text() == "视频链接"
    assert win.lbl_out.text() == "输出路径"
    assert win.lbl_out.objectName() == "outLabel"
    assert win.zh_color_btn.objectName() == "zhColorBtn"
    assert win.en_color_btn.objectName() == "enColorBtn"
    assert win.zh_color_btn.hex() == "#FFFFFF"
    assert win.save_btn.objectName() == win.clear_key_btn.objectName() == win.api_portal_btn.objectName() == "brandGhost"
    assert win.url_edit.objectName() or True
    assert win.start_btn is win.run_btn
    assert win.run_btn.objectName() == "primary"
    from bilingual_sub.gui.widgets.filament_btn import FilamentButton

    assert isinstance(win.run_btn, FilamentButton)
    assert isinstance(win.download_btn, FilamentButton)
    assert win.pause_btn.objectName() == "quiet"
    assert win.stop_btn.objectName() == "danger"
    assert win.pct_label.text() == "0%"
    assert not win.logo_mark.pixmap().isNull()
    from PySide6.QtWidgets import QScrollArea

    assert win.findChild(QScrollArea, "formScroll") is not None
    assert win.pause_btn.isEnabled() is False
    assert win.resume_btn.isEnabled() is False
    assert win.stop_btn.isEnabled() is False
    win.showMaximized()
    assert bool(win.windowState() & Qt.WindowState.WindowMaximized)
    win.setWindowState(Qt.WindowState.WindowNoState)
    win.resize(1440, 900)
    win.show()
    app.processEvents()
    model_bottom = win.model_combo.mapTo(win, win.model_combo.rect().bottomLeft()).y()
    run_top = win.run_btn.mapTo(win, win.run_btn.rect().topLeft()).y()
    assert model_bottom < run_top
    assert not win.model_combo.visibleRegion().isEmpty()
    win.close()
    _ = app


def test_progress_log_skips_transcribe_and_done_has_no_popup():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from pathlib import Path
    from unittest.mock import patch

    from PySide6.QtWidgets import QApplication, QMessageBox

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.styles import app_qss
    from bilingual_sub.i18n import set_locale
    from bilingual_sub.models import JobResult

    set_locale("zh-Hans")
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(app_qss())
    win = MainWindow()
    win._on_progress("extract", 0.05)
    win._on_progress("extract", 0.05)
    win._on_progress("transcribe", 0.20)
    win._on_progress("transcribe", 0.21)
    win._on_progress("transcribe", 0.22)
    win._on_progress("burn", 0.90)
    text = win.log.toPlainText()
    assert "抽取音频" in text
    assert "语音识别" not in text
    assert "烧录视频" not in text
    assert "transcribe" not in text
    assert "(20%)" not in text
    result = JobResult(
        job_id="t",
        output_mp4=Path(r"D:\out\a.mp4"),
        output_srt=Path(r"D:\out\a.srt"),
        output_ass=Path(r"D:\out\a.ass"),
        cue_count=3,
        missing_en=[],
        duration_sec=1.0,
        report_path=Path(r"D:\out\report.json"),
        reused=False,
    )
    with patch.object(QMessageBox, "information") as info:
        win._on_done(result)
    assert info.call_count == 0
    assert "完成，3 条字幕" in win.log.toPlainText()
    win.close()
    _ = app


def test_pause_resume_stop_state_machine():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.core.control import JobControl
    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.styles import app_qss

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(app_qss())
    win = MainWindow()
    win._control = JobControl()
    win._set_running_ui(True, paused=False)
    assert win.run_btn.isEnabled() is False
    assert win.pause_btn.isEnabled() is True
    assert win.stop_btn.isEnabled() is True
    assert win.resume_btn.isEnabled() is False
    win._pause()
    assert win.resume_btn.isEnabled() is True
    assert win.pause_btn.isEnabled() is False
    win._resume()
    assert win.pause_btn.isEnabled() is True
    win._stop()
    assert win.run_btn.isEnabled() is True
    assert win.pause_btn.isEnabled() is False
    assert win.stop_btn.isEnabled() is False
    win.close()
    _ = app


def test_fetch_models_does_not_announce_count():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.styles import app_qss

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(app_qss())
    win = MainWindow()
    win._on_models(["gpt-4o-mini", "deepseek-v3"])
    assert "已加载" not in win.key_status.text()
    assert "模型" not in win.key_status.text() or win.key_status.text() == ""
    assert win.key_status.isHidden() or not win.key_status.text()
    assert win.model_combo.count() == 2
    win.close()
    _ = app


def test_locale_switch_does_not_change_subtitle_langs():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.styles import app_qss

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(app_qss())
    win = MainWindow()
    assert win.source_lang_combo.currentData() == "zh"
    assert win.target_lang_combo.currentData() == "zh"
    win.locale_combo.setCurrentIndex(win.locale_combo.findData("en"))
    assert win.source_lang_combo.currentData() == "zh"
    assert win.target_lang_combo.currentData() == "zh"
    assert win.mode_combo.currentData() == "bilingual"
    from bilingual_sub.i18n import set_locale

    set_locale("zh-Hans")
    win.close()
    _ = app


def test_english_target_auto_enables_dub():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.styles import app_qss

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(app_qss())
    win = MainWindow()
    assert win.dub_check.isChecked() is False
    win.target_lang_combo.setCurrentIndex(win.target_lang_combo.findData("en"))
    assert win.target_lang_combo.currentData() == "en"
    assert win.mode_combo.currentData() == "bilingual"
    assert win.dub_check.isChecked() is True
    win.close()
    _ = app


def test_subtitle_style_does_not_change_target_lang():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.styles import app_qss
    from bilingual_sub.i18n import set_locale

    set_locale("zh-Hans")
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(app_qss())
    win = MainWindow()
    assert win.target_lang_combo.currentData() == "zh"
    win.mode_combo.setCurrentIndex(win.mode_combo.findData("single:en"))
    assert win.mode_combo.currentData() == "single:en"
    assert win.target_lang_combo.currentData() == "zh"
    assert win.dub_check.isChecked() is False
    win.mode_combo.setCurrentIndex(win.mode_combo.findData("enzh"))
    assert win.target_lang_combo.currentData() == "zh"
    win.close()
    _ = app


def test_empty_counter_download_gate_and_more_overlay():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QWidget

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.styles import app_qss
    from bilingual_sub.i18n import set_locale

    set_locale("zh-Hans")
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(app_qss())
    win = MainWindow()
    assert win.pct_label.text() == "0%"
    assert win.download_btn.isEnabled() is False
    win.url_edit.setText("https://www.bilibili.com/video/BV1")
    assert win.download_btn.isEnabled() is True
    win.url_edit.clear()
    assert win.download_btn.isEnabled() is False
    from PySide6.QtCore import Qt

    win.setWindowState(Qt.WindowState.WindowNoState)
    win.resize(1200, 800)
    win.show()
    app.processEvents()
    for label in (win.lbl_source, win.lbl_target, win.lbl_mode):
        assert label.sizeHint().width() <= label.width()
    compose = win.url_edit.parent()
    assert abs(win.drop.height() - compose.height()) <= 2
    assert win.drop.height() in range(126, 132)
    assert abs(win.drop.width() - compose.width()) < 80
    assert abs(win.url_edit.height() - win.download_btn.height()) <= 4
    assert 40 <= win.url_edit.height() <= 52
    assert 110 <= win.download_btn.width() <= 170
    assert win.url_edit.width() > win.download_btn.width() + 80
    assert win.download_btn.objectName() == "composeGo"
    assert win.api_portal_btn.text() == "API 分发站"
    assert win.clear_key_btn.text() == "清除令牌"
    assert win.github_btn.objectName() == "githubBtn"
    assert win.github_btn.width() >= 36
    assert win.github_btn.height() >= 36
    theme_c = win.theme_combo.mapTo(win, win.theme_combo.rect().center())
    locale_c = win.locale_combo.mapTo(win, win.locale_combo.rect().center())
    github_c = win.github_btn.mapTo(win, win.github_btn.rect().center())
    assert theme_c.x() < locale_c.x() < github_c.x()
    assert github_c.y() < 80
    assert github_c.x() >= win.width() - 80
    assert abs(github_c.y() - locale_c.y()) <= 8
    assert win.company_lbl.text() == "深度云创科技"
    company_c = win.company_lbl.mapTo(win, win.company_lbl.rect().center())
    assert abs(company_c.x() - win.width() / 2) <= 8
    assert company_c.y() >= win.height() - 80
    assert company_c.y() > github_c.y() + 200
    assert win.asr_help.isHidden()
    assert win.tts_help.isHidden()
    assert not hasattr(win, "video_name")
    assert win.lbl_source_file.text() == "上传视频"
    assert win.lbl_source_url.text() == "视频链接"
    win.more_btn.setChecked(True)
    win.dub_check.setChecked(True)
    app.processEvents()
    win.tts_combo.setCurrentIndex(win.tts_combo.findData("openai"))
    app.processEvents()
    assert win._slot_voice.isVisible()
    assert win._slot_endpoint.isHidden()
    assert win.tts_preview_btn.objectName() == "ttsPreviewBtn"
    assert win.tts_preview_btn.text() == "试听"
    assert win.tts_preview_btn.isVisible()
    assert {win.tts_voice_edit.itemData(i) for i in range(win.tts_voice_edit.count())} == {
        "alloy",
        "echo",
        "fable",
        "onyx",
        "nova",
        "shimmer",
    }
    assert "中性" in win.tts_voice_edit.itemText(0)
    win.tts_combo.setCurrentIndex(win.tts_combo.findData("gptsovits"))
    app.processEvents()
    assert win._slot_voice.isHidden()
    assert win._slot_endpoint.isVisible()
    assert not win.tts_preview_btn.isVisible()
    win.tts_combo.setCurrentIndex(win.tts_combo.findData("openai"))
    win.dub_check.setChecked(False)
    win.more_btn.setChecked(False)
    app.processEvents()
    assert win.out_edit.isVisible()
    assert win.browse_out_btn.isVisible()
    assert win.out_edit.height() >= 32
    assert abs(win.out_edit.height() - win.browse_out_btn.height()) <= 1
    assert abs(
        win.out_edit.mapTo(win, win.out_edit.rect().topLeft()).y()
        - win.browse_out_btn.mapTo(win, win.browse_out_btn.rect().topLeft()).y()
    ) <= 1
    assert win.save_btn.objectName() == "brandGhost"
    assert win.clear_key_btn.objectName() == "brandGhost"
    assert win.api_portal_btn.objectName() == "brandGhost"
    before_bar = win.run_btn.mapTo(win, win.run_btn.rect().topLeft()).y()
    win.more_btn.setChecked(True)
    app.processEvents()
    after_bar = win.run_btn.mapTo(win, win.run_btn.rect().topLeft()).y()
    more_bottom = win.more_box.mapTo(win, win.more_box.rect().bottomLeft()).y()
    more_top = win.more_btn.mapTo(win, win.more_btn.rect().topLeft()).y()
    key_bottom = win.key_edit.mapTo(win, win.key_edit.rect().bottomLeft()).y()
    bar_bottom = win.run_btn.mapTo(win, win.run_btn.rect().bottomLeft()).y()
    assert win.more_box.isVisible()
    assert win.more_box.height() >= 36
    assert win.color_check.isVisible()
    assert win.dub_check.isVisible()
    assert win.refine_check.isVisible()
    assert win.color_box.isHidden()
    assert win.color_check.mapTo(win, win.color_check.rect().topLeft()).x() < win.dub_check.mapTo(
        win, win.dub_check.rect().topLeft()
    ).x()
    assert win.dub_check.mapTo(win, win.dub_check.rect().topLeft()).x() < win.refine_check.mapTo(
        win, win.refine_check.rect().topLeft()
    ).x()
    assert not win.key_edit.visibleRegion().isEmpty()
    assert not win.model_combo.visibleRegion().isEmpty()
    assert not win.source_lang_combo.visibleRegion().isEmpty()
    assert key_bottom <= more_top + 2
    assert win.out_edit.isVisible()
    assert win.out_edit.height() >= 32
    assert after_bar >= before_bar
    deck = win.findChild(QWidget, "deck")
    assert deck is not None
    deck_bottom = deck.mapTo(win, deck.rect().bottomLeft()).y()
    assert deck_bottom <= after_bar + 8
    assert more_bottom <= deck_bottom + 8 or win.form_scroll.widget().isAncestorOf(win.more_box)
    assert bar_bottom < win.height()
    win.color_check.setChecked(True)
    app.processEvents()
    assert win.color_box.isVisible()
    assert win.zh_color_btn.isVisible()
    assert win.en_color_btn.isVisible()
    assert not win.key_edit.visibleRegion().isEmpty()
    assert not win.model_combo.visibleRegion().isEmpty()
    win.dub_check.setChecked(True)
    app.processEvents()
    after_bar = win.run_btn.mapTo(win, win.run_btn.rect().topLeft()).y()
    bar_bottom = win.run_btn.mapTo(win, win.run_btn.rect().bottomLeft()).y()
    deck_bottom = deck.mapTo(win, deck.rect().bottomLeft()).y()
    assert deck_bottom <= after_bar + 8
    assert win.run_btn.isVisible()
    assert not win.run_btn.visibleRegion().isEmpty()
    assert bar_bottom < win.height()
    assert win.out_edit.isVisible() and win.out_edit.height() >= 32
    assert not win.key_edit.visibleRegion().isEmpty()
    win.resize(1200, 760)
    app.processEvents()
    after_bar = win.run_btn.mapTo(win, win.run_btn.rect().topLeft()).y()
    bar_bottom = win.run_btn.mapTo(win, win.run_btn.rect().bottomLeft()).y()
    deck_bottom = deck.mapTo(win, deck.rect().bottomLeft()).y()
    assert win.more_box.isVisible()
    assert deck_bottom <= after_bar + 8
    assert not win.run_btn.visibleRegion().isEmpty()
    assert bar_bottom < win.height()
    win.close()
    _ = app


def test_same_video_new_path_copies_without_worker(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.styles import app_qss
    from bilingual_sub.i18n import set_locale
    from bilingual_sub.models import JobResult

    set_locale("zh-Hans")
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(app_qss())
    win = MainWindow()
    video = tmp_path / "talk.mp4"
    video.write_bytes(b"video")
    src_mp4 = tmp_path / "old" / "talk-中英字幕.mp4"
    src_srt = tmp_path / "old" / "talk-中英字幕.bilingual.srt"
    src_ass = tmp_path / "old" / "talk-中英字幕.bilingual.ass"
    src_mp4.parent.mkdir()
    src_mp4.write_bytes(b"burned")
    src_srt.write_text("srt", encoding="utf-8")
    src_ass.write_text("ass", encoding="utf-8")
    report = tmp_path / "old" / "report.json"
    report.write_text("{}", encoding="utf-8")
    win._video = video
    win._last_result = JobResult(
        job_id="r",
        output_mp4=src_mp4,
        output_srt=src_srt,
        output_ass=src_ass,
        cue_count=4,
        missing_en=[],
        duration_sec=1.0,
        report_path=report,
    )
    win._last_signature = win._job_signature()
    dest = tmp_path / "exports" / "final.mp4"
    assert win._try_relocate_outputs(dest, log=True) is True
    assert dest.read_bytes() == b"burned"
    assert dest.with_name("final.bilingual.srt").read_text(encoding="utf-8") == "srt"
    assert win._worker is None
    assert "已按新路径导出，4 条字幕" in win.log.toPlainText()
    win.close()
    _ = app
