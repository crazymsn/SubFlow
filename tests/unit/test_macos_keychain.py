import ctypes
import sys
from types import SimpleNamespace

import keyring
import pytest

from bilingual_sub.secrets import store


def test_mac_read_never_falls_back_to_interactive_keyring(monkeypatch):
    monkeypatch.setattr(store, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(store, "_macos_get_password", lambda *args: None)
    monkeypatch.setattr(keyring, "get_password", lambda *args: pytest.fail("interactive read"))
    assert store.get_api_key() is None


def test_mac_legacy_key_read_does_not_migrate_or_delete(monkeypatch):
    monkeypatch.setattr(store, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(store, "_macos_get_password",
                        lambda service, user: "test-token" if user == store.CREDENTIAL_KEY else None)
    monkeypatch.setattr(store, "_keyring_set", lambda *args: pytest.fail("startup write"))
    monkeypatch.setattr(store, "_keyring_delete", lambda *args: pytest.fail("startup delete"))
    assert store.get_api_key() == "test-token"


def test_mac_legacy_file_read_preserves_storage(monkeypatch):
    monkeypatch.setattr(store, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(store, "_macos_get_password", lambda *args: None)
    monkeypatch.setattr(store, "_keyring_set", lambda *args: pytest.fail("startup write"))
    path = store._legacy_fallback_paths()[0]
    store._write_fallback(path, "test-file-token")
    before = path.read_bytes()
    assert store.get_api_key() == "test-file-token"
    assert path.read_bytes() == before
    assert not store._user_fallback_path().exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Security framework")
@pytest.mark.parametrize("status", [-25308, -25300, -128, -25293, 0])
def test_native_query_disallows_authentication_ui(monkeypatch, status):
    from keyring.backends.macOS import api

    from bilingual_sub.secrets.macos_keychain import get_password

    lookup = api._found.CFDictionaryGetValue
    lookup.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    lookup.restype = ctypes.c_void_p
    create_data = api._found.CFDataCreate
    create_data.argtypes = (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long)
    create_data.restype = ctypes.c_void_p
    calls = []

    def copy_matching(query, result):
        allowed = ctypes.c_ubyte()
        assert api._sec.SecKeychainGetUserInteractionAllowed(ctypes.byref(allowed)) == 0
        assert not allowed.value, "legacy Keychain interaction must also be disabled"
        assert lookup(query, api.k_("kSecUseAuthenticationUI")) == api.k_("kSecUseAuthenticationUIFail").value
        assert lookup(query, api.k_("kSecMatchLimit")) == api.k_("kSecMatchLimitOne").value
        calls.append(True)
        if status == 0:
            ctypes.cast(result, ctypes.POINTER(ctypes.c_void_p))[0] = create_data(None, b"test-token", 10)
        return status

    # Never access the real user's Keychain, even in this native ABI test.
    monkeypatch.setattr(api, "SecItemCopyMatching", copy_matching)
    assert get_password("test-service", "test-user") == ("test-token" if status == 0 else None)
    assert calls == [True]


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Security framework")
@pytest.mark.parametrize("previous", [0, 1])
def test_legacy_interaction_setting_is_restored_on_exception(monkeypatch, previous):
    from keyring.backends.macOS import api

    from bilingual_sub.secrets.macos_keychain import get_password

    states = []

    def get_allowed(ptr):
        ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ubyte))[0] = previous
        return 0

    def set_allowed(value):
        states.append(int(value))
        return 0

    def fail(*args):
        assert states == [0]
        raise RuntimeError("query failure")

    monkeypatch.setattr(api._sec, "SecKeychainGetUserInteractionAllowed", get_allowed)
    monkeypatch.setattr(api._sec, "SecKeychainSetUserInteractionAllowed", set_allowed)
    monkeypatch.setattr(api, "SecItemCopyMatching", fail)
    with pytest.raises(RuntimeError, match="query failure"):
        get_password("test-service", "test-user")
    assert states == [0, previous]


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Security framework")
@pytest.mark.parametrize("failure", ["get", "set"])
def test_cannot_disable_interaction_does_not_query(monkeypatch, failure):
    from keyring.backends.macOS import api

    from bilingual_sub.secrets.macos_keychain import get_password

    def get_allowed(ptr):
        return -50 if failure == "get" else 0

    def set_allowed(value):
        return -50 if failure == "set" else 0

    monkeypatch.setattr(api._sec, "SecKeychainGetUserInteractionAllowed", get_allowed)
    monkeypatch.setattr(api._sec, "SecKeychainSetUserInteractionAllowed", set_allowed)
    monkeypatch.setattr(api, "SecItemCopyMatching", lambda *args: pytest.fail("unsafe query"))
    with pytest.raises(api.Error):
        get_password("test-service", "test-user")


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Keychain lock")
def test_explicit_save_waits_for_silent_read_lock(monkeypatch):
    import threading

    from bilingual_sub.secrets.macos_keychain import KEYCHAIN_LOCK

    entered = threading.Event()
    saved = threading.Event()
    monkeypatch.setattr(keyring, "set_password", lambda *args: saved.set())

    def save():
        entered.set()
        assert store._keyring_set("test-user", "test-token")

    with KEYCHAIN_LOCK:
        worker = threading.Thread(target=save)
        worker.start()
        assert entered.wait(2)
        assert not saved.wait(0.05)
    worker.join(2)
    assert not worker.is_alive() and saved.is_set()
