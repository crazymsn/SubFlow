from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class AsrSettings(BaseModel):
    model: str = "medium"
    language: str = "zh"
    device: str = "auto"


class SilenceSettings(BaseModel):
    noise_db: float = -32
    min_duration: float = 0.35


class CueSettings(BaseModel):
    min_duration: float = 0.90
    max_duration: float = 8.0
    silence_split_threshold: float = 0.55
    snap_tolerance: float = 0.22


class TranslateSettings(BaseModel):
    model: str = "gpt-4o-mini"
    batch_size: int = 30
    cache_enabled: bool = True
    max_en_chars: int = 120


class BurnSettings(BaseModel):
    encoder: str = "auto"
    cq: int = 18
    preset: str = "p4"


class VideoSettings(BaseModel):
    work_dir: str = "auto"
    copy_to_ascii_path: bool = True


class StyleText(BaseModel):
    font: str = "Microsoft YaHei"
    size: int = 80
    bold: bool = True
    color: str = "#FFFFFF"
    outline: float = 3.2
    shadow: float = 0
    spacing: float = 0.8


class StyleLayout(BaseModel):
    cn_y: int = 1376
    en_y: int = 1472
    anchor: str = "center"
    margin_lr: int = 160


class StylePreset(BaseModel):
    name: str = "no-plate-large"
    style: dict[str, Any] = Field(default_factory=dict)


class AppSettings(BaseModel):
    video: VideoSettings = Field(default_factory=VideoSettings)
    asr: AsrSettings = Field(default_factory=AsrSettings)
    silence: SilenceSettings = Field(default_factory=SilenceSettings)
    cues: CueSettings = Field(default_factory=CueSettings)
    translate: TranslateSettings = Field(default_factory=TranslateSettings)
    burn: BurnSettings = Field(default_factory=BurnSettings)
    style_preset: str = "no-plate-large"


def _package_root() -> Path:
    return Path(__file__).resolve().parent


def _repo_root() -> Path:
    """Project root (parent of ``src/``) in dev layout."""
    return _package_root().parents[1]


def _bundled_config_dir() -> Path:
    data = _package_root() / "_data" / "config"
    if data.is_dir():
        return data
    repo = _repo_root() / "config"
    if repo.is_dir():
        return repo
    return _package_root().parent / "config"


def user_config_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home())) / "SubFlow"
    return Path.home() / ".config" / "subflow"


def _user_config_path() -> Path:
    return user_config_dir() / "config.yaml"


def load_subtitle_colors() -> tuple[str, str]:
    from bilingual_sub.core.render import DEFAULT_EN_COLOR, DEFAULT_ZH_COLOR, normalize_hex

    data = _load_yaml(_user_config_path())
    style = data.get("style") if isinstance(data.get("style"), dict) else {}
    return (
        normalize_hex(style.get("zh_color"), DEFAULT_ZH_COLOR),
        normalize_hex(style.get("en_color"), DEFAULT_EN_COLOR),
    )


def _legacy_user_config_path() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home())) / "bilingual-sub" / "config.yaml"
    return Path.home() / ".config" / "bilingual-sub" / "config.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings(
    project_config: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> AppSettings:
    merged: dict[str, Any] = {}
    default_path = _bundled_config_dir() / "default.yaml"
    merged = _deep_merge(merged, _load_yaml(default_path))
    merged = _deep_merge(merged, _load_yaml(_legacy_user_config_path()))
    merged = _deep_merge(merged, _load_yaml(_user_config_path()))
    for name in ("subflow.yaml", "bilingual-sub.yaml"):
        cwd_cfg = Path.cwd() / name
        if cwd_cfg.is_file():
            merged = _deep_merge(merged, _load_yaml(cwd_cfg))
    if project_config and project_config.is_file():
        merged = _deep_merge(merged, _load_yaml(project_config))
    env_model = (os.environ.get("SUBFLOW_TRANSLATE_MODEL") or "").strip()
    if env_model:
        merged = _deep_merge(merged, {"translate": {"model": env_model}})
    if overrides:
        merged = _deep_merge(merged, overrides)
    return AppSettings.model_validate(merged)


def load_style_preset(name: str) -> StylePreset:
    path = _bundled_config_dir() / "presets" / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Style preset not found: {name}")
    data = _load_yaml(path)
    return StylePreset.model_validate(data)


def bundled_fonts_dir() -> Path:
    data = _package_root() / "_data" / "fonts"
    if data.is_dir() and any(data.iterdir()):
        return data
    repo = _repo_root() / "fonts"
    if repo.is_dir() and any(repo.iterdir()):
        return repo
    return data


def default_glossary_path() -> Path:
    return _bundled_config_dir() / "glossary.example.yaml"


def load_ui_theme() -> str:
    data = _load_yaml(_user_config_path())
    ui = data.get("ui") if isinstance(data.get("ui"), dict) else {}
    theme = str(ui.get("theme") or "dark")
    return theme if theme in {"light", "dark"} else "dark"


def save_user_overrides(overrides: dict[str, Any]) -> Path:
    path = _user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = _load_yaml(path)
    merged = _deep_merge(current, overrides)
    path.write_text(
        yaml.safe_dump(merged, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path
