"""Netflix-style single-line subtitle limits (pure functions)."""

from __future__ import annotations

import math
import re
import unicodedata

from bilingual_sub.core.langs import is_cjk, lang_family, screen_line
from bilingual_sub.models import Cue, WordSpan

MAX_DURATION = 7.0
MIN_DURATION = 5 / 6
CPL = {"en": 42, "es": 42, "fr": 42, "de": 42, "ru": 42, "zh": 16, "zh-Hant": 16, "ja": 16}
CPS = {"en": 20, "es": 20, "fr": 20, "de": 20, "ru": 20, "zh": 9, "zh-Hant": 9, "ja": 9}


def cpl_limit(lang: str) -> int:
    return CPL.get(lang, 16 if is_cjk(lang) else 42)


def cps_limit(lang: str) -> float:
    return float(CPS.get(lang, 9 if is_cjk(lang) else 20))


def visible_len(text: str) -> int:
    return len((text or "").replace("\n", "").strip())


def cpl_ok(text: str, lang: str) -> bool:
    return visible_len(text) <= cpl_limit(lang)


def cps_ok(text: str, duration: float, lang: str) -> bool:
    if duration <= 0:
        return False
    return visible_len(text) / duration <= cps_limit(lang)


def needs_split(text: str, start: float, end: float, lang: str) -> bool:
    duration = end - start
    if duration > MAX_DURATION:
        return True
    if not cpl_ok(text, lang):
        return True
    # Dividing text and its available time cannot improve its reading speed.
    return False


def _compact(text: str) -> str:
    return "".join(text.split())


def _word_boundaries(text: str, words: list[WordSpan], start: float, end: float) -> dict[int, float]:
    """Use ASR times only when every displayed character is actually aligned."""
    if _compact(text) != "".join(_compact(w.text) for w in words):
        return {}
    previous = start
    for word in words:
        if (not math.isfinite(word.start) or not math.isfinite(word.end)
                or not previous <= word.start <= word.end <= end or not _compact(word.text)):
            return {}
        previous = word.end
    offset = 0
    boundaries = {}
    for left, right in zip(words, words[1:]):
        offset += len(_compact(left.text))
        boundaries[offset] = (left.end + right.start) / 2
    return boundaries


def _cut(text: str, lang: str) -> int | None:
    middle = len(text) / 2
    spaces = [m.start() for m in re.finditer(r"\s+", text)]
    if spaces and not is_cjk(lang):
        return min(spaces, key=lambda i: abs(i - middle))
    if not is_cjk(lang) and cpl_ok(text, lang):
        return None  # Do not break a short word just to fill a long interval.
    # Keep combining marks and joined emoji attached to their base character.
    cuts = [i for i in range(1, len(text))
            if not unicodedata.combining(text[i]) and text[i] != "\u200d"
            and text[i - 1] != "\u200d" and not "\ufe00" <= text[i] <= "\ufe0f"
            and not "\U0001f3fb" <= text[i] <= "\U0001f3ff"]
    return min(cuts, key=lambda i: abs(i - middle)) if cuts else None


def split_text(
    text: str,
    start: float,
    end: float,
    lang: str,
    words: list[WordSpan] | None = None,
) -> list[Cue]:
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise ValueError("字幕时间必须有限、非负且结束晚于开始")
    raw = " ".join((text or "").split())
    boundaries = _word_boundaries(raw, words or [], start, end)
    # Splitting is iterative: every leaf must fit, unless its text or time can
    # no longer be divided. Original endpoints are never clipped or extended.
    pending = [(raw, start, end, 0, True)]
    out: list[Cue] = []
    while pending:
        part, a, b, offset, force = pending.pop()
        cut = _cut(part, lang) if force or needs_split(part, a, b, lang) else None
        lo, hi = round(a * 100) + 1, round(b * 100) - 1
        if cut is not None and lo <= hi:
            left, right = part[:cut].strip(), part[cut:].strip()
            count = len(_compact(left))
            ratio = count / max(1, len(_compact(part)))
            mid = boundaries.get(offset + count, a + (b - a) * ratio)
            mid = max(lo, min(hi, round(mid * 100))) / 100
            if left and right and a < mid < b:
                pending.append((right, mid, b, offset + count, False))
                pending.append((left, a, mid, offset, False))
                continue
        out.append(Cue(start=a, end=b, zh=part, en=part))
    return out


def fit_cues(cues: list[Cue], lang: str, *, use_target: bool = True) -> list[Cue]:
    fitted: list[Cue] = []
    for cue in cues:
        if use_target:
            text = screen_line(cue, f"single:{lang}")
        else:
            text = cue.source or cue.target or ""
        text = " ".join(text.split())
        parts = (split_text(text, cue.start, cue.end, lang, cue.words)
                 if needs_split(text, cue.start, cue.end, lang)
                 else [Cue(cue.start, cue.end, text)])
        for part in parts:
            # Fitted cues are a display projection. Keep full bilingual cues
            # separately for dubbing; repeating their other slots here can make
            # language heuristics render the unsplit sentence on every frame.
            fitted.append(Cue(part.start, part.end, part.zh, language_texts={lang_family(lang): part.zh}))
    return fitted


def fit_warnings(cues: list[Cue], lang: str) -> list[dict]:
    """Report unsatisfied app limits without inventing additional screen time."""
    warnings = []
    for i, cue in enumerate(cues, 1):
        text = screen_line(cue, f"single:{lang}")
        duration = cue.end - cue.start
        issues = []
        if not cpl_ok(text, lang):
            issues.append("characters_per_line")
        if not cps_ok(text, duration, lang):
            issues.append("characters_per_second")
        if duration < MIN_DURATION:
            issues.append("minimum_duration")
        if duration > MAX_DURATION:
            issues.append("maximum_duration")
        if issues:
            warnings.append({"cue": i, "issues": issues})
    return warnings
