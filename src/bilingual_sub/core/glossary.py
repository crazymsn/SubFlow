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
