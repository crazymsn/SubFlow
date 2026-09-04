"""Back-compat wrapper — tokens live in theme.py."""

from __future__ import annotations

from bilingual_sub.gui.theme import DARK, LIGHT, app_qss, tokens_for

__all__ = ["DARK", "LIGHT", "app_qss", "tokens_for"]
