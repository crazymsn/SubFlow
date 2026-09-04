"""Keep the user's model pick after a remote list refresh."""

from __future__ import annotations


def merge_model_list(models: list[str], current: str) -> list[str]:
    """Fetched ids first; keep a custom current value if the API omitted it."""
    seen: set[str] = set()
    out: list[str] = []
    for mid in models:
        name = mid.strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    cur = current.strip()
    if cur and cur not in seen:
        out.insert(0, cur)
    return out


def preferred_model(models: list[str], current: str) -> str:
    """Keep a typed choice; stay empty after fetch so the user picks."""
    _ = models
    return current.strip()
