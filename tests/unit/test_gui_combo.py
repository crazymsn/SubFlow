import os

import pytest

from bilingual_sub.brand import WINDOW_TITLE, brand_dir, icon_path, logo_path, mark_path
from bilingual_sub.gui.model_choice import merge_model_list, preferred_model

pytest.importorskip("PySide6")


def test_brand_files_exist():
    assert logo_path().is_file()
    assert mark_path().is_file()
    assert icon_path().is_file()
    assert mark_path().name == "subflow-mark.png"
    assert WINDOW_TITLE == "深度云创科技"
    assert (brand_dir() / "check-on.png").is_file()
    assert (brand_dir() / "check-off.png").is_file()


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

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(app_qss())
    win = MainWindow()
    assert not win.out_edit.isReadOnly()
    assert win.out_edit.isEnabled()
    assert win.browse_out_btn.text() == "浏览"
    first = Path(r"C:\media\one.mp4")
    win._set_video(first)
    assert win.out_edit.text() == str(default_output_mp4(first))
    custom = Path(r"D:\exports\final.mp4")
    win.out_edit.setText(str(custom))
    assert win.out_edit.text() == str(custom)
    win._set_video(Path(r"C:\media\two.mp4"))
    assert win.out_edit.text() == str(Path(r"D:\exports\two-中英字幕.mp4"))
    win.close()
    _ = app


def test_window_chrome():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel

    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.styles import app_qss

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(app_qss())
    win = MainWindow()
    assert win.windowTitle() == "深度云创科技"
    labels = win.findChildren(QLabel)
    assert any(lbl.text() == "SubFlow 语幕" for lbl in labels)
    assert all(lbl.objectName() != "company" for lbl in labels)
    assert win.burn_check.text() == "烧录到视频"
    win.close()
    _ = app
