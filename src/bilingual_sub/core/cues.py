from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable
from decimal import Decimal
from itertools import groupby

from bilingual_sub.core.glossary import Glossary
from bilingual_sub.models import Cue, Segment, WordSpan

_SENT_END = re.compile(r"[。！？!?；;]")
_CJK_OR_KANA = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]")
_NO_SPACE_BEFORE = set(".,!?;:)]}、。！？；：…—-~")
_NO_SPACE_AFTER = set("([{（【「『")
_CJK_BREAK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
_ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "e.g.", "i.e."}


def join_word_texts(parts: Iterable[str]) -> str:
    """Join WhisperX word tokens. Latin needs spaces; CJK does not."""
    out = ""
    for raw in parts:
        token = (raw or "").strip()
        if not token:
            continue
        if not out:
            out = token
            continue
        prev, nxt = out[-1], token[0]
        if nxt in _NO_SPACE_BEFORE or prev in _NO_SPACE_AFTER:
            out += token
        elif _CJK_OR_KANA.match(prev) or _CJK_OR_KANA.match(nxt):
            out += token
        else:
            out += " " + token
    return out


def tidy_zh(zh: str) -> str:
    zh = zh.strip("，、； ").strip()
    zh = zh.replace("decode", "Decode")
    zh = re.sub(r"(Decode)(?=就是|就是说)", r"\1 ", zh)
    zh = re.sub(r"(?<=[\u4e00-\u9fff])(?=[A-Za-z])", " ", zh)
    zh = re.sub(r"(?<=[A-Za-z])(?=[\u4e00-\u9fff])", " ", zh)
    zh = re.sub(r"(?<=[\u4e00-\u9fff])(?=\d)", " ", zh)
    zh = re.sub(r"(?<=\d)(?=[\u4e00-\u9fff])", " ", zh)
    zh = re.sub(r"\s+", " ", zh).strip()
    return zh


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").replace("decode", "Decode").lower()


def snap(
    t0: float,
    t1: float,
    silences: list[tuple[float, float]],
    *,
    tolerance: float = 0.22,
    min_duration: float = 0.90,
) -> tuple[float, float]:
    for s0, s1 in silences:
        if abs(s1 - t0) <= tolerance:
            t0 = max(t0, s1)
        if abs(s0 - t1) <= tolerance:
            t1 = min(t1, s0)
    if t1 - t0 < min_duration:
        t1 = t0 + min_duration
    return round(t0, 2), round(t1, 2)


def clauses(zh: str) -> list[str]:
    parts = [
        p.strip("，、；, ").strip()
        for p in re.split(r"(?<!\d)[，、；,](?!\d)", zh)
        if p.strip("，、；, ").strip()
    ]
    return parts or [zh]


def split_by_punct(t0: float, t1: float, zh: str) -> list[tuple[float, float, str]]:
    parts = clauses(zh)
    if len(parts) == 1 or (t1 - t0) < 1.8:
        return [(t0, t1, tidy_zh(zh))]
    if len(parts) > 2:
        parts = [parts[0], "，".join(parts[1:])]
    weights = [max(1, len(_norm(p))) for p in parts]
    total = sum(weights)
    out: list[tuple[float, float, str]] = []
    cur = t0
    i = 0
    while i < len(parts):
        p = parts[i]
        if i == len(parts) - 1:
            nxt = t1
        else:
            nxt = t0 + (t1 - t0) * (sum(weights[: i + 1]) / total)
        if nxt - cur < 0.75 and i < len(parts) - 1:
            parts[i + 1] = p + "，" + parts[i + 1]
            i += 1
            continue
        out.append((cur, nxt, tidy_zh(p)))
        cur = nxt
        i += 1
    return out or [(t0, t1, tidy_zh(zh))]


def long_internal_silence(
    t0: float,
    t1: float,
    silences: list[tuple[float, float]],
    *,
    threshold: float = 0.55,
) -> list[tuple[float, float]]:
    hits = []
    for s0, s1 in silences:
        if s0 >= t0 + 0.25 and s1 <= t1 - 0.20 and (s1 - s0) >= threshold:
            hits.append((s0, s1))
    return hits


def _has_complete_alignment(seg: Segment) -> bool:
    words = seg.words
    if not words or _norm("".join(w.text for w in words)) != _norm(seg.text):
        return False
    previous = seg.start
    previous_end = seg.start
    for word in words:
        if (not math.isfinite(word.start) or not math.isfinite(word.end)
                or word.start < previous or word.end <= word.start or word.end > seg.end
                or word.end < previous_end):
            return False
        previous = word.start
        previous_end = word.end
    return True


def _sentence_ends(text: str) -> bool:
    raw = text.rstrip().rstrip('\"\'”’)]}）】」』')
    if _SENT_END.search(raw):
        return True
    if not raw.endswith("."):
        return False
    token = raw.rsplit(None, 1)[-1] if raw else ""
    return token.lower() not in _ABBREVIATIONS and not re.fullmatch(r"(?:[A-Z]\.)+", token)


def cues_from_words(segments: list[Segment], glossary: Glossary, *,
                    max_duration: float = 8.0, gap_threshold: float = .55) -> list[Cue] | None:
    if not math.isfinite(max_duration) or max_duration <= 0:
        raise ValueError("字幕最长时长必须是有限正数")
    if not math.isfinite(gap_threshold) or gap_threshold < 0:
        raise ValueError("静音拆分阈值必须是有限非负数")
    if any(seg.text.strip() and not _has_complete_alignment(seg) for seg in segments):
        return None
    out: list[Cue] = []

    def emit(buf: list[WordSpan]) -> None:
        if buf:
            text = glossary.correct(join_word_texts(w.text for w in buf))
            if text:
                out.append(Cue(start=round(buf[0].start, 2),
                    end=max(round(buf[-1].end, 2), round(round(buf[0].start, 2) + 0.01, 2)),
                    zh=text, words=list(buf)))

    for seg in segments:
        buf: list[WordSpan] = []
        for word in seg.words:
            if buf and word.start >= buf[-1].end:
                gap = word.start - buf[-1].end
                if (_sentence_ends(buf[-1].text) or (gap > 0 and gap >= gap_threshold)
                        or word.end - buf[0].start > max_duration):
                    emit(buf)
                    buf = []
            buf.append(word)
        # ASR segment boundaries must not disappear when punctuation is absent.
        emit(buf)
    return out or None


def _long_text_cut(text: str) -> int | None:
    cuts = [m.start() for m in re.finditer(r"\s+", text) if 0 < m.start() < len(text) - 1]
    if not cuts:
        cuts = [i for i in range(1, len(text))
                if (_CJK_BREAK.match(text[i - 1]) or _CJK_BREAK.match(text[i]))
                and text[i] not in _NO_SPACE_BEFORE and text[i - 1] not in _NO_SPACE_AFTER
                and not unicodedata.combining(text[i])
                and text[i] != "\u200d" and text[i - 1] != "\u200d"
                and not "\ufe00" <= text[i] <= "\ufe0f"]
    return min(cuts, key=lambda i: abs(i - len(text) / 2)) if cuts else None


def _split_long_cue(cue: Cue, max_duration: float) -> list[Cue]:
    # Word-aligned cues were already split at real word boundaries. A single
    # long word (or inseparable overlapping group) keeps its original interval.
    if cue.words:
        return [cue]
    pending, out = [cue], []
    while pending:
        part = pending.pop()
        cut = _long_text_cut(part.zh) if part.end - part.start > max_duration else None
        if cut is not None:
            left, right = part.zh[:cut].strip(), part.zh[cut:].strip()
            weight = len("".join(left.split())) / max(1, len("".join(part.zh.split())))
            mid = round(part.start + (part.end - part.start) * weight, 2)
            if left and right and part.start < mid < part.end:
                pending.extend([Cue(mid, part.end, right), Cue(part.start, mid, left)])
                continue
        out.append(part)
    return out


def _build_segment_cues(
    segments: list[Segment],
    silences: list[tuple[float, float]],
    glossary: Glossary,
    *,
    snap_tolerance: float = 0.22,
    min_duration: float = 0.90,
    silence_split_threshold: float = 0.55,
) -> list[Cue]:
    cues: list[tuple[float, float, str]] = []
    for seg in segments:
        if not seg.text.strip():
            continue
        zh = glossary.correct(seg.text)
        t0, t1 = snap(
            seg.start, seg.end, silences, tolerance=snap_tolerance, min_duration=min_duration
        )
        pauses = long_internal_silence(t0, t1, silences, threshold=silence_split_threshold)
        parts = clauses(zh)
        if pauses and len(parts) >= 2:
            islands: list[tuple[float, float]] = []
            cur = t0
            for s0, s1 in pauses:
                if s0 - cur >= 0.40:
                    islands.append((cur, s0))
                cur = s1
            if t1 - cur >= 0.40:
                islands.append((cur, t1))
            if len(islands) >= 2:
                if len(parts) > len(islands):
                    head = parts[: len(islands) - 1]
                    tail = "，".join(parts[len(islands) - 1 :])
                    parts = head + [tail]
                elif len(parts) < len(islands):
                    islands = [(t0, t1)]
                    parts = [zh]
                for (a, b), p in zip(islands, parts):
                    cues.append((a, b, tidy_zh(p)))
                continue
        for a, b, p in split_by_punct(t0, t1, zh):
            cues.append((a, b, p))

    tmp: list[tuple[float, float, str]] = []
    for a, b, zh in cues:
        if not zh:
            continue
        if "，" in zh and (b - a) >= 1.8:
            tmp.extend(split_by_punct(a, b, zh))
        else:
            tmp.append((a, b, zh))

    out: list[Cue] = []
    for a, b, zh in tmp:
        if out and a < out[-1].end:
            a = out[-1].end
        if b <= a:
            continue
        out.append(Cue(start=round(a, 2), end=max(round(b, 2), round(round(a, 2) + 0.01, 2)), zh=zh))
    return out


def build_cues(
    segments: list[Segment],
    silences: list[tuple[float, float]],
    glossary: Glossary,
    *,
    snap_tolerance: float = 0.22,
    min_duration: float = 0.90,
    max_duration: float = 8.0,
    silence_split_threshold: float = 0.55,
    media_duration: float | None = None,
) -> list[Cue]:
    if not math.isfinite(max_duration) or max_duration <= 0:
        raise ValueError("字幕最长时长必须是有限正数")
    limit = None
    if media_duration is not None:
        if not math.isfinite(media_duration) or media_duration < 0:
            raise ValueError("媒体时长必须是有限非负数")
        # ASS timestamps have centisecond precision. Round inward so exporting
        # a fractional final frame cannot extend past the available media.
        limit = int(Decimal(str(media_duration)) * 100) / 100
        # Exclude entirely out-of-range segments before constructing subtitles.
        segments = [s for s in segments if s.start < limit and s.end > 0]
    out: list[Cue] = []
    for aligned, group in groupby(segments, key=_has_complete_alignment):
        run = list(group)
        if aligned:
            chunk = cues_from_words(run, glossary, max_duration=max_duration,
                                    gap_threshold=silence_split_threshold) or []
        else:
            chunk = _build_segment_cues(run, silences, glossary,
                snap_tolerance=snap_tolerance, min_duration=min_duration,
                silence_split_threshold=silence_split_threshold)
        if out and chunk and out[-1].start < chunk[0].start < out[-1].end:
            out[-1].end = chunk[0].start
        out.extend(chunk)
    if limit is None:
        return [part for cue in out for part in _split_long_cue(cue, max_duration)]
    bounded = []
    for cue in out:
        cue.start = max(0.0, cue.start)
        cue.end = min(cue.end, limit)
        if cue.start >= cue.end:
            continue
        if any(w.start < cue.start or w.end > cue.end for w in cue.words):
            # Keep the recognized phrase, but do not advertise word alignment
            # that extends beyond this cue's actual display interval.
            cue.words = []
        bounded.append(cue)
    return [part for cue in bounded for part in _split_long_cue(cue, max_duration)]
