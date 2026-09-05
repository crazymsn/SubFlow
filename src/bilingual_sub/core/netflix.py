"""Netflix-style single-line subtitle limits (pure functions)."""

from __future__ import annotations

from bilingual_sub.core.langs import is_cjk
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
    if duration >= MIN_DURATION and not cps_ok(text, duration, lang):
        return True
    return False


def _split_plain(text: str, start: float, end: float) -> list[tuple[str, float, float]]:
    raw = (text or "").strip()
    if not raw:
        return [(raw, start, end)]
    mid = max(1, len(raw) // 2)
    cut = raw.rfind(" ", 0, mid + 8)
    if cut < 1:
        cut = raw.find(" ", mid)
    if cut < 1:
        cut = mid
    left, right = raw[:cut].strip(), raw[cut:].strip()
    if not right:
        return [(left, start, end)]
    ratio = max(0.2, min(0.8, len(left) / max(1, len(raw))))
    mid_t = start + (end - start) * ratio
    return [(left, start, mid_t), (right, mid_t, end)]


def _split_words(words: list[WordSpan], start: float, end: float) -> list[tuple[str, float, float]]:
    if len(words) < 2:
        return _split_plain("".join(w.text for w in words), start, end)
    mid = len(words) // 2
    left, right = words[:mid], words[mid:]
    return [
        (" ".join(w.text for w in left).strip(), left[0].start, left[-1].end),
        (" ".join(w.text for w in right).strip(), right[0].start, right[-1].end),
    ]


def split_text(
    text: str,
    start: float,
    end: float,
    lang: str,
    words: list[WordSpan] | None = None,
) -> list[Cue]:
    pieces = _split_words(words, start, end) if words else _split_plain(text, start, end)
    out: list[Cue] = []
    for part, a, b in pieces:
        if b - a < MIN_DURATION:
            b = a + MIN_DURATION
        if b - a > MAX_DURATION:
            b = a + MAX_DURATION
        cue = Cue(start=round(a, 2), end=round(b, 2), zh=part, en=part)
        out.append(cue)
    if len(out) == 1 and needs_split(out[0].target or "", out[0].start, out[0].end, lang):
        again = _split_plain(out[0].target or "", out[0].start, out[0].end)
        if len(again) > 1:
            return [
                Cue(start=round(a, 2), end=round(b, 2), zh=part, en=part) for part, a, b in again
            ]
    return out


def fit_cues(cues: list[Cue], lang: str, *, use_target: bool = True) -> list[Cue]:
    fitted: list[Cue] = []
    for cue in cues:
        text = (cue.target if use_target else cue.source) or ""
        words = cue.words
        if not needs_split(text, cue.start, cue.end, lang):
            fitted.append(cue)
            continue
        parts = split_text(text, cue.start, cue.end, lang, words)
        for part in parts:
            if use_target:
                part.zh = cue.zh
                part.en = part.en
            fitted.append(part)
    return fitted
