from bilingual_sub.config import load_ui_theme
from bilingual_sub.gui.styles import app_qss
from bilingual_sub.gui.theme import (
    BRAND,
    BRAND_HOVER,
    BRAND_INK,
    BRAND_PRESSED,
    DARK,
    LIGHT,
    STACKS,
    TYPE,
    UI_FAMILIES,
    contrast_ratio,
    mix_hex,
    qss_selector_colors,
    tokens_for,
    type_font,
)


def test_token_pairs_meet_aa():
    for theme in (LIGHT, DARK):
        assert contrast_ratio(theme.ink, theme.paper) >= 4.5
        assert contrast_ratio(theme.muted, theme.paper) >= 4.5
        assert contrast_ratio(theme.filamentInk, theme.filament) >= 4.5
        assert contrast_ratio(theme.filamentInk, theme.filamentHover) >= 4.5
        assert contrast_ratio(theme.filamentInk, theme.filamentPressed) >= 4.5
        assert contrast_ratio(theme.logFg, theme.sheet) >= 4.5


def test_progress_counter_meets_large_text_contrast_in_both_themes():
    for name in ("light", "dark"):
        colors = qss_selector_colors(app_qss(name), "QLabel#pct")
        assert colors and contrast_ratio(colors[0], tokens_for(name).sheet) >= 3


def test_filament_is_not_label_or_help_ink():
    for name in ("light", "dark"):
        tokens = tokens_for(name)
        qss = app_qss(name)
        for selector in ("QLabel#fieldLabel", "QLabel#help"):
            colors = qss_selector_colors(qss, selector)
            assert colors, f"{name} {selector} missing color"
            assert tokens.filament not in colors
            assert all(color == tokens.muted for color in colors)


def test_brand_button_is_identical_in_light_and_dark():
    assert LIGHT.filament == DARK.filament == BRAND
    assert LIGHT.filamentHover == DARK.filamentHover == BRAND_HOVER
    assert LIGHT.filamentPressed == DARK.filamentPressed == BRAND_PRESSED
    assert LIGHT.filamentInk == DARK.filamentInk == BRAND_INK


def test_mix_hex_midpoint():
    assert mix_hex("#000000", "#FFFFFF", 0.5) == "#808080"


def test_ghost_and_quiet_share_hover():
    qss = app_qss("light")
    assert "QPushButton#ghost:hover, QPushButton#quiet:hover" in qss
    assert "QPushButton#ghost, QPushButton#quiet" in qss


def test_brand_ghost_hover_matches_check_wash():
    from bilingual_sub.gui.theme import LIGHT

    qss = app_qss("light")
    assert LIGHT.filament in qss
    assert LIGHT.filamentWash in qss
    for selector in (
        "QPushButton#brandGhost:hover",
        "QPushButton#ghost:hover, QPushButton#quiet:hover",
        "QPushButton#danger:hover",
        "QToolButton#githubBtn:hover",
    ):
        assert selector in qss
        block = qss.split(selector, 1)[1].split("}", 1)[0]
        assert LIGHT.filamentWash in block
        assert LIGHT.filament in block


def test_type_scale_is_five_rungs():
    assert TYPE.caption == "12px"
    assert TYPE.body == "13px"
    assert TYPE.ui == "14px"
    assert TYPE.stage == "14px"
    assert TYPE.title == "20px"
    assert TYPE.counter == "32px"


def test_qss_shares_one_cjk_stack():
    qss = app_qss("light")
    assert "Microsoft YaHei UI" in qss
    assert STACKS.uiFamily in qss
    assert STACKS.displayFamily in qss
    assert STACKS.monoFamily in qss
    assert "letter-spacing: 0.8px" not in qss
    assert UI_FAMILIES[0] == "Microsoft YaHei UI"


def test_type_font_prefers_yahei():
    font = type_font(size=14)
    families = list(font.families())
    assert families[0] == "Microsoft YaHei UI"
    assert font.pixelSize() == 14


def test_default_theme_is_dark(tmp_path, monkeypatch):
    monkeypatch.setattr("bilingual_sub.config._user_config_path", lambda: tmp_path / "missing.yaml")
    assert load_ui_theme() == "dark"
