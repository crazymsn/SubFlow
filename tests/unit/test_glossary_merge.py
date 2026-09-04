from bilingual_sub.core.glossary import Glossary


def test_merge_later_overrides():
    bundled = Glossary(replacements=[("a", "A"), ("b", "B")])
    generated = Glossary.from_terms([{"term": "b", "translation": "Bee"}, {"term": "c", "translation": "Cee"}])
    user = Glossary(replacements=[("c", "C-user")])
    merged = Glossary.merge(bundled, generated, user)
    mapping = dict(merged.replacements)
    assert mapping["a"] == "A"
    assert mapping["b"] == "Bee"
    assert mapping["c"] == "C-user"


def test_block_and_from_terms():
    g = Glossary.from_terms([{"term": "Prefill", "translation": "预填充", "note": "x"}])
    assert "Prefill => 预填充" in g.block()
    assert g.apply_to_text("use Prefill now") == "use 预填充 now"
