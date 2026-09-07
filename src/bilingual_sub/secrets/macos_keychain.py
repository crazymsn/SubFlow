"""Read legacy macOS Keychain items without requesting authentication UI."""
from __future__ import annotations

import ctypes
import threading
from contextlib import contextmanager

KEYCHAIN_LOCK = threading.RLock()


@contextmanager
def _without_interaction(api):
    # kSecUseAuthenticationUIFail alone is ignored by the legacy macOS
    # file-based Keychain's ACL path. This flag is local to this process.
    get_allowed = api._sec.SecKeychainGetUserInteractionAllowed
    get_allowed.argtypes = (ctypes.POINTER(ctypes.c_ubyte),)
    get_allowed.restype = ctypes.c_int32
    set_allowed = api._sec.SecKeychainSetUserInteractionAllowed
    set_allowed.argtypes = (ctypes.c_ubyte,)
    set_allowed.restype = ctypes.c_int32
    previous = ctypes.c_ubyte()
    api.Error.raise_for_status(get_allowed(ctypes.byref(previous)))
    api.Error.raise_for_status(set_allowed(False))
    try:
        yield
    finally:
        api.Error.raise_for_status(set_allowed(previous.value))


def get_password(service: str, username: str) -> str | None:
    from keyring.backends.macOS import api

    with KEYCHAIN_LOCK, _without_interaction(api):
        return _query_password(api, service, username)


def _query_password(api, service: str, username: str) -> str | None:
    # Preserve the item ACL and the previous process interaction setting.
    release = api._found.CFRelease
    release.argtypes = (ctypes.c_void_p,)
    release.restype = None
    values = {
        "kSecClass": api.k_("kSecClassGenericPassword"),
        "kSecMatchLimit": api.k_("kSecMatchLimitOne"),
        "kSecUseAuthenticationUI": api.k_("kSecUseAuthenticationUIFail"),
        "kSecReturnData": ctypes.c_void_p.in_dll(api._found, "kCFBooleanTrue"),
    }
    owned = []
    result = ctypes.c_void_p()
    try:
        for name, value in (("kSecAttrService", service), ("kSecAttrAccount", username)):
            ref = api.create_cf(value)
            if not ref:
                raise MemoryError("Cannot allocate Keychain query")
            owned.append(ref)
            values[name] = ref
        query = api.CFDictionaryCreate(
            None,
            (ctypes.c_void_p * len(values))(*(api.k_(name) for name in values)),
            (ctypes.c_void_p * len(values))(*values.values()),
            len(values),
            api._found.kCFTypeDictionaryKeyCallBacks,
            api._found.kCFTypeDictionaryValueCallBacks,
        )
        if not query:
            raise MemoryError("Cannot allocate Keychain query")
        owned.append(query)
        status = api.SecItemCopyMatching(query, ctypes.byref(result))
        if status in (api.error.item_not_found, api.error.sec_interaction_not_allowed,
                      api.error.keychain_denied, api.error.sec_auth_failed):
            return None
        api.Error.raise_for_status(status)
        return api.cfstr_to_str(result)
    finally:
        if result.value:
            release(result)
        for ref in reversed(owned):
            release(ref)
