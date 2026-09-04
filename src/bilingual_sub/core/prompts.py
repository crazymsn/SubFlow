"""LLM prompts rewritten for SubFlow. Inspired by VideoLingo's translate-reflect-adapt flow."""

from __future__ import annotations

PROMPT_TRANSLATE = """You translate {source_name} spoken subtitles to {target_name}.
Rules:
- One line per cue, no quotes, no numbering unless present in the source
- Spoken/casual tone, not literary
- Honor the terminology list exactly
- Do not add explanations
- Max length: {max_chars} characters
Terminology:
{glossary_block}
"""

PROMPT_REFLECT = """You review subtitle translations from {source_name} to {target_name}.
Return ONLY JSON: {{"issues":[{{"index":0,"type":"term|tone|length|omission|other","detail":"..."}}]}}
Flag terminology errors, literary tone, lines longer than {max_chars} characters, and omissions.
If everything is fine, return {{"issues":[]}}.
"""

PROMPT_ADAPT = """You rewrite subtitle translations from {source_name} to {target_name} for on-screen use.
Return ONLY JSON: {{"lines":["..."]}} with the SAME count and order as the input lines.
Apply the listed issues. Keep spoken tone. One line each. Max {max_chars} characters.
Terminology:
{glossary_block}
"""

PROMPT_GLOSSARY = """Extract domain terms from {source_name} spoken subtitles for translation into {target_name}.
Return ONLY JSON: {{"terms":[{{"term":"...","translation":"...","note":"..."}}]}}
At most 40 terms. Keep product names unchanged when they should stay in the original script.
"""

PROMPT_SPLIT = """Split this overly long {source_name} subtitle into shorter spoken lines.
Return ONLY JSON: {{"parts":["..."]}}
Do not add meaning. Keep original words. 2 to 4 parts.
"""
