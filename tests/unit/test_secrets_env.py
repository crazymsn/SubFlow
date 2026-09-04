from bilingual_sub.secrets.store import get_api_key


def test_env_api_key(monkeypatch):
    monkeypatch.setenv("SUBFLOW_API_KEY", "sk-test-env-key")
    monkeypatch.delenv("MEDING_API_KEY", raising=False)
    assert get_api_key() == "sk-test-env-key"
