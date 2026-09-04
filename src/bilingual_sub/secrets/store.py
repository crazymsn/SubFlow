from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

SERVICE_NAME = "subflow"
LEGACY_SERVICE_NAME = "bilingual-sub"
CREDENTIAL_KEY = "meding_api_key"
ENV_KEY_NAMES = ("SUBFLOW_API_KEY", "MEDING_API_KEY")


def _config_bases() -> list[Path]:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home()))
        return [root / "SubFlow", root / "bilingual-sub"]
    home = Path.home() / ".config"
    return [home / "subflow", home / "bilingual-sub"]


def _fallback_path() -> Path:
    base = _config_bases()[0]
    base.mkdir(parents=True, exist_ok=True)
    return base / "credentials.json"


def _legacy_fallback_path() -> Path:
    bases = _config_bases()
    return bases[-1] / "credentials.json"


def _restrict_permissions(path: Path) -> None:
    try:
        if os.name != "nt":
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def set_api_key(key: str) -> None:
    key = key.strip()
    if not key:
        raise ValueError("API key cannot be empty")
    try:
        import keyring

        keyring.set_password(SERVICE_NAME, CREDENTIAL_KEY, key)
        logger.info("API key saved to system credential store")
        return
    except Exception as exc:
        logger.debug("keyring unavailable: %s", exc)

    path = _fallback_path()
    path.write_text(json.dumps({"api_key": key}), encoding="utf-8")
    _restrict_permissions(path)
    logger.info("API key saved to %s", path)


def get_api_key() -> str | None:
    for name in ENV_KEY_NAMES:
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    try:
        import keyring

        for service in (SERVICE_NAME, LEGACY_SERVICE_NAME):
            val = keyring.get_password(service, CREDENTIAL_KEY)
            if val:
                return val
    except Exception:
        pass

    for path in (_fallback_path(), _legacy_fallback_path()):
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                found = str(data.get("api_key") or "").strip()
                if found:
                    return found
            except (json.JSONDecodeError, OSError):
                continue
    return None


def delete_api_key() -> None:
    try:
        import keyring

        for service in (SERVICE_NAME, LEGACY_SERVICE_NAME):
            try:
                keyring.delete_password(service, CREDENTIAL_KEY)
            except Exception:
                pass
    except Exception:
        pass
    for path in (_fallback_path(), _legacy_fallback_path()):
        if path.is_file():
            path.unlink(missing_ok=True)


def mask_api_key(key: str | None) -> str:
    if not key:
        return "(not set)"
    if len(key) <= 8:
        return "sk-***"
    return f"sk-***{key[-4:]}"
