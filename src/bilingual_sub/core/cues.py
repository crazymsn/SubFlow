from __future__ import annotations

import re

from bilingual_sub.core.glossary import Glossary
from bilingual_sub.models import Cue, Segment


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


def build_cues(
    segments: list[Segment],
    silences: list[tuple[float, float]],
    glossary: Glossary,
    *,
    snap_tolerance: float = 0.22,
    min_duration: float = 0.90,
    max_duration: float = 8.0,
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
        if not zh or zh == "然后去":
            continue
        if "，" in zh and (b - a) >= 1.8:
            tmp.extend(split_by_punct(a, b, zh))
        else:
            tmp.append((a, b, zh))

    out: list[Cue] = []
    for a, b, zh in tmp:
        if out and a < out[-1].end + 0.03:
            a = out[-1].end + 0.04
            if b <= a:
                b = a + 0.7
        b = min(b, a + max_duration)
        out.append(Cue(start=round(a, 2), end=round(b, 2), zh=zh))
    return out
