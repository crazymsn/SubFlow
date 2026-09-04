from bilingual_sub.models import Cue, WordSpan


def test_old_zh_en_roundtrip():
    cue = Cue.from_dict({"start": 1.0, "end": 2.5, "zh": "你好", "en": "Hello"})
    assert cue.zh == "你好"
    assert cue.en == "Hello"
    assert cue.source == "你好"
    assert cue.target == "Hello"
    data = cue.to_dict()
    assert data["zh"] == "你好"
    assert data["en"] == "Hello"
    assert data["source"] == "你好"
    assert data["target"] == "Hello"
    again = Cue.from_dict(data)
    assert again.zh == "你好"
    assert again.en == "Hello"


def test_new_source_target_and_words():
    cue = Cue.from_dict(
        {
            "start": 0.1,
            "end": 1.2,
            "source": "Prefill",
            "target": "预填充",
            "words": [{"start": 0.1, "end": 0.5, "text": "Pre"}, {"start": 0.5, "end": 1.2, "text": "fill"}],
        }
    )
    assert cue.zh == "Prefill"
    assert cue.en == "预填充"
    assert len(cue.words) == 2
    assert isinstance(cue.words[0], WordSpan)
    assert cue.words[0].text == "Pre"


def test_source_alias_writes_zh():
    cue = Cue(start=0, end=1, zh="甲")
    cue.source = "乙"
    cue.target = "Yi"
    assert cue.zh == "乙"
    assert cue.en == "Yi"
