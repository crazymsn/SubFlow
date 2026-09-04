from bilingual_sub.adapters.meding import parse_model_ids


def test_parse_openai_objects():
    class M:
        def __init__(self, i: str) -> None:
            self.id = i

    class R:
        data = [M("gpt-4o-mini"), M("deepseek-v3"), M("gpt-4o-mini")]

    assert parse_model_ids(R()) == ["gpt-4o-mini", "deepseek-v3"]


def test_parse_dict_and_list():
    assert parse_model_ids({"data": [{"id": "a"}, {"name": "b"}]}) == ["a", "b"]
    assert parse_model_ids(["x", "y", "x"]) == ["x", "y"]
    assert parse_model_ids(None) == []
