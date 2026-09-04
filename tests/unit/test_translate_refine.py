from bilingual_sub.core.glossary import Glossary
from bilingual_sub.core.translate_refine import translate_cues_refined
from bilingual_sub.models import Cue


class FakeClient:
    def __init__(self, *, reflect_bad=False, adapt_bad=False, batch_fail_first=False):
        self.calls = []
        self.reflect_bad = reflect_bad
        self.adapt_bad = adapt_bad
        self.batch_fail_first = batch_fail_first
        self.n_batch = 0

    def translate_batch(self, texts, **kwargs):
        self.n_batch += 1
        self.calls.append(("batch", texts, kwargs))
        return [f"EN:{t}" for t in texts]

    def chat_json(self, *, model, system, user):
        self.calls.append(("json", system[:24], user[:24]))
        if "issues" in system.lower() or "review" in system.lower():
            if self.reflect_bad:
                raise RuntimeError("bad reflect json")
            return {"issues": []}
        if self.adapt_bad:
            raise RuntimeError("bad adapt")
        lines = []
        for line in user.splitlines():
            if "=>" in line:
                lines.append(line.split("=>", 1)[-1].strip() + "!")
        return {"lines": lines or ["ok"]}


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
    assert all(c.en for c in out)


def test_refine_degrades_on_bad_json():
    client = FakeClient(reflect_bad=True, adapt_bad=True)
    cues = [Cue(0, 1, "术语")]
    out, stats, _ = translate_cues_refined(
        cues, model="m", source_lang="zh", target_lang="en", client=client
    )
    assert stats.degraded is True
    assert out[0].en.startswith("EN:")
