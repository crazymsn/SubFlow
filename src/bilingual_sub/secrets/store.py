from __future__ import annotations

import json
import logging
import os
import re
import stat
import sys
from contextlib import nullcontext
from pathlib import Path

logger = logging.getLogger(__name__)

SERVICE_NAME = "subflow"
LEGACY_SERVICE_NAME = "bilingual-sub"
CREDENTIAL_KEY = "meding_api_key"
ENV_KEY_NAMES = ("SUBFLOW_API_KEY", "MEDING_API_KEY")


def _macos_get_password(service: str, username: str) -> str | None:
    from bilingual_sub.secrets.macos_keychain import get_password

    return get_password(service, username)


def _keyring_access():
    if sys.platform == "darwin":
        from bilingual_sub.secrets.macos_keychain import KEYCHAIN_LOCK

        return KEYCHAIN_LOCK
    return nullcontext()


def _os_user() -> str:
    for name in (os.environ.get("USERNAME"), os.environ.get("USER"), os.environ.get("LOGNAME")):
        if name and name.strip():
            return name.strip()
    try:
        import getpass

        return getpass.getuser().strip() or "default"
    except Exception:
        return "default"


def _safe_user() -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", _os_user()).strip("._")
    return safe or "default"


def _credential_username() -> str:
    return f"{_safe_user()}::{CREDENTIAL_KEY}"


def _config_bases() -> list[Path]:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home()))
        return [root / "SubFlow", root / "bilingual-sub"]
    home = Path.home() / ".config"
    return [home / "subflow", home / "bilingual-sub"]


def _user_fallback_path() -> Path:
    return _config_bases()[0] / "users" / _safe_user() / "credentials.json"


def _legacy_fallback_paths() -> list[Path]:
    return [base / "credentials.json" for base in _config_bases()]


def _restrict_permissions(path: Path) -> None:
    try:
        if os.name != "nt":
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            path.parent.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            return
        user = _os_user()
        import subprocess

        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(R,W)"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        pass


def _write_fallback(path: Path, key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"api_key": key}), encoding="utf-8")
    _restrict_permissions(path)


def _read_fallback(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        found = str(data.get("api_key") or "").strip()
        return found or None
    except (json.JSONDecodeError, OSError):
        return None


def _keyring_get(username: str) -> str | None:
    try:
        import keyring

        for service in (SERVICE_NAME, LEGACY_SERVICE_NAME):
            reader = _macos_get_password if sys.platform == "darwin" else keyring.get_password
            val = reader(service, username)
            if val:
                return val
    except Exception:
        return None
    return None


def _keyring_set(username: str, key: str) -> bool:
    try:
        import keyring

        with _keyring_access():
            keyring.set_password(SERVICE_NAME, username, key)
        return True
    except Exception as exc:
        logger.debug("keyring unavailable: %s", exc)
        return False


def _keyring_delete(username: str) -> None:
    try:
        import keyring

        with _keyring_access():
            for service in (SERVICE_NAME, LEGACY_SERVICE_NAME):
                try:
                    keyring.delete_password(service, username)
                except Exception:
                    pass
    except Exception:
        pass


def set_api_key(key: str) -> None:
    key = key.strip()
    if not key:
        raise ValueError("API key cannot be empty")
    if _keyring_set(_credential_username(), key):
        logger.info("API key saved to current-user credential store")
        return
    path = _user_fallback_path()
    _write_fallback(path, key)
    logger.info("API key saved for current Windows user")


def get_api_key() -> str | None:
    for name in ENV_KEY_NAMES:
        val = (os.environ.get(name) or "").strip()
        if val:
            return val

    scoped = _keyring_get(_credential_username())
    if scoped:
        return scoped

    legacy = _keyring_get(CREDENTIAL_KEY)
    if legacy:
        # Startup also reads credentials. Migration writes/deletes may prompt on
        # macOS even when the read succeeded silently; leave existing items intact.
        if sys.platform != "darwin":
            _keyring_set(_credential_username(), legacy)
            _keyring_delete(CREDENTIAL_KEY)
        return legacy

    scoped_file = _read_fallback(_user_fallback_path())
    if scoped_file:
        return scoped_file

    for path in _legacy_fallback_paths():
        found = _read_fallback(path)
        if found:
            if sys.platform == "darwin":
                return found
            if _keyring_set(_credential_username(), found):
                path.unlink(missing_ok=True)
            else:
                _write_fallback(_user_fallback_path(), found)
                if path.resolve() != _user_fallback_path().resolve():
                    path.unlink(missing_ok=True)
            return found
    return None


def delete_api_key() -> None:
    _keyring_delete(_credential_username())
    _keyring_delete(CREDENTIAL_KEY)
    for path in [_user_fallback_path(), *_legacy_fallback_paths()]:
        if path.is_file():
            path.unlink(missing_ok=True)


def mask_api_key(key: str | None) -> str:
    if not key:
        return "(not set)"
    if len(key) <= 8:
        return "sk-***"
    return f"sk-***{key[-4:]}"
