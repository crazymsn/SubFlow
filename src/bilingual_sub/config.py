from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from filelock import FileLock, Timeout
from pydantic import BaseModel, Field

from bilingual_sub.core.file_io import write_text_files


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


def load_gptsovits_settings() -> dict[str, str]:
    data = _load_yaml(_user_config_path())
    block = _mapping(data.get("tts"))
    sovits = _mapping(block.get("gptsovits"))
    # Older GUI tests could persist this fixed temporary fixture in a real profile.
    # Ignore only that known missing/corrupt fixture, never a user's custom reference.
    if obsolete_test_reference(str(sovits.get("ref_audio") or "")):
        sovits = {**sovits, "ref_audio": "", "prompt_text": "", "prompt_lang": ""}
    endpoint = str(sovits.get("endpoint") or os.environ.get("SUBFLOW_GPTSOVITS_URL") or "").strip()
    return {
        "endpoint": endpoint,
        "ref_audio": str(sovits.get("ref_audio") or os.environ.get("SUBFLOW_GPTSOVITS_REF") or "").strip(),
        "prompt_text": str(sovits.get("prompt_text") or os.environ.get("SUBFLOW_GPTSOVITS_PROMPT") or ""),
        "prompt_lang": str(sovits.get("prompt_lang") or os.environ.get("SUBFLOW_GPTSOVITS_PROMPT_LANG") or "").strip(),
    }


def obsolete_test_reference(value: str) -> bool:
    if not value.strip():
        return False
    try:
        path = Path(value).expanduser()
        if path.resolve() != (Path(tempfile.gettempdir()) / "subflow-sovits-ref.wav").resolve():
            return False
        if not path.exists():
            return True
        return path.is_file() and path.stat().st_size == 16 and path.read_bytes() == b"RIFF....WAVE...."
    except OSError:
        return False


def save_gptsovits_settings(
    *,
    endpoint: str = "",
    ref_audio: str = "",
    prompt_text: str = "",
    prompt_lang: str = "",
) -> Path:
    return save_user_overrides(
        {
            "tts": {
                "gptsovits": {
                    "endpoint": endpoint,
                    "ref_audio": ref_audio,
                    "prompt_text": prompt_text,
                    "prompt_lang": prompt_lang,
                }
            }
        }
    )


def load_subtitle_colors() -> tuple[str, str]:
    from bilingual_sub.core.render import DEFAULT_EN_COLOR, DEFAULT_ZH_COLOR, normalize_hex

    data = _load_yaml(_user_config_path())
    style = _mapping(data.get("style"))
    return (
        normalize_hex(style.get("zh_color"), DEFAULT_ZH_COLOR),
        normalize_hex(style.get("en_color"), DEFAULT_EN_COLOR),
    )


def _legacy_user_config_path() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home())) / "bilingual-sub" / "config.yaml"
    return Path.home() / ".config" / "bilingual-sub" / "config.yaml"


def _load_yaml(path: Path, *, require_mapping: bool = False) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    if isinstance(data, dict):
        return data
    if require_mapping:
        raise ValueError(f"配置文件顶层必须是键值映射，原文件未修改：{path}")
    return {}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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
    ui = _mapping(data.get("ui"))
    theme = str(ui.get("theme") or "dark")
    return theme if theme in {"light", "dark"} else "dark"


def save_user_overrides(overrides: dict[str, Any]) -> Path:
    path = _user_config_path()
    # Follow a user-managed symlink, retaining the link itself when publishing.
    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Lock the complete read/merge/write operation across app processes.
        # Keep the lock file: unlinking it can split ownership between writers.
        with FileLock(str(destination) + ".lock", timeout=5):
            current = _load_yaml(destination, require_mapping=True)
            merged = _deep_merge(current, overrides)
            text = yaml.safe_dump(merged, allow_unicode=True, sort_keys=False)
            write_text_files([(destination, text, "utf-8")])
    except Timeout as exc:
        raise RuntimeError("配置正在被其他窗口保存，请稍后重试") from exc
    return path
