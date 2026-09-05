from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import APIConnectionError, APIStatusError

from bilingual_sub.adapters import meding
from bilingual_sub.core.control import JobControl, JobStopped
from bilingual_sub.core.glossary_ai import extract_glossary
from bilingual_sub.core.translate import translate_cues
from bilingual_sub.core.translate_refine import translate_cues_refined
from bilingual_sub.models import Cue


def status_error(status, message="request failed"):
    response = httpx.Response(status, request=httpx.Request("POST", "https://example.invalid/v1"))
    return APIStatusError(message, response=response, body={"message": message})


def completion(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture
def sdk(monkeypatch):
    sdk = Mock()
    constructor = Mock(return_value=sdk)
    monkeypatch.setattr(meding, "OpenAI", constructor)
    monkeypatch.setattr(meding.time, "sleep", Mock())
    sdk.constructor = constructor
    return sdk


@pytest.mark.parametrize("status,expected,calls", [
    (401, meding.MedingAuthError, 1), (403, meding.MedingAuthError, 1),
    (404, meding.MedingServiceError, 1), (429, meding.MedingServiceError, 4),
    (503, meding.MedingServiceError, 4),
])
def test_service_failure_does_not_fan_out_per_line(sdk, status, expected, calls):
    sdk.chat.completions.create.side_effect = status_error(status)
    client = meding.OpenAIMedingClient("test")
    with pytest.raises(expected):
        translate_cues([Cue(i, i + 1, f"句子{i}") for i in range(30)],
                       client=client, cache_enabled=False)
    assert sdk.chat.completions.create.call_count == calls
    assert sdk.constructor.call_args.kwargs["max_retries"] == 0
    assert sdk.constructor.call_args.kwargs["timeout"] == 60.0


def test_connection_error_has_bounded_retries(sdk):
    sdk.chat.completions.create.side_effect = APIConnectionError(
        request=httpx.Request("POST", "https://example.invalid/v1"))
    with pytest.raises(meding.MedingServiceError):
        meding.OpenAIMedingClient("test").translate_batch(["你好"], model="m", max_en_chars=120)
    assert sdk.chat.completions.create.call_count == 4
    assert [call.args[0] for call in meding.time.sleep.call_args_list] == [1, 2, 4]


@pytest.mark.parametrize("status,message,calls", [
    (401, "invalid key", 1), (404, "model missing", 1), (400, "invalid model", 1),
    (400, "response_format unsupported", 2), (422, "json_object unsupported", 2),
])
def test_json_mode_fallback_only_for_unsupported_format(sdk, status, message, calls):
    sdk.chat.completions.create.side_effect = [status_error(status, message), completion('{"ok":true}')]
    client = meding.OpenAIMedingClient("test")
    if calls == 2:
        assert client.chat_json(model="m", system="s", user="u") == {"ok": True}
        assert "response_format" not in sdk.chat.completions.create.call_args.kwargs
    else:
        with pytest.raises(meding.MedingError):
            client.chat_json(model="m", system="s", user="u")
    assert sdk.chat.completions.create.call_count == calls


def test_cancel_backoff_prevents_next_request(sdk, monkeypatch):
    control = JobControl()
    def cancel(_seconds):
        control.stop()
        control.check()
    monkeypatch.setattr(control, "wait_seconds", cancel)
    sdk.chat.completions.create.side_effect = status_error(503)
    with pytest.raises(JobStopped):
        meding.OpenAIMedingClient("test", control=control).translate_batch(
            ["你好"], model="m", max_en_chars=120)
    assert sdk.chat.completions.create.call_count == 1


@pytest.mark.parametrize("content", ["2024. A new year", "1.5 million people"])
def test_natural_numeric_prefix_survives(sdk, content):
    sdk.chat.completions.create.return_value = completion(content)
    assert meding.OpenAIMedingClient("test").translate_batch(
        ["原文"], model="m", max_en_chars=120) == [content]


def test_numbering_supports_large_batches(sdk):
    sdk.chat.completions.create.return_value = completion("\n".join(f"{i}. line" for i in range(1, 101)))
    assert meding.OpenAIMedingClient("test").translate_batch(
        ["原文"] * 100, model="m", max_en_chars=120) == ["line"] * 100


@pytest.mark.parametrize("error", [meding.MedingAuthError, meding.MedingServiceError, JobStopped])
@pytest.mark.parametrize("stage", ["translate", "reflect", "adapt", "glossary"])
def test_refinement_and_glossary_do_not_swallow_terminal_errors(error, stage):
    client = Mock()
    client.translate_batch.return_value = ["hello"]
    client.chat_json.return_value = {"issues": []}
    if stage == "translate":
        client.translate_batch.side_effect = error("failed")
    elif stage == "adapt":
        client.chat_json.side_effect = [{"issues": []}, error("failed")]
    else:
        client.chat_json.side_effect = error("failed")
    with pytest.raises(error):
        if stage == "glossary":
            extract_glossary([Cue(0, 1, "你好")], model="m", source_lang="zh", target_lang="en", client=client)
        else:
            translate_cues_refined([Cue(0, 1, "你好")], model="m", source_lang="zh", target_lang="en", client=client)


def test_malformed_translation_response_reports_missing_without_index_error():
    client = Mock()
    client.translate_batch.return_value = []
    out, _, missing = translate_cues([Cue(0, 1, "你好")], client=client, cache_enabled=False)
    assert out[0].en is None
    assert missing == ["你好"]
    assert client.translate_batch.call_count == 2


def test_public_models_excludes_chinese_vendor_name():
    assert meding.parse_model_ids(["智源/bge", "BAAI/bge", "gpt-test"]) == ["gpt-test"]
