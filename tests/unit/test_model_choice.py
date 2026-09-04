from bilingual_sub.gui.model_choice import merge_model_list, preferred_model


def test_keeps_saved_model_when_in_list():
    assert preferred_model(["gpt-4o-mini", "deepseek-v3"], "deepseek-v3") == "deepseek-v3"


def test_keeps_typed_model_when_not_in_list():
    assert preferred_model(["gpt-4o-mini"], "my-custom") == "my-custom"


def test_stays_empty_when_user_has_not_chosen():
    assert preferred_model(["gpt-4o-mini", "deepseek-v3"], "") == ""
    assert preferred_model([], "") == ""


def test_merge_prepends_unknown_current():
    assert merge_model_list(["a", "b"], "custom") == ["custom", "a", "b"]
    assert merge_model_list(["a", "b"], "b") == ["a", "b"]
    assert merge_model_list(["a", "a", ""], "  ") == ["a"]
