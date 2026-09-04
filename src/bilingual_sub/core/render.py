from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bilingual_sub.config import StylePreset
from bilingual_sub.models import Cue


def ass_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def srt_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def ass_esc(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


DEFAULT_ZH_COLOR = "#FFFFFF"
DEFAULT_EN_COLOR = "#F2F2F2"


def normalize_hex(value: object, default: str = DEFAULT_ZH_COLOR) -> str:
    raw = str(value or "").strip()
    if raw.lower().startswith("0x"):
        raw = raw[2:]
    raw = raw.lstrip("#")
    if len(raw) == 3 and all(char in "0123456789abcdefABCDEF" for char in raw):
        raw = "".join(char * 2 for char in raw)
    if len(raw) == 6 and all(char in "0123456789abcdefABCDEF" for char in raw):
        return f"#{raw.upper()}"
    return default


def apply_subtitle_colors(preset: StylePreset, zh: str | None, en: str | None) -> StylePreset:
    style = dict(preset.style)
    zh_cfg = dict(style.get("zh") or {})
    en_cfg = dict(style.get("en") or {})
    if zh:
        zh_cfg["color"] = normalize_hex(zh, str(zh_cfg.get("color") or DEFAULT_ZH_COLOR))
    if en:
        en_cfg["color"] = normalize_hex(en, str(en_cfg.get("color") or DEFAULT_EN_COLOR))
    style["zh"] = zh_cfg
    style["en"] = en_cfg
    return preset.model_copy(update={"style": style})


def _hex_to_ass(color: str) -> str:
    c = normalize_hex(color).lstrip("#")
    if len(c) == 6:
        r, g, b = c[0:2], c[2:4], c[4:6]
        return f"&H00{b.upper()}{g.upper()}{r.upper()}"
    return "&H00FFFFFF"


def est_width(text: str, fs: int) -> float:
    w = 0.0
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" or ch in "，。；：、？！":
            w += fs
        elif ch.isalnum():
            w += fs * 0.56
        else:
            w += fs * 0.38
    return w


def scale_tag(text: str, fs: int, max_w: float) -> str:
    w = est_width(text, fs)
    if w <= max_w:
        return ""
    pct = max(82, min(100, int(max_w / w * 100)))
    return f"\\fscx{pct}"


REF_W = 2560
REF_H = 1600


def resolve_play_layout(
    style: dict[str, Any],
    play_res: tuple[int, int] | None,
) -> dict[str, Any]:
    """Scale preset (authored for 2560x1600) to the actual video frame."""
    if play_res:
        pw, ph = play_res
    else:
        pr = style.get("play_res")
        if pr == "auto" or pr is None:
            pw, ph = REF_W, REF_H
        else:
            pw, ph = int(pr[0]), int(pr[1])

    layout: dict[str, Any] = style.get("layout") or {}
    zh_cfg: dict[str, Any] = dict(style.get("zh") or {})
    en_cfg: dict[str, Any] = dict(style.get("en") or {})
    sy = ph / REF_H
    sx = pw / REF_W

    cn_y = int(round(int(layout.get("cn_y", 1376)) * sy))
    en_y = int(round(int(layout.get("en_y", 1472)) * sy))
    margin_lr = max(8, int(round(int(layout.get("margin_lr", 160)) * sx)))
    max_w = float(style.get("scale_to_fit_width", 2280)) * sx

    pad = max(24, int(round(40 * sy)))
    if en_y >= ph - pad:
        shift = en_y - (ph - pad)
        cn_y -= shift
        en_y -= shift
    if cn_y < pad:
        cn_y = pad
        en_y = max(en_y, cn_y + int(round(96 * sy)))

    zh_cfg["size"] = max(18, int(round(int(zh_cfg.get("size", 80)) * sy)))
    en_cfg["size"] = max(14, int(round(int(en_cfg.get("size", 56)) * sy)))
    zh_cfg["outline"] = round(float(zh_cfg.get("outline", 3.2)) * sy, 2)
    en_cfg["outline"] = round(float(en_cfg.get("outline", 2.6)) * sy, 2)

    return {
        "pw": pw,
        "ph": ph,
        "cx": pw // 2,
        "cn_y": cn_y,
        "en_y": en_y,
        "margin_lr": margin_lr,
        "max_w": max_w,
        "zh": zh_cfg,
        "en": en_cfg,
    }


def render_ass_srt(
    cues: list[Cue],
    preset: StylePreset,
    *,
    play_res: tuple[int, int] | None = None,
    mode: str = "bilingual",
) -> tuple[str, str]:
    style = preset.style
    geo = resolve_play_layout(style, play_res)
    pw, ph = geo["pw"], geo["ph"]
    cx, cn_y, en_y = geo["cx"], geo["cn_y"], geo["en_y"]
    margin_lr = geo["margin_lr"]
    max_w = geo["max_w"]
    zh_cfg = geo["zh"]
    en_cfg = geo["en"]
    zh_fs = int(zh_cfg.get("size", 80))
    en_fs = int(en_cfg.get("size", 56))
    zh_font = zh_cfg.get("font", "Microsoft YaHei")
    en_font = en_cfg.get("font", "Microsoft YaHei")
    zh_outline = float(zh_cfg.get("outline", 3.2))
    en_outline = float(en_cfg.get("outline", 2.6))
    zh_color = _hex_to_ass(str(zh_cfg.get("color", DEFAULT_ZH_COLOR)))
    en_color = _hex_to_ass(str(en_cfg.get("color", DEFAULT_EN_COLOR)))
    zh_bold = -1 if zh_cfg.get("bold", True) else 0
    en_bold = -1 if en_cfg.get("bold", False) else 0

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {pw}
PlayResY: {ph}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
Title: bilingual-sub

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CN,{zh_font},{zh_fs},{zh_color},&H000000FF,&H00000000,&H00000000,{zh_bold},0,0,0,100,100,{float(zh_cfg.get("spacing", 0.8))},0,1,{zh_outline},0,5,{margin_lr},{margin_lr},0,1
Style: EN,{en_font},{en_fs},{en_color},&H000000FF,&H00000000,&H00000000,{en_bold},0,0,0,100,100,{float(en_cfg.get("spacing", 1.2))},0,1,{en_outline},0,5,{margin_lr},{margin_lr},0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    cn_pos = rf"\an5\pos({cx},{cn_y})"
    en_pos = rf"\an5\pos({cx},{en_y})"

    events: list[str] = []
    srt_blocks: list[str] = []
    for i, cue in enumerate(cues, 1):
        en = cue.en or ""
        zh_tag = scale_tag(cue.zh, zh_fs, max_w)
        en_tag = scale_tag(en, en_fs, max_w)
        zh_line = (
            f"{{{cn_pos}\\b1\\fs{zh_fs}{zh_tag}\\bord{zh_outline}\\shad0\\c{zh_color}}}"
            f"{ass_esc(cue.zh)}"
        )
        en_line = (
            f"{{{en_pos}\\b0\\fs{en_fs}{en_tag}\\bord{en_outline}\\shad0\\c{en_color}}}"
            f"{ass_esc(en)}"
        )
        if mode == "netflix_single":
            line = (cue.en or cue.zh or "").strip()
            tag = scale_tag(line, zh_fs, max_w)
            body = (
                f"{{{cn_pos}\\b1\\fs{zh_fs}{tag}\\bord{zh_outline}\\shad0\\c{zh_color}}}"
                f"{ass_esc(line)}"
            )
            events.append(f"Dialogue: 0,{ass_time(cue.start)},{ass_time(cue.end)},CN,,0,0,0,,{body}")
            srt_blocks.append(f"{i}\n{srt_time(cue.start)} --> {srt_time(cue.end)}\n{line}\n")
            continue
        events.append(f"Dialogue: 1,{ass_time(cue.start)},{ass_time(cue.end)},CN,,0,0,0,,{zh_line}")
        events.append(f"Dialogue: 0,{ass_time(cue.start)},{ass_time(cue.end)},EN,,0,0,0,,{en_line}")
        srt_blocks.append(f"{i}\n{srt_time(cue.start)} --> {srt_time(cue.end)}\n{cue.zh}\n{en}\n")

    return header + "\n".join(events) + "\n", "".join(srt_blocks)


def write_subtitles(
    cues: list[Cue],
    preset: StylePreset,
    ass_path: Path,
    srt_path: Path,
    *,
    play_res: tuple[int, int] | None = None,
    mode: str = "bilingual",
) -> None:
    ass_text, srt_text = render_ass_srt(cues, preset, play_res=play_res, mode=mode)
    ass_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path.write_text(ass_text, encoding="utf-8-sig")
    srt_path.write_text(srt_text, encoding="utf-8")


def save_cues_json(cues: list[Cue], path: Path) -> None:
    path.write_text(
        json.dumps([c.to_dict() for c in cues], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_cues_json(path: Path) -> list[Cue]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Cue.from_dict(d) for d in data]
