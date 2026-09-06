from pathlib import Path

import pytest

from bilingual_sub import config


@pytest.mark.parametrize("content", [None, b"RIFF....WAVE...."])
def test_known_stale_test_reference_returns_to_automatic_mode(tmp_path, monkeypatch, content):
    monkeypatch.setattr(config.tempfile, "gettempdir", lambda: str(tmp_path))
    reference = tmp_path / "subflow-sovits-ref.wav"
    if content:
        reference.write_bytes(content)
    config.save_gptsovits_settings(endpoint="http://localhost:19880", ref_audio=str(reference),
                                  prompt_text="test prompt", prompt_lang="en")
    settings = config.load_gptsovits_settings()
    assert settings == {"endpoint": "http://localhost:19880", "ref_audio": "", "prompt_text": "", "prompt_lang": ""}


def test_user_reference_and_valid_audio_are_not_silently_replaced(tmp_path, monkeypatch, pcm_wav):
    monkeypatch.setattr(config.tempfile, "gettempdir", lambda: str(tmp_path))
    paths = [tmp_path / "user.wav", tmp_path / "elsewhere/subflow-sovits-ref.wav"]
    for path in paths:
        config.save_gptsovits_settings(ref_audio=str(path), prompt_text="actual text")
        assert config.load_gptsovits_settings()["ref_audio"] == str(path)
    valid = tmp_path / "subflow-sovits-ref.wav"
    valid.write_bytes(pcm_wav(4))
    assert not config.obsolete_test_reference(str(valid))


def test_gui_and_credentials_persist_only_in_test_profile(tmp_path):
    from bilingual_sub.secrets.store import get_api_key, set_api_key

    assert config.user_config_dir().is_relative_to(tmp_path)
    assert Path.home().is_relative_to(tmp_path)
    config.save_gptsovits_settings(ref_audio=str(tmp_path / "test-only.wav"))
    set_api_key("test-only-token")
    assert get_api_key() == "test-only-token"


def test_frozen_self_test_does_not_change_callers_settings_or_credentials(tmp_path, monkeypatch):
    from bilingual_sub.gui import self_test
    from bilingual_sub.secrets.store import get_api_key, set_api_key

    original = config.save_user_overrides({"ui": {"theme": "dark"}})
    before = original.read_bytes()
    set_api_key("outer-test-token")
    def exercise(report, profile):
        assert config.user_config_dir().is_relative_to(profile)
        assert get_api_key() is None
        config.save_gptsovits_settings(ref_audio="temporary-smoke-reference.wav")
        set_api_key("inner-test-token")
        report.write_text("{}")
    monkeypatch.setattr(self_test, "_run", exercise)
    self_test.run(tmp_path / "report.json")
    assert original.read_bytes() == before
    assert get_api_key() == "outer-test-token"
