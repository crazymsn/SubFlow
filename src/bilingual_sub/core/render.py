from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bilingual_sub.config import StylePreset
from bilingual_sub.core.langs import (
    convert_han,
    is_pair_mode,
    pair_display_texts,
    screen_line,
    single_subtitle_lang,
)
from bilingual_sub.models import Cue

SUBTITLE_PACK = "han-layout-v3"
PAIR_ZH_CPL = 16
PAIR_EN_CPL = 42
PAIR_MAX_LINES = 1

_BREAK_AFTER = set("，。；：、？！,.!?;:）)」』】》 的了和与是")
_WIDE_EXTRA = set("，。；：、？！「」『』（）【】《》")


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


def _is_wide(ch: str) -> bool:
    code = ord(ch)
    if ch in _WIDE_EXTRA:
        return True
    return (
        0x3000 <= code <= 0x303F
        or 0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0xFF01 <= code <= 0xFF60
    )


def _advance(ch: str, fs: int, *, bold: bool = False) -> float:
    if _is_wide(ch):
        w = fs * 1.04
    elif ch.isspace():
        w = fs * 0.34
    elif ch.isalnum():
        w = fs * 0.64
    else:
        w = fs * 0.46
    if bold:
        w *= 1.06
    return w


def est_width(text: str, fs: int, *, bold: bool = False, spacing: float = 0.0) -> float:
    total = 0.0
    count = 0
    for ch in text:
        if ch in "\n\r":
            continue
        total += _advance(ch, fs, bold=bold)
        count += 1
    if count > 1:
        total += spacing * (count - 1)
    return total


def line_box_width(
    text: str,
    fs: int,
    *,
    bold: bool = False,
    spacing: float = 0.0,
    outline: float = 0.0,
) -> float:
    return est_width(text, fs, bold=bold, spacing=spacing) + 2 * outline


def _best_cut(text: str, width_fn, limit: float) -> int:
    if width_fn(text) <= limit:
        return len(text)
    lo, hi, fit = 1, len(text), 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if width_fn(text[:mid]) <= limit:
            fit = mid
            lo = mid + 1
        else:
            hi = mid - 1
    window = text[:fit]
    for index in range(len(window) - 1, max(0, len(window) - 16) - 1, -1):
        if window[index] in _BREAK_AFTER:
            return index + 1
    return max(1, fit)


def wrap_to_width(
    text: str,
    fs: int,
    max_w: float,
    *,
    bold: bool = False,
    spacing: float = 0.0,
    outline: float = 0.0,
    max_lines: int = 4,
) -> list[str]:
    raw = " ".join((text or "").replace("\n", " ").split())
    if not raw:
        return [""]
    limit = max(24.0, max_w - 2 * outline)

    def width_fn(chunk: str) -> float:
        return est_width(chunk, fs, bold=bold, spacing=spacing)

    if width_fn(raw) <= limit:
        return [raw]
    lines: list[str] = []
    rest = raw
    while rest:
        if width_fn(rest) <= limit:
            lines.append(rest)
            break
        cut = _best_cut(rest, width_fn, limit)
        if cut >= len(rest):
            lines.append(rest)
            break
        head, rest = rest[:cut].strip(), rest[cut:].strip()
        if not head:
            head, rest = rest[:1], rest[1:].strip()
        lines.append(head)
        if not rest:
            break
    kept = [line for line in lines if line] or [raw]
    cap = max(1, max_lines)
    if len(kept) <= cap:
        return kept
    leading, tail = kept[: cap - 1], kept[cap - 1 :]
    joiner = " " if any(" " in part for part in tail) else ""
    return leading + [joiner.join(tail)]


def fit_scale(
    lines: list[str],
    fs: int,
    max_w: float,
    *,
    bold: bool = False,
    spacing: float = 0.0,
    outline: float = 0.0,
) -> int:
    widest = 0.0
    for line in lines:
        widest = max(widest, line_box_width(line, fs, bold=bold, spacing=spacing, outline=outline))
    if widest <= max_w:
        return 100
    return max(1, min(100, int(max_w / widest * 100)))


def scale_tag(text: str, fs: int, max_w: float) -> str:
    lines = wrap_to_width(text, fs, max_w)
    pct = fit_scale(lines, fs, max_w)
    if pct >= 100:
        return ""
    return f"\\fscx{pct}\\fscy{pct}"


def _line_height(fs: int, scale: int) -> int:
    return max(1, int(round(fs * (scale / 100.0) * 1.2)))


def pair_measure_width(fs: int, kind: str, max_w: float) -> float:
    cpl = PAIR_ZH_CPL if kind == "zh" else PAIR_EN_CPL
    em = 1.04 if kind == "zh" else 0.64
    return max(48.0, min(max_w, fs * em * cpl))


def _block_height(lines: list[str], fs: int, scale: int) -> int:
    return max(1, len(lines)) * _line_height(fs, scale)


def fit_text(
    text: str,
    fs: int,
    max_w: float,
    *,
    bold: bool = False,
    spacing: float = 0.0,
    outline: float = 0.0,
    max_lines: int = 4,
) -> tuple[list[str], int]:
    lines = wrap_to_width(
        text, fs, max_w, bold=bold, spacing=spacing, outline=outline, max_lines=max_lines
    )
    return lines, fit_scale(lines, fs, max_w, bold=bold, spacing=spacing, outline=outline)


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
    # Type follows the tighter axis so 9:16 never inherits 16:10 font sizes.
    s = min(sx, sy)

    cn_y = int(round(int(layout.get("cn_y", 1376)) * sy))
    en_y = int(round(int(layout.get("en_y", 1472)) * sy))
    margin_lr = max(8, int(round(int(layout.get("margin_lr", 160)) * sx)))

    pad = max(24, int(round(40 * sy)), int(round(ph * 0.07)))
    margin_lr = max(margin_lr, int(round(pw * 0.07)))
    if en_y >= ph - pad:
        shift = en_y - (ph - pad)
        cn_y -= shift
        en_y -= shift
    if cn_y < pad:
        cn_y = pad
        en_y = max(en_y, cn_y + int(round(96 * sy)))

    zh_cfg["size"] = max(18, int(round(int(zh_cfg.get("size", 80)) * s)))
    en_cfg["size"] = max(14, int(round(int(en_cfg.get("size", 56)) * s)))
    zh_cfg["outline"] = round(float(zh_cfg.get("outline", 3.2)) * s, 2)
    en_cfg["outline"] = round(float(en_cfg.get("outline", 2.6)) * s, 2)
    zh_cfg["spacing"] = round(float(zh_cfg.get("spacing", 0.8)) * s, 2)
    en_cfg["spacing"] = round(float(en_cfg.get("spacing", 1.2)) * s, 2)

    outline_pad = 2.0 * max(float(zh_cfg["outline"]), float(en_cfg["outline"]))
    safe_w = max(64.0, float(pw) - 2 * margin_lr - outline_pad)
    authored = float(style.get("scale_to_fit_width", 2280)) * sx
    max_w = min(safe_w, authored) if authored > 0 else safe_w
    zh_cfg["size"] = max(18, min(int(zh_cfg["size"]), int(max_w / 12)))
    en_cfg["size"] = max(14, min(int(en_cfg["size"]), int(max_w / 28)))

    return {
        "pw": pw,
        "ph": ph,
        "cx": pw // 2,
        "cn_y": cn_y,
        "en_y": en_y,
        "margin_lr": margin_lr,
        "max_w": max_w,
        "pad": pad,
        "zh": zh_cfg,
        "en": en_cfg,
    }


def _ass_body(
    lines: list[str],
    *,
    cx: int,
    y: int,
    fs: int,
    scale: int,
    bold: bool,
    outline: float,
    color: str,
) -> str:
    shrink = f"\\fscx{scale}\\fscy{scale}" if scale < 100 else ""
    joined = r"\N".join(ass_esc(line) for line in lines)
    return (
        f"{{\\an2\\pos({cx},{y})\\q2\\b{1 if bold else 0}\\fs{fs}{shrink}"
        f"\\bord{outline}\\shad0\\c{color}}}"
        f"{joined}"
    )


def _resolve_han(mode: str, han_lang: str | None) -> str | None:
    if han_lang in {"zh", "zh-Hant"}:
        return han_lang
    lang = single_subtitle_lang(mode)
    if lang in {"zh", "zh-Hant"}:
        return lang
    if is_pair_mode(mode):
        return "zh"
    return None


def _single_line(
    cue: Cue,
    mode: str,
    han_lang: str | None = None,
    *,
    target_lang: str = "",
    source_lang: str = "",
) -> str:
    lang = single_subtitle_lang(mode)
    text = screen_line(cue, mode, target_lang=target_lang, source_lang=source_lang)
    if lang and lang not in {"zh", "zh-Hant"}:
        return text
    target = _resolve_han(mode, han_lang)
    if target in {"zh", "zh-Hant"}:
        return convert_han(text, target)
    return text


def render_ass_srt(
    cues: list[Cue],
    preset: StylePreset,
    *,
    play_res: tuple[int, int] | None = None,
    mode: str = "bilingual",
    han_lang: str | None = None,
    target_lang: str = "",
    source_lang: str = "",
) -> tuple[str, str]:
    style = preset.style
    geo = resolve_play_layout(style, play_res)
    pw, ph = geo["pw"], geo["ph"]
    cx, cn_y = geo["cx"], geo["cn_y"]
    margin_lr = geo["margin_lr"]
    max_w = geo["max_w"]
    zh_cfg = geo["zh"]
    en_cfg = geo["en"]
    pad = int(geo.get("pad") or max(24, ph // 40))
    zh_fs = int(zh_cfg.get("size", 80))
    en_fs = int(en_cfg.get("size", 56))
    zh_font = zh_cfg.get("font", "Microsoft YaHei")
    en_font = en_cfg.get("font", "Microsoft YaHei")
    zh_outline = float(zh_cfg.get("outline", 3.2))
    en_outline = float(en_cfg.get("outline", 2.6))
    zh_spacing = float(zh_cfg.get("spacing", 0.8))
    en_spacing = float(en_cfg.get("spacing", 1.2))
    zh_color = _hex_to_ass(str(zh_cfg.get("color", DEFAULT_ZH_COLOR)))
    en_color = _hex_to_ass(str(en_cfg.get("color", DEFAULT_EN_COLOR)))
    zh_bold = bool(zh_cfg.get("bold", True))
    en_bold = bool(en_cfg.get("bold", False))
    zh_bold_style = -1 if zh_bold else 0
    en_bold_style = -1 if en_bold else 0

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
Style: CN,{zh_font},{zh_fs},{zh_color},&H000000FF,&H00000000,&H00000000,{zh_bold_style},0,0,0,100,100,{zh_spacing},0,1,{zh_outline},0,2,{margin_lr},{margin_lr},0,1
Style: EN,{en_font},{en_fs},{en_color},&H000000FF,&H00000000,&H00000000,{en_bold_style},0,0,0,100,100,{en_spacing},0,1,{en_outline},0,2,{margin_lr},{margin_lr},0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events: list[str] = []
    srt_blocks: list[str] = []
    han = _resolve_han(mode, han_lang)
    gap = max(14, int(round(min(zh_fs, en_fs) * 0.42)))
    floor_y = ph - pad
    pair = is_pair_mode(mode)
    for i, cue in enumerate(cues, 1):
        if mode == "netflix_single" or single_subtitle_lang(mode):
            line = _single_line(
                cue, mode, han, target_lang=target_lang, source_lang=source_lang
            )
            lines, scale = fit_text(
                line,
                zh_fs,
                max_w,
                bold=zh_bold,
                spacing=zh_spacing,
                outline=zh_outline,
                max_lines=1,
            )
            y = min(cn_y + zh_fs // 2, floor_y)
            body = _ass_body(
                lines,
                cx=cx,
                y=y,
                fs=zh_fs,
                scale=scale,
                bold=zh_bold,
                outline=zh_outline,
                color=zh_color,
            )
            events.append(f"Dialogue: 0,{ass_time(cue.start)},{ass_time(cue.end)},CN,,0,0,0,,{body}")
            srt_blocks.append(f"{i}\n{srt_time(cue.start)} --> {srt_time(cue.end)}\n" + "\n".join(lines) + "\n")
            continue

        if pair:
            zh_text, en_text = pair_display_texts(cue)
        else:
            zh_text = cue.zh or ""
            en_text = cue.en or ""
        if han and zh_text.strip():
            zh_text = convert_han(zh_text, han)
        if not zh_text.strip() and en_text.strip():
            lines, scale = fit_text(
                en_text,
                zh_fs,
                max_w,
                bold=zh_bold,
                spacing=zh_spacing,
                outline=zh_outline,
                max_lines=PAIR_MAX_LINES if pair else 4,
            )
            y = min(cn_y + zh_fs // 2, floor_y)
            body = _ass_body(
                lines,
                cx=cx,
                y=y,
                fs=zh_fs,
                scale=scale,
                bold=zh_bold,
                outline=zh_outline,
                color=en_color,
            )
            events.append(f"Dialogue: 0,{ass_time(cue.start)},{ass_time(cue.end)},EN,,0,0,0,,{body}")
            srt_blocks.append(f"{i}\n{srt_time(cue.start)} --> {srt_time(cue.end)}\n" + "\n".join(lines) + "\n")
            continue
        show_en = bool(en_text.strip()) and en_text.strip() != zh_text.strip()
        en_first = mode == "enzh"
        if en_first and show_en:
            top_text, bot_text = en_text, zh_text
            top_fs, bot_fs = zh_fs, en_fs
            top_bold, bot_bold = zh_bold, en_bold
            top_spacing, bot_spacing = zh_spacing, en_spacing
            top_outline, bot_outline = zh_outline, en_outline
            top_color, bot_color = en_color, zh_color
            top_style, bot_style = "EN", "CN"
        else:
            top_text, bot_text = zh_text, en_text
            top_fs, bot_fs = zh_fs, en_fs
            top_bold, bot_bold = zh_bold, en_bold
            top_spacing, bot_spacing = zh_spacing, en_spacing
            top_outline, bot_outline = zh_outline, en_outline
            top_color, bot_color = zh_color, en_color
            top_style, bot_style = "CN", "EN"
        # One language, one line. Use the full safe width, then scale if it still overflows.
        top_limit = max_w
        bot_limit = max_w
        top_lines, top_scale = fit_text(
            top_text,
            top_fs,
            top_limit,
            bold=top_bold,
            spacing=top_spacing,
            outline=top_outline,
            max_lines=PAIR_MAX_LINES if pair else 4,
        )
        bot_lines, bot_scale = (
            fit_text(
                bot_text,
                bot_fs,
                bot_limit,
                bold=bot_bold,
                spacing=bot_spacing,
                outline=bot_outline,
                max_lines=PAIR_MAX_LINES if pair else 4,
            )
            if show_en
            else ([], 100)
        )
        if show_en:
            bot_h = _block_height(bot_lines, bot_fs, bot_scale)
            top_h = _block_height(top_lines, top_fs, top_scale)
            bot_bottom = floor_y
            bot_top = bot_bottom - bot_h
            top_bottom = bot_top - gap
            if top_bottom - top_h < pad:
                top_bottom = pad + top_h
                bot_bottom = min(floor_y, top_bottom + gap + bot_h)
        else:
            top_bottom = min(cn_y + top_fs // 2, floor_y)
        top_body = _ass_body(
            top_lines,
            cx=cx,
            y=top_bottom,
            fs=top_fs,
            scale=top_scale,
            bold=top_bold,
            outline=top_outline,
            color=top_color,
        )
        events.append(
            f"Dialogue: 1,{ass_time(cue.start)},{ass_time(cue.end)},{top_style},,0,0,0,,{top_body}"
        )
        if show_en:
            bot_body = _ass_body(
                bot_lines,
                cx=cx,
                y=bot_bottom,
                fs=bot_fs,
                scale=bot_scale,
                bold=bot_bold,
                outline=bot_outline,
                color=bot_color,
            )
            events.append(
                f"Dialogue: 0,{ass_time(cue.start)},{ass_time(cue.end)},{bot_style},,0,0,0,,{bot_body}"
            )
            srt_blocks.append(
                f"{i}\n{srt_time(cue.start)} --> {srt_time(cue.end)}\n"
                + "\n".join(top_lines)
                + "\n"
                + "\n".join(bot_lines)
                + "\n"
            )
        else:
            srt_blocks.append(
                f"{i}\n{srt_time(cue.start)} --> {srt_time(cue.end)}\n" + "\n".join(top_lines) + "\n"
            )

    return header + "\n".join(events) + "\n", "".join(srt_blocks)


def write_subtitles(
    cues: list[Cue],
    preset: StylePreset,
    ass_path: Path,
    srt_path: Path,
    *,
    play_res: tuple[int, int] | None = None,
    mode: str = "bilingual",
    han_lang: str | None = None,
    target_lang: str = "",
    source_lang: str = "",
) -> None:
    ass_text, srt_text = render_ass_srt(
        cues,
        preset,
        play_res=play_res,
        mode=mode,
        han_lang=han_lang,
        target_lang=target_lang,
        source_lang=source_lang,
    )
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
