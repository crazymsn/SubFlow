"""Product identity — SubFlow 语幕 by 深度云创科技."""

from __future__ import annotations

import sys
from pathlib import Path

PRODUCT_EN = "SubFlow"
PRODUCT_ZH = "语幕"
PRODUCT_FULL = f"{PRODUCT_EN} {PRODUCT_ZH}"
COMPANY_ZH = "深度云创科技"
COMPANY_URL = "https://nav.meding.site"
COMPANY_EN = "DeepCloud"
WINDOW_TITLE = PRODUCT_FULL
TAGLINE = "新一代 AI 视频语音识别、自动翻译、字幕生成工具"
CLI_NAME = "subflow"
APP_USER_MODEL_ID = "tech.deepcloud.subflow"
API_PORTAL_URL = "https://api.meding.site"
GITHUB_URL = "https://github.com/crazymsn/SubFlow"


def _brand_candidates() -> list[Path]:
    module = Path(__file__).resolve()
    roots = [module.parent / "_data" / "brand"]
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve().parent
        meipass = Path(getattr(sys, "_MEIPASS", exe))
        roots.extend(
            (
                meipass / "bilingual_sub" / "_data" / "brand",
                exe / "_internal" / "bilingual_sub" / "_data" / "brand",
                exe / "brand",
            )
        )
    # brand.py -> bilingual_sub -> src -> repo
    roots.append(module.parents[2] / "assets" / "brand")
    return roots


def brand_dir() -> Path:
    fallback = _brand_candidates()[-1]
    for path in _brand_candidates():
        try:
            if path.is_dir() and (path / "subflow.png").is_file():
                return path
        except OSError:
            continue
    for path in _brand_candidates():
        if path.is_dir():
            return path
    return fallback


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
