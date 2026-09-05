from unittest.mock import Mock

from bilingual_sub.adapters.meding import TranslationCache
from bilingual_sub.core.glossary import Glossary
from bilingual_sub.core.translate import translate_cues
from bilingual_sub.core.translate_refine import translate_cues_refined
from bilingual_sub.models import Cue


def test_plain_cache_changes_with_character_limit_and_glossary(tmp_path, monkeypatch):
    cache = TranslationCache(tmp_path / "nested" / "translations.db")
    monkeypatch.setattr("bilingual_sub.core.translate.TranslationCache", lambda: cache)
    client = Mock()
    client.translate_batch.side_effect = [["short"], ["long translation"], ["new term"]]
    results = []
    for limit, glossary in [(5, ""), (120, ""), (120, "term => new term"), (120, "term => new term")]:
        out, stats, _ = translate_cues([Cue(0, 1, "术语")], client=client,
                                       max_en_chars=limit, glossary_block=glossary)
        results.append(out[0].en)
    assert results == ["short", "long translation", "new term", "new term"]
    assert stats.cache_hits == 1
    assert client.translate_batch.call_count == 3


def test_refined_cache_changes_with_glossary(tmp_path):
    cache = TranslationCache(tmp_path / "translations.db")
    client = Mock()
    client.translate_batch.return_value = ["draft"]
    client.chat_json.side_effect = [{"issues": []}, {"lines": ["old term"]},
                                    {"issues": []}, {"lines": ["new term"]}]
    results = []
    for term in ["old term", "new term", "new term"]:
        out, stats, _ = translate_cues_refined(
            [Cue(0, 1, "术语")], model="m", source_lang="zh", target_lang="en", client=client,
            cache=cache, glossary=Glossary(replacements=[("术语", term)]))
        results.append(out[0].en)
    assert results == ["old term", "new term", "new term"]
    assert stats.cache_hits == 1
    assert client.translate_batch.call_count == 2
