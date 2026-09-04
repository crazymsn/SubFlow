import json
import sys
from pathlib import Path

from bilingual_sub.secrets import store
from bilingual_sub.secrets.store import delete_api_key, get_api_key, set_api_key


def test_env_api_key(monkeypatch):
    monkeypatch.setenv("SUBFLOW_API_KEY", "sk-test-env-key")
    monkeypatch.delenv("MEDING_API_KEY", raising=False)
    assert get_api_key() == "sk-test-env-key"


class _NoKeyring:
    def set_password(self, *args, **kwargs):
        raise RuntimeError("no keyring")

    def get_password(self, *args, **kwargs):
        raise RuntimeError("no keyring")

    def delete_password(self, *args, **kwargs):
        raise RuntimeError("no keyring")


def test_api_keys_are_isolated_per_os_user(tmp_path, monkeypatch):
    monkeypatch.delenv("SUBFLOW_API_KEY", raising=False)
    monkeypatch.delenv("MEDING_API_KEY", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setitem(sys.modules, "keyring", _NoKeyring())

    monkeypatch.setenv("USERNAME", "alice")
    set_api_key("sk-alice-secret")
    alice_file = tmp_path / "SubFlow" / "users" / "alice" / "credentials.json"
    assert alice_file.is_file()
    assert json.loads(alice_file.read_text(encoding="utf-8"))["api_key"] == "sk-alice-secret"
    assert get_api_key() == "sk-alice-secret"

    monkeypatch.setenv("USERNAME", "bob")
    assert get_api_key() is None
    set_api_key("sk-bob-secret")
    bob_file = tmp_path / "SubFlow" / "users" / "bob" / "credentials.json"
    assert bob_file.is_file()
    assert get_api_key() == "sk-bob-secret"
    assert json.loads(alice_file.read_text(encoding="utf-8"))["api_key"] == "sk-alice-secret"

    delete_api_key()
    assert get_api_key() is None
    assert not bob_file.is_file()
    monkeypatch.setenv("USERNAME", "alice")
    assert get_api_key() == "sk-alice-secret"
    delete_api_key()
    assert get_api_key() is None
    _ = store
    _ = Path
