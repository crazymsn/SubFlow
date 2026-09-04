from __future__ import annotations

import re
from pathlib import Path

import yaml


class Glossary:
    def __init__(
        self,
        replacements: list[tuple[str, str]] | None = None,
        regex_rules: list[tuple[str, str]] | None = None,
        punctuation: dict[str, str] | None = None,
    ) -> None:
        self.replacements = replacements or []
        self.regex_rules = regex_rules or []
        self.punctuation = punctuation or {}

    @classmethod
    def load(cls, path: Path | None) -> Glossary:
        if path is None or not path.is_file():
            return cls()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        reps = [(r["from"], r["to"]) for r in data.get("replacements") or []]
        regex = [(r["pattern"], r["replace"]) for r in data.get("regex") or []]
        punct = dict(data.get("punctuation") or {})
        return cls(replacements=reps, regex_rules=regex, punctuation=punct)

    def correct(self, zh: str) -> str:
        for pattern, repl in self.regex_rules:
            zh = re.sub(pattern, repl, zh)
        for src, dst in self.punctuation.items():
            zh = zh.replace(src, dst)
        for a, b in self.replacements:
            zh = zh.replace(a, b)
        zh = re.sub(r"\s+", " ", zh).strip()
        zh = zh.replace(" ，", "，").replace("， ", "，")
        return zh

    def apply_to_text(self, text: str) -> str:
        return self.correct(text)

    def block(self) -> str:
        lines = [f"{a} => {b}" for a, b in self.replacements]
        return "\n".join(lines)

    def to_yaml(self) -> str:
        data = {
            "replacements": [{"from": a, "to": b} for a, b in self.replacements],
            "regex": [{"pattern": p, "replace": r} for p, r in self.regex_rules],
            "punctuation": dict(self.punctuation),
        }
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)

    def save(self, path: Path) -> None:
        path.write_text(self.to_yaml(), encoding="utf-8")

    @classmethod
    def from_terms(cls, terms: list[dict]) -> Glossary:
        reps: list[tuple[str, str]] = []
        for item in terms:
            src = str(item.get("term") or item.get("from") or "").strip()
            dst = str(item.get("translation") or item.get("to") or src).strip()
            if src:
                reps.append((src, dst))
        return cls(replacements=reps)

    @classmethod
    def merge(cls, *glossaries: Glossary) -> Glossary:
        """Later arguments override earlier ones. Call as merge(bundled, generated, user)."""
        seen: dict[str, str] = {}
        regex: list[tuple[str, str]] = []
        punct: dict[str, str] = {}
        for g in glossaries:
            for a, b in g.replacements:
                seen[a] = b
            regex.extend(g.regex_rules)
            punct.update(g.punctuation)
        return cls(replacements=list(seen.items()), regex_rules=regex, punctuation=punct)
