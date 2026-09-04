"""Product identity — SubFlow 语幕 by 深度云创科技."""

from __future__ import annotations

from pathlib import Path

PRODUCT_EN = "SubFlow"
PRODUCT_ZH = "语幕"
PRODUCT_FULL = f"{PRODUCT_EN} {PRODUCT_ZH}"
COMPANY_ZH = "深度云创科技"
COMPANY_EN = "DeepCloud"
WINDOW_TITLE = COMPANY_ZH
TAGLINE = "新一代 AI 视频语音识别、自动翻译、字幕生成工具"
CLI_NAME = "subflow"
APP_USER_MODEL_ID = "tech.deepcloud.subflow"
API_PORTAL_URL = "https://api.meding.site"
GITHUB_URL = "https://github.com/crazymsn/SubFlow"


def brand_dir() -> Path:
    bundled = Path(__file__).resolve().parent / "_data" / "brand"
    if bundled.is_dir():
        return bundled
    repo = Path(__file__).resolve().parents[2] / "assets" / "brand"
    return repo


def logo_path() -> Path:
    d = brand_dir()
    for name in ("subflow.png", "deepcloud.png", "deepcloud.jpg"):
        p = d / name
        if p.is_file():
            return p
    return d / "subflow.png"


def mark_path() -> Path:
    mark = brand_dir() / "subflow-mark.png"
    return mark if mark.is_file() else logo_path()


def icon_path() -> Path:
    ico = brand_dir() / "subflow.ico"
    return ico if ico.is_file() else mark_path()
