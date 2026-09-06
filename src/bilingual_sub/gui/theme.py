"""Telecine-console tokens. Widgets must not hardcode hex."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import brand_rc  # noqa: F401


@dataclass(frozen=True)
class ThemeTokens:
    paper: str
    ink: str
    muted: str
    sheet: str
    line: str
    lineStrong: str
    filament: str
    filamentHover: str
    filamentPressed: str
    filamentLine: str
    filamentInk: str
    filamentWash: str
    danger: str
    dangerLine: str
    select: str
    disabledFill: str
    disabledFg: str
    logFg: str


@dataclass(frozen=True)
class TypeScale:
    caption: str = "12px"
    body: str = "13px"
    ui: str = "14px"
    title: str = "20px"
    stage: str = "14px"
    counter: str = "32px"


@dataclass(frozen=True)
class FontStacks:
    uiFamily: str = '"Microsoft YaHei UI", "Segoe UI Variable Text", "Segoe UI", "PingFang SC", sans-serif'
    displayFamily: str = '"Microsoft YaHei UI", "Segoe UI Variable Display", "Segoe UI", "PingFang SC", sans-serif'
    monoFamily: str = '"Cascadia Mono", "Consolas", monospace'


UI_FAMILIES = ("Microsoft YaHei UI", "Segoe UI Variable Text", "Segoe UI", "PingFang SC")
DISPLAY_FAMILIES = ("Microsoft YaHei UI", "Segoe UI Variable Display", "Segoe UI", "PingFang SC")
STACKS = FontStacks()


# Cursor Build button — sampled from the composer split key.
# Fill #F1B467, ink #141414; identical in light and dark.
BRAND = "#F1B467"
BRAND_HOVER = "#F2BC76"
BRAND_PRESSED = "#DEA65F"
BRAND_INK = "#141414"


LIGHT = ThemeTokens(
    paper="#E6E7EA",
    ink="#16181D",
    muted="#5C616A",
    sheet="#F7F8FA",
    line="#C9CDD4",
    lineStrong="#A8AEB8",
    filament=BRAND,
    filamentHover=BRAND_HOVER,
    filamentPressed=BRAND_PRESSED,
    filamentLine=BRAND,
    filamentInk=BRAND_INK,
    filamentWash="#F6ECE0",
    danger="#A14A3C",
    dangerLine="#C48A80",
    select="#E8DCC4",
    disabledFill="#D5D8DE",
    disabledFg="#8A9099",
    logFg="#16181D",
)

DARK = ThemeTokens(
    paper="#0C0D10",
    ink="#F2EFE8",
    muted="#9A968C",
    sheet="#16181E",
    line="#2A2D36",
    lineStrong="#4A4F5A",
    filament=BRAND,
    filamentHover=BRAND_HOVER,
    filamentPressed=BRAND_PRESSED,
    filamentLine=BRAND,
    filamentInk=BRAND_INK,
    filamentWash="#3D342B",
    danger="#D4A090",
    dangerLine="#5A3A38",
    select="#3A2E20",
    disabledFill="#3A3A40",
    disabledFg="#8A8074",
    logFg="#F2EFE8",
)

TYPE = TypeScale()


def type_font(*, size: int = 14, weight: int | None = None, display: bool = False):
    from PySide6.QtGui import QFont

    font = QFont()
    font.setFamilies(list(DISPLAY_FAMILIES if display else UI_FAMILIES))
    font.setPixelSize(size)
    font.setWeight(QFont.Weight(weight) if weight is not None else QFont.Weight.Normal)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def tokens_for(theme: str = "light") -> ThemeTokens:
    return DARK if theme == "dark" else LIGHT


def _channel(value: float) -> float:
    value = value / 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    raw = hex_color.lstrip("#")
    r, g, b = int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(fg: str, bg: str) -> float:
    light, dark = sorted((relative_luminance(fg), relative_luminance(bg)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def mix_hex(a: str, b: str, t: float) -> str:
    def channels(hex_color: str) -> tuple[int, int, int]:
        raw = hex_color.lstrip("#")
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)

    ar, ag, ab = channels(a)
    br, bg, bb = channels(b)
    return f"#{round(ar + (br - ar) * t):02X}{round(ag + (bg - ag) * t):02X}{round(ab + (bb - ab) * t):02X}"


def qss_selector_colors(qss: str, selector: str) -> list[str]:
    import re

    colors: list[str] = []
    for match in re.finditer(rf"{re.escape(selector)}\s*\{{([^}}]+)\}}", qss):
        colors.extend(re.findall(r"(?m)^\s*color:\s*(#[0-9A-Fa-f]{6})", match.group(1)))
    return colors


def app_qss(theme: str = "light") -> str:
    tokens = tokens_for(theme)
    mapping = {**asdict(tokens), **asdict(TYPE), **asdict(STACKS)}
    mapping["counterInk"] = tokens.filament if theme == "dark" else tokens.ink
    qss = _QSS
    for key, value in sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True):
        qss = qss.replace(f"${key}", str(value))
    return qss


_QSS = """
QWidget#workspace { background: transparent; }
QLabel#sectionTitle {
    font-family: $uiFamily; font-size: 15px; font-weight: 600; color: $ink;
}
QLabel#stepBadge {
    background: $filamentWash; color: $ink; border: 1px solid $line;
    border-radius: 8px; font-family: $uiFamily; font-size: 12px; font-weight: 600;
}
QLabel#voiceNote {
    background: $paper; color: $muted; padding: 12px; border-radius: 8px;
    font-family: $uiFamily; font-size: $body;
}
QLabel#serviceStatus {
    color: $muted; font-family: $uiFamily; font-size: $body;
}
QFrame#urlCompose { background: transparent; border: none; }
QLabel#drop:focus { border: 2px solid $filament; }
QToolButton:focus { border: 1px solid $filament; }
QLineEdit:disabled, QComboBox:disabled { color: $disabledFg; background: $disabledFill; }

QMainWindow, QWidget#root {
    background: $paper;
    color: $ink;
    font-family: $uiFamily;
    font-size: $ui;
}
QWidget#formInner, QWidget#formViewport, QWidget#fieldCol, QWidget#headerTitles, QWidget#localeCluster, QWidget#moreBox, QWidget#sourceStrip, QWidget#sourceLink, QWidget#sourceStation, QWidget#moreTrack, QWidget#outCluster, QWidget#deck, QWidget#stage {
    background: transparent;
}
QLabel {
    color: $ink;
    background: transparent;
}
QToolButton#brandTitle, QLabel#productTitle {
    font-family: $displayFamily;
    font-size: $title;
    font-weight: 600;
    letter-spacing: 0.3px;
    color: $ink;
    padding: 0;
}
QToolButton#brandTitle, QLabel#productTitle {
    font-size: 24px;
}
QToolButton#brandTitle, QToolButton#brandTitle:hover, QToolButton#brandTitle:pressed, QToolButton#brandTitle:focus {
    background: transparent;
    border: none;
    color: $ink;
    text-decoration: none;
}
QLabel#section {
    color: $muted;
    font-family: $uiFamily;
    font-size: $caption;
    font-weight: 600;
    letter-spacing: 0.4px;
    padding: 0;
}
QLabel#gpuStatus {
    font-family: $uiFamily;
    font-size: $ui;
    color: $ink;
    border: none;
    padding: 8px;
}
QLabel#fieldLabel {
    color: $muted;
    font-family: $uiFamily;
    font-size: $caption;
    font-weight: 600;
    letter-spacing: 0.4px;
    padding: 0;
}
QLabel#outLabel {
    color: $ink;
    font-family: $uiFamily;
    font-size: $ui;
    font-weight: 600;
    letter-spacing: 0.2px;
    padding: 0 4px 0 0;
}
QLabel#hint, QLabel#help {
    color: $muted;
    font-family: $uiFamily;
    font-size: $body;
    line-height: 1.45;
    padding: 0;
}
QLabel#logoMark {
    background: transparent;
    border: none;
    padding: 0;
}
QLabel#stageNow {
    color: $ink;
    font-family: $uiFamily;
    font-size: $stage;
    font-weight: 500;
    letter-spacing: 0.2px;
    padding: 0 0 0 10px;
    border-left: 2px solid $filament;
}
QLabel#stageNow[failed="true"] {
    color: $danger;
    border-left-color: $danger;
}
QLabel#pct {
    font-family: $displayFamily;
    color: $counterInk;
    font-size: $counter;
    font-weight: 500;
    letter-spacing: 0.3px;
    padding: 0 2px 0 0;
}
QFrame#sourceStrip, QFrame#deck, QFrame#actionBar, QFrame#voiceCard, QFrame#settingsCard {
    background: $sheet;
    border: 1px solid $line;
    border-radius: 12px;
}
QFrame#stage {
    background: $sheet;
    border: 1px solid $line;
    border-radius: 12px;
}
QFrame#rule, QFrame#headerRule {
    background: $line;
    border: none;
    max-height: 1px;
    min-height: 1px;
}
QFrame#stageRule {
    background: $filament;
    border: none;
    max-height: 2px;
    min-height: 2px;
}
QFrame#moreDrawer, QWidget#moreBox {
    background: transparent;
    border: none;
}
QWidget#nested, QWidget#moreTrack {
    background: transparent;
    border: none;
}
QFrame#sourceLink {
    background: transparent;
    border: none;
}
QLabel#drop {
    background: $paper;
    border: 1px dashed $filament;
    border-radius: 6px;
}
QLabel#drop {
    color: $muted;
    padding: 0 20px;
    font-family: $uiFamily;
    font-size: $ui;
}
QLabel#drop[active="true"] {
    border-style: solid;
    color: $ink;
    background: $sheet;
}
QFrame#actionBar QLineEdit#outEdit {
    min-height: 36px;
    max-height: 36px;
    padding: 0 12px;
    font-size: $ui;
    font-weight: 400;
    font-family: $uiFamily;
}
QFrame#actionBar QPushButton#ghost {
    min-height: 36px;
    max-height: 36px;
    padding: 0 14px;
}
QFrame#urlCompose QLineEdit#urlEdit {
    background: $sheet;
    border: 1px solid $line;
    border-radius: 6px;
    padding: 0 14px;
    min-height: 44px;
    max-height: 44px;
    font-family: $uiFamily;
    font-size: $ui;
}
QFrame#urlCompose QPushButton#composeGo {
    min-width: 80px;
    max-width: 80px;
    min-height: 44px;
    max-height: 44px;
    padding: 0 18px;
}
QToolButton#githubBtn {
    background: $paper;
    border: 1px solid $line;
    border-radius: 6px;
    padding: 0;
}
QToolButton#githubBtn:hover {
    border: 1px solid $filament;
    border-radius: 6px;
    background: $filamentWash;
}
QScrollArea#formScroll {
    background: transparent;
    border: none;
}
QLineEdit, QComboBox {
    background: $paper;
    border: 1px solid $line;
    border-radius: 6px;
    padding: 8px 12px;
    min-height: 20px;
    color: $ink;
    font-family: $uiFamily;
    font-size: $ui;
    font-weight: 400;
    selection-background-color: $filament;
    selection-color: $filamentInk;
}
QComboBox {
    combobox-popup: 0;
    padding-right: 28px;
}
QComboBox#localeCombo, QComboBox#themeCombo {
    padding: 0 30px 0 12px;
    font-size: 16px;
}
QComboBox#localeCombo QAbstractItemView, QComboBox#themeCombo QAbstractItemView {
    font-size: 16px;
}
QLineEdit:hover, QComboBox:hover {
    border-color: $lineStrong;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {
    border: 1px solid $filament;
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
    background: $sheet;
    color: $ink;
    border: 1px solid $line;
    outline: 0;
    font-family: $uiFamily;
    font-size: $ui;
    selection-background-color: $select;
    selection-color: $ink;
}
QComboBox QAbstractItemView::item {
    min-height: 34px;
    padding: 6px 12px;
}
QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected {
    background: $select;
    color: $ink;
}
QCheckBox {
    color: $ink;
    spacing: 8px;
    min-height: 28px;
    font-family: $uiFamily;
    font-size: $ui;
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
    border-radius: 6px;
    padding: 8px 16px;
    font-family: $uiFamily;
    font-weight: 600;
    font-size: $ui;
    letter-spacing: 0.2px;
    min-height: 20px;
}
QPushButton:focus {
    border: 1px solid $filament;
}
QPushButton#primary, QFrame#urlCompose QPushButton#composeGo {
    background: transparent;
    color: $filamentInk;
    border: none;
    font-weight: 600;
    letter-spacing: 0.2px;
}
QPushButton#primary {
    min-height: 40px;
    max-height: 40px;
    min-width: 156px;
    padding: 0 22px;
}
QPushButton#primary:hover, QFrame#urlCompose QPushButton#composeGo:hover,
QPushButton#primary:pressed, QFrame#urlCompose QPushButton#composeGo:pressed,
QPushButton#primary:disabled, QFrame#urlCompose QPushButton#composeGo:disabled,
QPushButton#primary:focus, QFrame#urlCompose QPushButton#composeGo:focus {
    background: transparent;
    border: none;
}
QPushButton#colorChip, QPushButton#zhColorBtn, QPushButton#enColorBtn {
    background: $sheet;
    color: $ink;
    border: 1px solid $line;
    min-height: 36px;
    max-height: 36px;
    padding: 0 12px 0 8px;
    font-weight: 500;
    text-align: left;
}
QPushButton#colorChip:hover, QPushButton#zhColorBtn:hover, QPushButton#enColorBtn:hover {
    border-color: $filament;
    background: $filamentWash;
}
QPushButton#brandGhost {
    background: transparent;
    color: $ink;
    border: 1px solid $line;
    min-height: 36px;
    max-height: 36px;
    padding: 0 14px;
}
QPushButton#brandGhost:hover {
    border-color: $filament;
    background: $filamentWash;
}
QPushButton#brandGhost:pressed {
    border-color: $filamentPressed;
    background: $filamentHover;
}
QPushButton#brandGhost:disabled {
    color: $disabledFg;
    border-color: $line;
    background: transparent;
}
QPushButton#ghost, QPushButton#quiet {
    background: transparent;
    color: $ink;
    border: 1px solid $line;
    min-height: 36px;
    max-height: 36px;
    padding: 0 14px;
}
QPushButton#ghost:hover, QPushButton#quiet:hover {
    border-color: $filament;
    background: $filamentWash;
}
QPushButton#ghost:pressed, QPushButton#quiet:pressed {
    border-color: $filamentPressed;
    background: $filamentHover;
}
QPushButton#ghost:disabled, QPushButton#quiet:disabled {
    color: $disabledFg;
    border-color: $line;
    background: transparent;
}
QPushButton#ttsPreviewBtn {
    background: transparent;
    color: $ink;
    border: 1px solid $line;
    min-height: 36px;
    max-height: 36px;
    padding: 0 14px;
}
QPushButton#ttsPreviewBtn:hover {
    border-color: $filament;
    background: $filamentWash;
}
QPushButton#ttsPreviewBtn:pressed {
    border-color: $filamentPressed;
    background: $filamentHover;
}
QPushButton#ttsPreviewBtn:disabled {
    color: $disabledFg;
    border-color: $line;
    background: transparent;
}
QPushButton#danger {
    background: transparent;
    color: $danger;
    border: 1px solid $dangerLine;
    min-height: 36px;
    max-height: 36px;
    padding: 0 14px;
}
QPushButton#danger:hover {
    border-color: $filament;
    background: $filamentWash;
}
QPushButton#danger:pressed {
    border-color: $filamentPressed;
    background: $filamentHover;
}
QPushButton#danger:disabled { color: $disabledFg; border-color: $line; }
QProgressBar {
    background: $line;
    border: none;
    border-radius: 2px;
    min-height: 4px;
    max-height: 4px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background: $filament;
    border-radius: 2px;
}
QPlainTextEdit {
    background: $paper;
    border: 1px solid $line;
    border-radius: 6px;
    color: $logFg;
    padding: 12px 14px;
    font-family: $monoFamily;
    font-size: $body;
    line-height: 1.4;
}
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: $lineStrong;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QToolTip {
    background: $sheet;
    color: $ink;
    border: 1px solid $line;
    padding: 6px 10px;
    font-family: $uiFamily;
    font-size: $body;
}
QMessageBox {
    background: $sheet;
}
QMessageBox QLabel {
    color: $ink;
    font-family: $uiFamily;
    font-size: $ui;
}
QMessageBox QPushButton {
    color: $filamentInk;
    background: $filament;
    border: 1px solid $filamentLine;
    border-radius: 6px;
    min-width: 80px;
    min-height: 32px;
    padding: 4px 14px;
}
QMessageBox QPushButton:hover { background: $filamentHover; }
QMessageBox QPushButton:focus { border: 2px solid $ink; }
"""
