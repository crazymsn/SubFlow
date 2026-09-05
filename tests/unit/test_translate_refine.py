import pytest

from bilingual_sub.adapters.meding import MedingError, TranslationCache, parse_model_json
from bilingual_sub.core.glossary import Glossary
from bilingual_sub.core.translate_refine import refine_cache_key, translate_cues_refined
from bilingual_sub.models import Cue


class FakeClient:
    def __init__(self, *, reflect_bad=False, adapt_bad=False, adapt_payload=None):
        self.calls = []
        self.reflect_bad = reflect_bad
        self.adapt_bad = adapt_bad
        self.adapt_payload = adapt_payload
        self.n_batch = 0

    def translate_batch(self, texts, **kwargs):
        self.n_batch += 1
        self.calls.append(("batch", texts, kwargs))
        return [f"EN:{t}" for t in texts]

    def chat_json(self, *, model, system, user):
        self.calls.append(("json", system[:24], user[:24]))
        if "review" in system.lower():
            if self.reflect_bad:
                raise RuntimeError("bad reflect json")
            return {"issues": []}
        if self.adapt_bad:
            raise RuntimeError("bad adapt")
        if self.adapt_payload is not None:
            return self.adapt_payload
        lines = []
        for line in user.splitlines():
            if "=>" in line:
                lines.append(line.split("=>", 1)[-1].strip() + "!")
        return {"lines": lines or ["ok"]}


class FailFirstPass:
    def translate_batch(self, texts, **kwargs):
        raise MedingError("down")

    def chat_json(self, **kwargs):
        raise AssertionError("should not polish a failed first pass")


@pytest.mark.parametrize("line", ["2024. A new year", "1.5 million people"])
def test_refine_keeps_natural_numbers(line):
    out, stats, _ = translate_cues_refined(
        [Cue(0, 1, "原文")], model="m", source_lang="zh", target_lang="en",
        client=FakeClient(adapt_payload={"lines": [line]}))
    assert out[0].en == line
    assert not stats.degraded


@pytest.mark.parametrize("line", [None, {}, 123, ""])
def test_refine_invalid_json_lines_keep_draft(line):
    out, stats, _ = translate_cues_refined(
        [Cue(0, 1, "原文")], model="m", source_lang="zh", target_lang="en",
        client=FakeClient(adapt_payload={"lines": [line]}))
    assert out[0].en == "EN:原文"
    assert stats.degraded


def test_refine_three_calls_and_adapt():
    client = FakeClient()
    cues = [Cue(0, 1, "你好"), Cue(1, 2, "世界")]
    out, stats, missing = translate_cues_refined(
        cues,
        model="m",
        source_lang="zh",
        target_lang="en",
        glossary=Glossary(),
        client=client,
    )
    assert not missing
    assert stats.api_calls >= 3
    assert stats.degraded is False
    assert [c.en for c in out] == ["EN:你好!", "EN:世界!"]


def test_refine_degrades_on_bad_json():
    client = FakeClient(reflect_bad=True, adapt_bad=True)
    cues = [Cue(0, 1, "术语")]
    out, stats, _ = translate_cues_refined(
        cues, model="m", source_lang="zh", target_lang="en", client=client
    )
    assert stats.degraded is True
    assert out[0].en.startswith("EN:")
    assert not out[0].en.endswith("!")


def test_refine_failed_batch_does_not_copy_source():
    out, stats, missing = translate_cues_refined(
        [Cue(0, 1, "术语")],
        model="m",
        source_lang="zh",
        target_lang="en",
        client=FailFirstPass(),
    )
    assert stats.degraded is True
    assert out[0].en is None
    assert missing == ["术语"]


def test_refine_accepts_numbered_and_alias_keys():
    client = FakeClient(adapt_payload={"translations": ["1. Hello!", "2. World!"]})
    out, stats, missing = translate_cues_refined(
        [Cue(0, 1, "你好"), Cue(1, 2, "世界")],
        model="m",
        source_lang="zh",
        target_lang="en",
        client=client,
    )
    assert not missing
    assert stats.degraded is False
    assert [c.en for c in out] == ["Hello!", "World!"]


def test_refine_does_not_cache_degraded_first_pass(tmp_path):
    cache = TranslationCache(tmp_path / "t.db")
    key = refine_cache_key("zh", "en", "你好")
    first = FakeClient(adapt_bad=True)
    out1, stats1, _ = translate_cues_refined(
        [Cue(0, 1, "你好")],
        model="m",
        source_lang="zh",
        target_lang="en",
        client=first,
        cache=cache,
    )
    assert stats1.degraded is True
    assert out1[0].en.startswith("EN:")
    assert cache.get("m", key) is None

    second = FakeClient()
    out2, stats2, _ = translate_cues_refined(
        [Cue(0, 1, "你好")],
        model="m",
        source_lang="zh",
        target_lang="en",
        client=second,
        cache=cache,
    )
    assert stats2.cache_hits == 0
    assert second.n_batch == 1
    assert out2[0].en == "EN:你好!"
    assert cache.get("m", key) == "EN:你好!"


def test_refine_cache_hit_skips_api(tmp_path):
    cache = TranslationCache(tmp_path / "t.db")
    cache.set("m", refine_cache_key("zh", "en", "你好"), "Hello there")
    client = FakeClient()
    out, stats, _ = translate_cues_refined(
        [Cue(0, 1, "你好")],
        model="m",
        source_lang="zh",
        target_lang="en",
        client=client,
        cache=cache,
    )
    assert out[0].en == "Hello there"
    assert stats.cache_hits == 1
    assert client.n_batch == 0
    assert client.calls == []


def test_parse_model_json_fenced_and_prose():
    assert parse_model_json('{"issues":[]}') == {"issues": []}
    assert parse_model_json('```json\n{"lines":["a"]}\n```') == {"lines": ["a"]}
    assert parse_model_json('Here you go:\n{"lines":["b"]}\nThanks') == {"lines": ["b"]}
