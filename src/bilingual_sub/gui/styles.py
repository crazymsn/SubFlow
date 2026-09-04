"""Cinema-tungsten tokens. Larger type, 8px rhythm, 40px controls."""

from __future__ import annotations

from . import brand_rc  # noqa: F401


def app_qss() -> str:
    return APP_QSS


APP_QSS = """
QMainWindow, QWidget#root {
    background: #0B0D12;
    color: #F3EDE2;
    font-family: "Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI", "PingFang SC", sans-serif;
    font-size: 16px;
}
QLabel {
    color: #F3EDE2;
    background: transparent;
}
QLabel#brandTitle {
    font-size: 28px;
    font-weight: 700;
    letter-spacing: 0.4px;
    color: #F6F0E6;
    padding: 0;
}
QLabel#tagline {
    color: #A39B8C;
    font-size: 14px;
    line-height: 20px;
}
QLabel#section {
    color: #D4B27C;
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 0.6px;
    padding-top: 6px;
}
QLabel#logoMark {
    background: transparent;
    border: none;
    padding: 0;
}
QFrame#card {
    background: #141820;
    border: 1px solid #2C3346;
    border-radius: 12px;
}
QLabel#drop {
    background: #10141C;
    border: 1px dashed #6B5340;
    border-radius: 10px;
    color: #A39B8C;
    padding: 20px 16px;
    font-size: 16px;
}
QLabel#drop[active="true"] {
    border-color: #C4A06A;
    background: #1A1610;
    color: #F3EDE2;
}
QLineEdit, QComboBox {
    background: #0F131A;
    border: 1px solid #2C3346;
    border-radius: 8px;
    padding: 8px 12px;
    min-height: 28px;
    color: #F3EDE2;
    font-size: 16px;
    selection-background-color: #C4A06A;
    selection-color: #1A1208;
}
QComboBox {
    combobox-popup: 0;
    padding-right: 28px;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {
    border: 1px solid #C4A06A;
}
QComboBox::drop-down {
    border: none;
    width: 32px;
    subcontrol-origin: padding;
    subcontrol-position: center right;
}
QComboBox::down-arrow {
    image: url(":/brand/chevron-down.png");
    width: 12px;
    height: 8px;
}
QComboBox QAbstractItemView {
    background: #141820;
    color: #F3EDE2;
    border: 1px solid #2C3346;
    outline: 0;
    font-size: 16px;
    selection-background-color: #3A2E20;
    selection-color: #F3EDE2;
}
QComboBox QAbstractItemView::item {
    min-height: 34px;
    padding: 6px 12px;
}
QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected {
    background: #3A2E20;
    color: #F3EDE2;
}
QCheckBox {
    color: #E4DED2;
    spacing: 8px;
    min-height: 28px;
    font-size: 16px;
}
QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border: none;
    image: url(":/brand/check-off.png");
}
QCheckBox::indicator:checked {
    image: url(":/brand/check-on.png");
}
QPushButton {
    border-radius: 8px;
    padding: 9px 16px;
    font-weight: 600;
    font-size: 15px;
    min-height: 28px;
}
QPushButton:focus {
    border: 1px solid #C4A06A;
}
QPushButton#primary {
    background: #C4A06A;
    color: #1A1208;
    border: none;
}
QPushButton#primary:hover { background: #D4B27C; }
QPushButton#primary:disabled { background: #4A4034; color: #8A8074; }
QPushButton#ghost {
    background: transparent;
    color: #C4A06A;
    border: 1px solid #6B5340;
}
QPushButton#ghost:hover { background: #1A1610; }
QPushButton#ghost:disabled { color: #5A564E; border-color: #2C3346; }
QProgressBar {
    background: #0F131A;
    border: 1px solid #2C3346;
    border-radius: 6px;
    height: 10px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background: #C4A06A;
    border-radius: 5px;
}
QPlainTextEdit {
    background: #0C0F16;
    border: 1px solid #2C3346;
    border-radius: 10px;
    color: #D8D2C6;
    padding: 10px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 14px;
}
QSplitter::handle:horizontal {
    width: 8px;
    background: #0B0D12;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 4px;
}
QScrollBar::handle:vertical {
    background: #3A3F52;
    border-radius: 4px;
    min-height: 24px;
}
"""
