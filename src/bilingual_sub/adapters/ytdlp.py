from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from filelock import FileLock, Timeout

from bilingual_sub.core.control import JobControl, JobStopped

logger = logging.getLogger(__name__)
_harvest_hint = ""


def harvest_hint() -> str:
    return _harvest_hint


def _set_harvest_hint(msg: str) -> None:
    global _harvest_hint
    _harvest_hint = msg

# Prefer the original spoken track. YouTube/Bilibili `ba` is often an English auto-dub.
def original_audio_selector(source_lang: str = "") -> str:
    """Prefer the original spoken track. Default is Chinese-first when source is unknown."""
    fam = ""
    raw = (source_lang or "").strip().lower()
    if raw and raw != "auto":
        if raw in {"zh", "zh-hans", "zh-hant", "zh-cn", "zh-tw"}:
            fam = "zh"
        else:
            fam = raw.split("-", 1)[0]
    extras: list[str] = []
    if fam == "zh":
        extras = ["ba[language^=zh]", "ba[language^=yue]"]
    elif fam:
        extras = [f"ba[language^={fam}]"]
    return "/".join(["ba[format_note*=original]", *extras, "ba[format_note!*=dub]", "ba"])


ORIGINAL_AUDIO = original_audio_selector("zh")
# Highest video + original audio. Prefer HTTPS at the same height; never fall back to `/b`.
BEST_AV_FORMAT = f"bv*[protocol^=http]+({ORIGINAL_AUDIO})/bv*+({ORIGINAL_AUDIO})"
LIST_FORMAT = "bv*+ba/bv*/bestvideo*"
HD_FLOOR = 1080
# Login cookies must not use tv / android. visionos still returns HTTPS/HLS when web/safari go SABR.
YT_SAFE_CLIENTS = ("default", "web_embedded", "visionos", "-tv", "-tv_downgraded")
YT_COOKIE_CLIENTS = (
    YT_SAFE_CLIENTS,
    ("web_embedded", "visionos", "-tv", "-tv_downgraded"),
)
YT_GUEST_CLIENTS = (
    ("default", "visionos"),
    ("visionos",),
    ("android", "ios", "visionos"),
)
BROWSERS = ("firefox", "edge", "safari", "chrome", "brave", "chromium")
_BROWSER_PATHS = {
    "firefox": (
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        "/Applications/Firefox.app",
        "/usr/bin/firefox",
    ),
    "edge": (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Microsoft Edge.app",
    ),
    "safari": ("/Applications/Safari.app",),
    "chrome": (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app",
        "/usr/bin/google-chrome",
    ),
    "brave": (
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        "/Applications/Brave Browser.app",
    ),
    "chromium": (
        r"C:\Program Files\Chromium\Application\chrome.exe",
        "/Applications/Chromium.app",
        "/usr/bin/chromium",
    ),
}
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


class DownloadError(RuntimeError):
    pass


def _host_matches(url: str, domains: tuple[str, ...]) -> bool:
    try:
        parsed = urlparse((url or "").strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        return parsed.scheme.lower() in {"http", "https"} and any(
            host == domain or host.endswith("." + domain) for domain in domains)
    except ValueError:
        return False


def is_bilibili_url(url: str) -> bool:
    return _host_matches(url, ("bilibili.com", "b23.tv", "bili2233.cn", "bilibili.tv"))


def is_youtube_url(url: str) -> bool:
    return _host_matches(url, ("youtube.com", "youtu.be", "youtube-nocookie.com"))


def _raw_media_slug(url: str) -> str:
    parsed = urlparse(canonicalize_url(url))
    host = (parsed.hostname or "").lower().rstrip(".")
    if host == "youtu.be" or host.endswith(".youtu.be"):
        return (parsed.path.strip("/").split("/") or ["video"])[0] or "video"
    video = (parse_qs(parsed.query).get("v") or [""])[0]
    if video:
        return video
    for part in parsed.path.split("/"):
        if part.startswith(("BV", "av", "ep")):
            return part
    return "video"


def media_slug(url: str) -> str:
    raw = _raw_media_slug(url)
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10))}
    if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", raw) and raw.upper() not in reserved:
        return raw
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", raw)[:60].strip("_") or "video"
    return f"{safe}-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


def download_folder(url: str, root: Path | None = None) -> Path:
    base = root or Path.home() / "Downloads" / "SubFlow"
    return base / media_slug(url)


def canonicalize_url(url: str) -> str:
    text = (url or "").strip()
    return (
        text.replace("://m.bilibili.com/", "://www.bilibili.com/")
        .replace("://www.bilibili.tv/", "://www.bilibili.com/")
        .replace("://bilibili.tv/", "://www.bilibili.com/")
    )


def _referer(url: str) -> str:
    if is_bilibili_url(url):
        return "https://www.bilibili.com/"
    if is_youtube_url(url):
        return "https://www.youtube.com/"
    return "https://www.youtube.com/"


def _bilibili_guest_cookies(dest_dir: Path) -> Path:
    import uuid

    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / "buvid.cookies.txt"
    buvid = str(uuid.uuid4()).upper()
    path.write_text(
        "# Netscape HTTP Cookie File\n"
        f".bilibili.com\tTRUE\t/\tFALSE\t0\tbuvid3\t{buvid}\n"
        f".bilibili.com\tTRUE\t/\tFALSE\t0\tbuvid4\t{buvid}\n"
        ".bilibili.com\tTRUE\t/\tFALSE\t0\tCURRENT_FNVAL\t4048\n"
        ".bilibili.com\tTRUE\t/\tFALSE\t0\tbili_locale\tzh-CN\n"
        ".bilibili.com\tTRUE\t/\tFALSE\t0\tbili_locale_sec\tzh-CN\n",
        encoding="utf-8",
    )
    return path


def _with_bilibili_locale(cookiefile: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / "bili.locale.cookies.txt"
    try:
        text = cookiefile.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return cookiefile
    lines = [line for line in text.splitlines() if "bili_locale" not in line.lower()]
    if not lines or not lines[0].startswith("#"):
        lines.insert(0, "# Netscape HTTP Cookie File")
    lines.append(".bilibili.com\tTRUE\t/\tFALSE\t0\tbili_locale\tzh-CN")
    lines.append(".bilibili.com\tTRUE\t/\tFALSE\t0\tbili_locale_sec\tzh-CN")
    try:
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        return cookiefile
    return out


def _patch_bilibili_original_audio() -> None:
    """Account locale can make playurl return English AI dub as the only audio."""
    try:
        from yt_dlp.extractor.bilibili import BilibiliBaseIE
    except Exception:
        return
    if getattr(BilibiliBaseIE, "_subflow_original_audio", False):
        return

    orig = BilibiliBaseIE._download_playinfo

    def _download_playinfo(self, bvid, cid, headers=None, query=None, fatal=True):
        q = dict(query or {})
        q.pop("cur_language", None)
        data = orig(self, bvid, cid, headers=headers, query=q, fatal=fatal)
        if not data:
            return data
        current = str(data.get("cur_language") or "").strip()
        if current:
            logger.info("bilibili playurl used AI dub %s; refetching original audio", current)
            q = dict(q)
            q["cur_language"] = ""
            retried = orig(self, bvid, cid, headers=headers, query=q, fatal=False)
            if retried:
                return retried
        return data

    BilibiliBaseIE._download_playinfo = _download_playinfo
    BilibiliBaseIE._subflow_original_audio = True


def available_browsers() -> tuple[str, ...]:
    """Browsers that look installed. Cookie fallback only opens these jars."""
    found: list[str] = []
    for name in BROWSERS:
        for raw in _BROWSER_PATHS.get(name, ()):
            try:
                if Path(raw).exists():
                    found.append(name)
                    break
            except OSError:
                continue
    return tuple(found)


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def _usable_cookie(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 32
    except OSError:
        return False


def _cookie_names(url: str | None) -> list[str]:
    if url and is_youtube_url(url):
        return ["youtube-cookies.txt", "cookies.txt"]
    if url and is_bilibili_url(url):
        return ["bilibili-cookies.txt", "cookies.txt"]
    return ["cookies.txt", "youtube-cookies.txt", "bilibili-cookies.txt"]


def _is_subflow_cookie_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        resolved = str(path.resolve()).lower().replace("/", "\\")
    except OSError:
        resolved = str(path).lower()
    if "inetcookies" in resolved:
        return False
    names = ("youtube-cookies.txt", "bilibili-cookies.txt", "cookies.txt", ".gitkeep")
    try:
        return any((path / name).exists() for name in names)
    except OSError:
        return False


def cookie_folder_dirs() -> list[Path]:
    """Cookies folders: user config first, then repo/exe templates."""
    dirs: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen or not _is_subflow_cookie_dir(resolved):
            return
        seen.add(resolved)
        dirs.append(resolved)

    try:
        from bilingual_sub.config import user_config_dir

        add(user_config_dir() / "Cookies")
    except Exception:
        pass
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if local:
        add(Path(local) / "SubFlow" / "Cookies")
    root = _project_root()
    add(root / "Cookies")
    here = root
    for _ in range(3):
        here = here.parent
        add(here / "Cookies")
    try:
        add(Path.cwd() / "Cookies")
    except OSError:
        pass
    return dirs


def cookie_search_dirs() -> list[Path]:
    dirs = list(cookie_folder_dirs())
    root = _project_root()
    for extra in (root / "config", root):
        if extra.is_dir() and extra not in dirs:
            dirs.append(extra)
    try:
        from bilingual_sub.config import user_config_dir

        cfg = user_config_dir()
        if cfg.is_dir() and cfg not in dirs:
            dirs.append(cfg)
    except Exception:
        pass
    return dirs


def _cookie_field_names(path: Path) -> set[str]:
    names: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return names
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            names.add(parts[5])
    return names


_YT_SESSION_COOKIES = frozenset({
    "SID",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "SAPISID",
    "__Secure-3PAPISID",
    "HSID",
    "SSID",
})
_YT_VISITOR_COOKIES = frozenset({"VISITOR_INFO1_LIVE", "PREF", "SOCS", "NID", "YSC", "GPS"})
_BILI_LOGIN_COOKIES = frozenset({"SESSDATA", "bili_jct", "DedeUserID"})


def youtube_cookie_is_guest(path: Path) -> bool:
    """True when a Netscape jar has no SID-family session cookies."""
    names = _cookie_field_names(path)
    if not names:
        return False
    if names & _YT_SESSION_COOKIES:
        return False
    return bool(names & _YT_VISITOR_COOKIES) or "LOGIN_INFO" in names


def cookie_has_site_login(path: Path, url: str | None) -> bool:
    names = _cookie_field_names(path)
    if not names:
        return True
    if url and is_youtube_url(url):
        return bool(names & _YT_SESSION_COOKIES)
    if url and is_bilibili_url(url):
        return bool(names & _BILI_LOGIN_COOKIES)
    return True


def cookie_file(url: str | None = None) -> Path | None:
    names = _cookie_names(url)
    found: list[Path] = []
    for folder in cookie_folder_dirs():
        for name in names:
            path = folder / name
            if _usable_cookie(path):
                found.append(path)
    env = (os.environ.get("SUBFLOW_COOKIES") or os.environ.get("YTDLP_COOKIES") or "").strip()
    if env:
        env_path = Path(env)
        if _usable_cookie(env_path):
            found.append(env_path)
    seen = set(cookie_folder_dirs())
    for root in cookie_search_dirs():
        if root in seen:
            continue
        for name in names:
            path = root / name
            if _usable_cookie(path):
                found.append(path)
    if url and is_youtube_url(url):
        logged = [path for path in found if not youtube_cookie_is_guest(path)]
        if logged:
            return logged[0]
        return None
    return found[0] if found else None


def _as_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(str(value))
    except (TypeError, ValueError):
        return None


def download_fraction(status: dict) -> float | None:
    state = str(status.get("status") or "")
    if state == "finished":
        return 1.0
    if state != "downloading":
        return None
    done = _as_float(status.get("downloaded_bytes"))
    total = _as_float(status.get("total_bytes")) or _as_float(status.get("total_bytes_estimate"))
    frag_i = _as_float(status.get("fragment_index"))
    frag_n = _as_float(status.get("fragment_count"))
    if frag_n and frag_n > 1 and frag_i is not None:
        inner = 0.0
        if total and total > 0 and done is not None:
            inner = min(1.0, max(0.0, done / total))
        overall = (max(0.0, frag_i - 1.0) + inner) / frag_n
        return min(0.999, max(0.0, overall))
    if total and total > 0 and done is not None:
        return min(0.999, max(0.0, done / total))
    raw = str(status.get("_percent_str") or "").strip().rstrip("%")
    try:
        if raw:
            return min(0.999, max(0.0, float(raw) / 100.0))
    except ValueError:
        return None
    return None


def _stream_key(status: dict) -> str:
    info = status.get("info_dict") or {}
    fmt = str(info.get("format_id") or "").strip()
    if fmt:
        return f"fmt:{fmt}"
    name = str(status.get("filename") or status.get("tmpfilename") or "")
    for token in ("-Frag", ".part"):
        cut = name.find(token)
        if cut > 0:
            name = name[:cut]
            break
    return name or str(info.get("format") or "stream")


class StreamProgress:
    """Map video-then-audio (and retries) onto a single non-decreasing 0–1 bar."""

    def __init__(self, expected: int = 1) -> None:
        self.expected = max(1, expected)
        self._keys: list[str] = []
        self._frac: dict[str, float] = {}
        self._last = 0.0
        self._attempt_base = 0.0

    def set_expected(self, n: int) -> None:
        if n > 0:
            self.expected = max(1, int(n))

    def begin_attempt(self) -> None:
        self._attempt_base = self._last
        self._keys.clear()
        self._frac.clear()

    def feed(self, status: dict) -> float | None:
        key = _stream_key(status)
        if key not in self._keys:
            self._keys.append(key)
            if len(self._keys) > self.expected:
                self.expected = len(self._keys)
        local = download_fraction(status)
        if local is None:
            return None
        self._frac[key] = max(self._frac.get(key, 0.0), min(1.0, local))
        raw = sum(self._frac.get(item, 0.0) for item in self._keys) / max(self.expected, len(self._keys))
        base = self._attempt_base
        mapped = base + (0.99 - base) * raw if base > 0 else raw
        self._last = min(0.99, max(self._last, mapped))
        return self._last


def max_video_height(info: dict | None) -> int:
    if not info:
        return 0
    heights: list[int] = []
    for fmt in info.get("formats") or ():
        if (fmt.get("vcodec") or "none") == "none":
            continue
        if not (fmt.get("url") or fmt.get("manifest_url")):
            continue
        height = _as_float(fmt.get("height"))
        if height and height > 0:
            heights.append(int(height))
    top = _as_float(info.get("height"))
    if top and top > 0:
        heights.append(int(top))
    return max(heights) if heights else 0


def selected_height(info: dict | None) -> int:
    if not info:
        return 0
    heights: list[int] = []
    for fmt in info.get("requested_formats") or ():
        if (fmt.get("vcodec") or "none") == "none":
            continue
        height = _as_float(fmt.get("height"))
        if height and height > 0:
            heights.append(int(height))
    if heights:
        return max(heights)
    return int(_as_float(info.get("height")) or 0)


def quality_target(listed: int) -> int:
    """Pin to the source maximum. If still unknown, refuse anything below HD."""
    return int(listed) if listed > 0 else HD_FLOOR


def format_for_height(height: int, source_lang: str = "") -> str:
    pin = quality_target(height)
    audio = original_audio_selector(source_lang or "zh")
    return (
        f"bv*[height>={pin}][protocol^=http]+({audio})/"
        f"bv*[height>={pin}]+({audio})/"
        f"b[height>={pin}][format_note*=original]/"
        f"b[height>={pin}]"
    )


def _audio_formats(info: dict | None) -> list[dict]:
    if not info:
        return []
    out: list[dict] = []
    for fmt in list(info.get("requested_formats") or ()) + list(info.get("formats") or ()):
        if str(fmt.get("acodec") or "none") == "none":
            continue
        out.append(fmt)
    return out


def audio_track_kind(fmt: dict | None) -> str:
    """original | dubbed | unknown"""
    if not fmt:
        return "unknown"
    note = str(fmt.get("format_note") or "").lower()
    pref = fmt.get("language_preference")
    try:
        pref_n = int(pref) if pref is not None else None
    except (TypeError, ValueError):
        pref_n = None
    if "original" in note or pref_n == 10:
        return "original"
    if "dub" in note or "dubbed" in note:
        return "dubbed"
    return "unknown"


def original_audio_format_id(info: dict | None) -> str | None:
    best_id = None
    best_abr = -1.0
    for fmt in (info or {}).get("formats") or ():
        if str(fmt.get("acodec") or "none") == "none":
            continue
        if audio_track_kind(fmt) != "original":
            continue
        try:
            abr = float(fmt.get("abr") or fmt.get("tbr") or 0)
        except (TypeError, ValueError):
            abr = 0.0
        ident = str(fmt.get("format_id") or "").strip()
        if ident and abr >= best_abr:
            best_abr = abr
            best_id = ident
    return best_id


def prefer_audio_format(info: dict | None, height: int, source_lang: str = "") -> str:
    fmt = format_for_height(height, source_lang)
    if not selected_audio_is_dubbed(info):
        return fmt
    orig = original_audio_format_id(info)
    if not orig:
        return fmt
    logger.info("replacing dubbed audio with original %s", orig)
    return (
        f"bv*[height>={height}][protocol^=http]+{orig}/"
        f"bv*[height>={height}]+{orig}/"
        + fmt
    )


def selected_audio_is_dubbed(info: dict | None) -> bool:
    requested = [
        fmt
        for fmt in (info or {}).get("requested_formats") or ()
        if str(fmt.get("acodec") or "none") != "none"
    ]
    if not requested:
        return False
    return any(audio_track_kind(fmt) == "dubbed" for fmt in requested) and not any(
        audio_track_kind(fmt) == "original" for fmt in requested
    )


def _impersonate():
    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget
    except Exception:
        return None
    for spec in ("chrome-131", "chrome-124", "chrome-120", "chrome-110", "chrome"):
        try:
            return ImpersonateTarget.from_str(spec)
        except Exception:
            continue
    return None


def _runtime_bin_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if local:
        return Path(local) / "SubFlow" / "bin"
    return Path.home() / ".cache" / "subflow" / "bin"


def _which_js_runtime(name: str) -> str | None:
    exe = shutil.which(name)
    if exe:
        return exe
    suffix = ".exe" if os.name == "nt" else ""
    local = _runtime_bin_dir() / f"{name}{suffix}"
    if local.is_file():
        return str(local)
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).resolve().parent / f"{name}{suffix}"
        if bundled.is_file():
            return str(bundled)
    return None


def js_runtime_map() -> dict[str, dict]:
    """yt-dlp 2026+ needs a JS runtime or YouTube falls back to visionos-only."""
    runtimes: dict[str, dict] = {"deno": {}, "node": {}, "bun": {}, "quickjs": {}}
    for name in runtimes:
        path = _which_js_runtime(name)
        if path:
            runtimes[name] = {"path": path}
    return runtimes


def _harvest_allowed() -> bool:
    if os.environ.get("SUBFLOW_NO_BROWSER_HARVEST"):
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return True


def _process_running(image: str) -> bool:
    if os.name != "nt":
        return False
    try:
        completed = shutil.which("tasklist")
        if not completed:
            return False
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        return image.lower() in (out.stdout or "").lower()
    except Exception:
        return False


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _cdp_cookies(port: int, timeout: float = 18.0) -> list[dict]:
    import json
    import urllib.request

    from websockets.sync.client import connect

    deadline = time.time() + timeout
    version = None
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.5) as resp:
                version = json.loads(resp.read().decode("utf-8", errors="ignore"))
            break
        except Exception as exc:
            last = exc
            time.sleep(0.25)
    if not version:
        raise RuntimeError(f"cdp not ready: {last}")
    ws_url = version.get("webSocketDebuggerUrl")
    if not ws_url:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as resp:
            pages = json.loads(resp.read().decode("utf-8", errors="ignore"))
        ws_url = next((item.get("webSocketDebuggerUrl") for item in pages if item.get("webSocketDebuggerUrl")), None)
    if not ws_url:
        raise RuntimeError("no cdp websocket")
    with connect(ws_url, open_timeout=6, close_timeout=3) as ws:
        ws.send(json.dumps({"id": 1, "method": "Storage.getCookies"}))
        while True:
            msg = json.loads(ws.recv(timeout=8))
            if msg.get("id") == 1:
                if msg.get("error"):
                    raise RuntimeError(str(msg["error"]))
                return list((msg.get("result") or {}).get("cookies") or [])


def _adopt_harvested_jar(dest: Path, cookies: list[dict], usable) -> Path | None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and usable(dest):
        return dest
    tmp = dest.with_name(f"{dest.name}.{os.getpid()}.tmp")
    try:
        _write_netscape(tmp, cookies)
        if usable(tmp):
            tmp.replace(dest)
            return dest
        return None
    finally:
        tmp.unlink(missing_ok=True)


def _write_netscape(path: Path, cookies: list[dict]) -> Path:
    lines = ["# Netscape HTTP Cookie File"]
    for item in cookies:
        domain = str(item.get("domain") or "")
        name = str(item.get("name") or "")
        if not domain or not name:
            continue
        flag = "TRUE" if domain.startswith(".") else "FALSE"
        cookie_path = str(item.get("path") or "/")
        secure = "TRUE" if item.get("secure") else "FALSE"
        expiry = int(item.get("expires") or 0)
        value = str(item.get("value") or "")
        lines.append(f"{domain}\t{flag}\t{cookie_path}\t{secure}\t{expiry}\t{name}\t{value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _user_cookie_dir() -> Path:
    try:
        from bilingual_sub.config import user_config_dir

        return user_config_dir() / "Cookies"
    except Exception:
        return _runtime_bin_dir().parent / "Cookies"


def harvest_debug_cookies(url: str) -> Path | None:
    """Read cookies from an already-open Chrome/Edge remote-debugging port."""
    if not _harvest_allowed():
        return None
    for port in (9222, 9229, 9333):
        try:
            cookies = _cdp_cookies(port, timeout=2.5)
        except Exception:
            continue
        if not cookies:
            continue
        dest = _user_cookie_dir()
        if is_youtube_url(url):
            path = dest / "youtube-cookies.txt"
            adopted = _adopt_harvested_jar(
                path,
                cookies,
                lambda jar: (not youtube_cookie_is_guest(jar)) and _usable_cookie(jar),
            )
            if adopted:
                logger.info("harvested YouTube cookies from chrome debug port %s", port)
                return adopted
        if is_bilibili_url(url):
            path = dest / "bilibili-cookies.txt"
            adopted = _adopt_harvested_jar(
                path,
                cookies,
                lambda jar: cookie_has_site_login(jar, url) and _usable_cookie(jar),
            )
            if adopted:
                logger.info("harvested Bilibili cookies from chrome debug port %s", port)
                return adopted
    return None


def harvest_browser_cookies(url: str) -> Path | None:
    """Start Chrome/Edge with --remote-debugging-port when the browser is not running."""
    if not _harvest_allowed():
        return None
    attached = harvest_debug_cookies(url)
    if attached:
        return attached
    browsers = (
        (
            "chrome.exe",
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data",
        ),
        (
            "msedge.exe",
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "User Data",
        ),
        (
            "msedge.exe",
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "User Data",
        ),
    )
    for image, exe, user_data in browsers:
        if not exe.is_file() or not user_data.is_dir():
            continue
        if _process_running(image):
            attached = harvest_debug_cookies(url)
            if attached:
                return attached
            _set_harvest_hint(
                f"{image} 已在运行，无法自动读取 Cookie。"
                "请完全退出浏览器后重试，或开启远程调试端口，"
                "或把 Netscape 格式 cookies 放到 %APPDATA%\\SubFlow\\Cookies。"
            )
            logger.info("skip launching %s for cookie harvest: already running", image)
            continue
        port = _free_port()
        cmd = [
            str(exe),
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={user_data}",
            "--profile-directory=Default",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            cookies = _cdp_cookies(port, timeout=20)
        except Exception as exc:
            logger.info("cookie harvest via %s failed: %s", exe.name, exc)
            cookies = []
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=6)
                except Exception:
                    proc.kill()
        if not cookies:
            continue
        dest = _user_cookie_dir()
        if is_youtube_url(url):
            path = dest / "youtube-cookies.txt"
            adopted = _adopt_harvested_jar(
                path,
                cookies,
                lambda jar: (not youtube_cookie_is_guest(jar)) and _usable_cookie(jar),
            )
            if adopted:
                logger.info("harvested YouTube cookies from %s", exe.name)
                return adopted
        if is_bilibili_url(url):
            path = dest / "bilibili-cookies.txt"
            adopted = _adopt_harvested_jar(
                path,
                cookies,
                lambda jar: cookie_has_site_login(jar, url) and _usable_cookie(jar),
            )
            if adopted:
                logger.info("harvested Bilibili cookies from %s", exe.name)
                return adopted
    return None


def ydl_options(
    dest_dir: Path,
    url: str,
    *,
    hook: Callable[[dict], None] | None = None,
    fmt: str = BEST_AV_FORMAT,
    clients: tuple[str, ...] | None = None,
    cookiefile: Path | None = None,
    cookiesfrombrowser: tuple | None = None,
    impersonate: bool = True,
) -> dict:
    url = canonicalize_url(url)
    dest_dir.mkdir(parents=True, exist_ok=True)
    headers = {
        "Referer": _referer(url),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if is_bilibili_url(url):
        headers["Origin"] = "https://www.bilibili.com"
        headers["Referer"] = "https://www.bilibili.com/"
        if cookiefile is None and not cookiesfrombrowser:
            cookiefile = _bilibili_guest_cookies(dest_dir)
        if cookiefile is not None:
            cookiefile = _with_bilibili_locale(cookiefile, dest_dir)
    target = _impersonate() if impersonate else None
    if target is None:
        headers["User-Agent"] = CHROME_UA
    runtimes = js_runtime_map()
    opts: dict = {
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "merge_output_format": "mp4",
        "format": fmt,
        "format_sort": ["lang", "res", "proto:https", "fps", "hdr:12", "vbr", "abr"],
        "format_sort_force": True,
        "overwrites": True,
        "continuedl": False,
        "quiet": True,
        "noplaylist": True,
        "retries": 8,
        "fragment_retries": 8,
        "extractor_retries": 3,
        "file_access_retries": 3,
        "concurrent_fragment_downloads": 3,
        "socket_timeout": 30,
        "geo_bypass": True,
        "http_headers": headers,
        "js_runtimes": runtimes,
        "remote_components": ["ejs:github", "ejs:npm"],
    }
    if is_youtube_url(url):
        opts["extractor_args"] = {
            "youtube": {
                "player_client": list(clients or YT_SAFE_CLIENTS),
                "lang": ["zh-CN", "zh-Hans", "zh"],
            }
        }
    if target is not None:
        opts["impersonate"] = target
    if cookiefile is not None:
        opts["cookiefile"] = str(cookiefile)
    if cookiesfrombrowser:
        opts["cookiesfrombrowser"] = cookiesfrombrowser
    if hook:
        opts["progress_hooks"] = [hook]
    return opts


def youtube_cookies_rejected(exc: BaseException) -> bool:
    text = str(exc)
    low = text.lower()
    return "cookies are no longer valid" in low or "cookie 已失效" in text


def listing_probes(attempts: list[dict], limit: int = 6) -> list[dict]:
    """Always include a guest probe so a dead login jar cannot occupy every listing slot."""
    picks: list[dict] = []

    def take(pred) -> None:
        for item in attempts:
            if item in picks or not pred(item):
                continue
            picks.append(item)
            return

    take(lambda item: bool(item.get("cookiefile")))
    take(lambda item: not item.get("cookiefile") and not item.get("cookiesfrombrowser"))
    take(lambda item: bool(item.get("cookiesfrombrowser")))
    for item in attempts:
        if item not in picks:
            picks.append(item)
        if len(picks) >= limit:
            break
    return picks[:limit]


def download_attempts(url: str) -> Iterator[dict]:
    """Logged-in Cookies jar first; harvested browser session; then guest."""
    cookie = cookie_file(url)
    if is_youtube_url(url) or is_bilibili_url(url):
        attached = harvest_debug_cookies(url)
        if attached is not None:
            cookie = attached
        elif cookie is None:
            cookie = harvest_browser_cookies(url)
    browsers = available_browsers() or ("firefox", "edge", "chrome")

    def emit(profile: dict) -> dict:
        return {**profile, "fmt": BEST_AV_FORMAT}

    if is_youtube_url(url):
        if cookie:
            clients: tuple[str, ...]
            for clients in YT_COOKIE_CLIENTS:
                yield emit({"clients": clients, "cookiefile": cookie, "impersonate": True})
            for browser in browsers:
                yield emit(
                    {
                        "clients": YT_SAFE_CLIENTS,
                        "cookiesfrombrowser": (browser,),
                        "impersonate": True,
                    }
                )
            for clients in YT_GUEST_CLIENTS:
                yield emit({"clients": clients, "impersonate": True})
            return
        for clients in YT_GUEST_CLIENTS:
            yield emit({"clients": clients, "impersonate": True})
        for browser in browsers:
            yield emit(
                {
                    "clients": YT_SAFE_CLIENTS,
                    "cookiesfrombrowser": (browser,),
                    "impersonate": True,
                }
            )
        return

    if cookie:
        yield emit({"cookiefile": cookie, "impersonate": True})
    for browser in browsers:
        yield emit({"cookiesfrombrowser": (browser,), "impersonate": True})
    yield emit({"impersonate": True})


def explain_download_error(exc: BaseException) -> str:
    text = str(exc).strip()
    if text.startswith(("下载失败", "YouTube ", "B 站", "无法解析", "未安装", "无法下载", "禁止")):
        return text
    low = text.lower()
    first = text.split("See https://", 1)[0].split("Also see https://", 1)[0].strip()
    if "cookies are no longer valid" in low:
        return "YouTube Cookie 已失效。请重新导出 youtube-cookies.txt 放到 Cookies 文件夹后再试。"
    if "could not copy chrome cookie" in low or "failed to decrypt with dpapi" in low:
        extra = harvest_hint()
        return (
            "Chrome / Edge 的 Cookie 库已锁定或使用 v20 加密，无法直接读取。"
            "请把已登录的 Netscape 格式 youtube-cookies.txt / bilibili-cookies.txt "
            "放到 exe 同级、项目根或 %APPDATA%\\SubFlow\\Cookies；"
            "或完全退出浏览器后再点下载。"
            + (f" {extra}" if extra else "")
        )
    if "page needs to be reloaded" in low or "requested format is not available" in low:
        return "YouTube 没有返回可下载地址。请再试一次；若仍失败，请更新 Cookies 文件夹里的 youtube-cookies.txt。"
    if "412" in low and any(token in low for token in ("bilibili", "b23.tv", "precondition")):
        return (
            "B 站拦截了网页请求。已尝试读取本机浏览器登录 Cookie；"
            "请用已登录的浏览器打开 bilibili.com 后再点下载。"
        )
    if "not a bot" in low or "sign in to confirm" in low or "确认你不是聊天机器人" in text or "确认你不是机器人" in text:
        extra = harvest_hint()
        return (
            "YouTube 拦截了下载。请重新从已登录浏览器导出 youtube-cookies.txt "
            "（有 LOGIN_INFO 也可能已被轮换）；放到 exe 同级 / 项目 / %APPDATA%\\SubFlow\\Cookies。"
            + (f" {extra}" if extra else "")
        )
    if any(token in low for token in ("bilibili", "b23.tv")) and any(
        token in low for token in ("412", "403", "login", "risk", "风控", "登录")
    ):
        return (
            "B 站拒绝了游客下载。请用浏览器登录 bilibili.com 后再试，"
            "或把 Netscape 格式的 bilibili-cookies.txt 放到本机配置目录。"
        )
    if "unsupported url" in low or "unable to extract" in low:
        return f"无法解析该链接：{first.splitlines()[0] if first else text}"
    if first:
        return f"下载失败：{first.splitlines()[0]}"
    return f"下载失败：{exc}"


def _picked_file(dest_dir: Path, *, since: float | None = None) -> Path | None:
    exact = dest_dir / "source.mp4"
    candidates = [exact] if exact.is_file() else sorted(p for p in dest_dir.glob("source.*") if p.is_file())
    for path in candidates:
        if not path.is_file():
            continue
        if since is not None and path.stat().st_mtime + 0.05 < since:
            continue
        return path
    return None


def _ensure_mp4(path: Path, dest_dir: Path, *, control: JobControl | None = None) -> Path:
    if control:
        control.wait_if_paused()
    target = dest_dir / "source.mp4"
    if path.suffix.lower() == ".mp4":
        if path.resolve() != target.resolve():
            shutil.copy2(path, target)
        if control:
            control.wait_if_paused()
        return target
    try:
        from bilingual_sub.adapters.ffmpeg import remux_to_mp4

        return remux_to_mp4(path, target, control=control)
    except JobStopped:
        raise
    except Exception as exc:
        raise DownloadError(f"下载文件转为 MP4 失败：{exc}") from exc


def _audio_status(path: Path) -> bool | None:
    try:
        from bilingual_sub.adapters.ffmpeg import probe_video

        return bool(probe_video(path).get("has_audio"))
    except Exception:
        return None


def _video_height(path: Path) -> int:
    try:
        from bilingual_sub.adapters.ffmpeg import probe_video

        return int(probe_video(path).get("height") or 0)
    except Exception:
        return 0


def download(
    url: str,
    dest_dir: Path,
    *,
    on_progress: Callable[[str, float], None] | None = None,
    control: JobControl | None = None,
    progress_range: tuple[float, float] = (0.03, 0.20),
    source_lang: str = "",
) -> Path:
    from bilingual_sub.adapters.download_worker import run_download_worker

    if control:
        control.wait_if_paused()
    dest_dir.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(dest_dir / ".download.lock"))
    try:
        lock.acquire(timeout=0)
    except Timeout as exc:
        raise DownloadError(f"该目录正在下载，请等待完成：{dest_dir}") from exc
    try:
        with tempfile.TemporaryDirectory(prefix=".subflow-download-", dir=dest_dir) as scratch:
            staging = Path(scratch)
            try:
                result = run_download_worker(url, staging, on_progress=on_progress, control=control,
                                             progress_range=progress_range, source_lang=source_lang)
                if not result.is_file() or result.stat().st_size == 0:
                    raise DownloadError("下载没有生成有效文件")
                if control:
                    control.wait_if_paused()
                target = dest_dir / "source.mp4"
                result.replace(target)
                return target
            except Exception:
                log = staging / "ytdlp.log"
                if log.is_file():
                    shutil.copy2(log, dest_dir / "ytdlp.log")
                worker_log = staging / "worker.log"
                if worker_log.is_file():
                    shutil.copy2(worker_log, dest_dir / "download-worker.log")
                raise
    finally:
        lock.release()


def _download_into(
    url: str, dest_dir: Path, *, on_progress: Callable[[str, float], None] | None = None,
    control: JobControl | None = None, progress_range: tuple[float, float] = (0.03, 0.20),
    source_lang: str = "",
) -> Path:
    if control:
        control.wait_if_paused()
    url = canonicalize_url(url)
    dest_dir.mkdir(parents=True, exist_ok=True)
    log_path = dest_dir / "ytdlp.log"
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise DownloadError("未安装 yt-dlp，请执行 pip install yt-dlp") from exc
    _patch_bilibili_original_audio()

    start, end = progress_range
    span = max(0.0, end - start)
    tracker = StreamProgress(expected=1)

    def emit(frac: float) -> None:
        if on_progress:
            on_progress("ingest", start + span * min(1.0, max(0.0, frac)))

    def hook(status: dict) -> None:
        if control:
            control.wait_if_paused()
        frac = tracker.feed(status)
        if frac is None:
            return
        emit(frac)

    def label_of(attempt: dict) -> object:
        return (
            attempt.get("clients")
            or attempt.get("cookiesfrombrowser")
            or attempt.get("cookiefile")
            or "default"
        )

    def build_opts(attempt: dict, *, fmt: str, with_hook: bool) -> dict:
        return ydl_options(
            dest_dir,
            url,
            hook=hook if with_hook else None,
            fmt=fmt,
            clients=attempt.get("clients"),
            cookiefile=attempt.get("cookiefile"),
            cookiesfrombrowser=attempt.get("cookiesfrombrowser"),
            impersonate=bool(attempt.get("impersonate", True)),
        )

    def extract_listing(attempt: dict) -> tuple[dict | None, int]:
        last_exc: Exception | None = None
        for fmt in (LIST_FORMAT, BEST_AV_FORMAT, "all"):
            if control:
                control.wait_if_paused()
            try:
                opts = build_opts(attempt, fmt=fmt, with_hook=False)
                with YoutubeDL(opts) as ydl:
                    if not hasattr(ydl, "extract_info"):
                        return None, 0
                    info = ydl.extract_info(url, download=False)
                if control:
                    control.wait_if_paused()
                return info, max_video_height(info)
            except JobStopped:
                raise
            except Exception as exc:
                last_exc = exc
                continue
        if last_exc:
            raise last_exc
        return None, 0

    last_error: Exception | None = None
    notes: list[str] = []
    best_path: Path | None = None
    best_height = -1
    listed_ceiling = 0
    attempts = list(download_attempts(url))
    if control:
        control.wait_if_paused()
    cookie_attempts = [item for item in attempts if item.get("cookiefile")]
    stale_cookie = False
    emit(0.02)

    for probe in listing_probes(attempts):
        if control:
            control.wait_if_paused()
        try:
            _info, height = extract_listing(probe)
        except JobStopped:
            raise
        except Exception as exc:
            notes.append(f"{label_of(probe)} list: {exc}")
            logger.warning("yt-dlp list %s failed: %s", label_of(probe), exc)
            if youtube_cookies_rejected(exc) and probe.get("cookiefile"):
                stale_cookie = True
            continue
        if height > listed_ceiling:
            listed_ceiling = height
        if listed_ceiling >= 2160:
            break

    if listed_ceiling:
        logger.info("highest listed format: %sp cookie=%s", listed_ceiling, bool(cookie_attempts))

    for attempt in attempts:
        if best_path is not None and listed_ceiling > 0 and best_height >= listed_ceiling:
            break
        if control:
            control.wait_if_paused()
        if stale_cookie and attempt.get("cookiefile"):
            continue
        if attempt.get("cookiefile"):
            logger.info("download with cookie file %s", Path(str(attempt["cookiefile"])).name)
        elif attempt.get("cookiesfrombrowser"):
            logger.info("download fallback: browser cookies %s", attempt["cookiesfrombrowser"])
        want = quality_target(listed_ceiling)
        fmt = format_for_height(want, source_lang)
        tracker.begin_attempt()
        # This is a private staging directory. A failed attempt must not leave
        # media that a later attempt can accidentally report as its own output.
        for path in dest_dir.glob("source.*"):
            if path.is_file():
                path.unlink()
        started = time.time()
        try:
            opts = build_opts(attempt, fmt=fmt, with_hook=True)
            def after_pp(status: dict) -> None:
                if control:
                    control.wait_if_paused()
                if tracker._last < 0.5:
                    return
                state = str(status.get("status") or "")
                if state == "started":
                    emit(0.97)
                elif state == "finished":
                    emit(0.99)

            opts["postprocessor_hooks"] = [after_pp]
            with YoutubeDL(opts) as ydl:
                if hasattr(ydl, "extract_info"):
                    try:
                        info = ydl.extract_info(url, download=False)
                        if control:
                            control.wait_if_paused()
                        listed_ceiling = max(listed_ceiling, max_video_height(info))
                        want = quality_target(listed_ceiling)
                        n = len((info or {}).get("requested_formats") or ()) or 1
                        tracker.set_expected(n)
                        ydl.params["format"] = prefer_audio_format(info, want, source_lang)
                        would = selected_height(info)
                        if would and would < HD_FLOOR:
                            raise DownloadError(f"该通道只有 {would}p，低于 {HD_FLOOR}p，已跳过")
                    except (DownloadError, JobStopped):
                        raise
                    except Exception as exc:
                        notes.append(f"{label_of(attempt)} list: {exc}")
                if control:
                    control.wait_if_paused()
                ydl.download([url])
                if control:
                    control.wait_if_paused()
        except JobStopped:
            raise
        except Exception as exc:
            last_error = exc
            notes.append(f"{label_of(attempt)}: {exc}")
            if youtube_cookies_rejected(exc) and attempt.get("cookiefile"):
                stale_cookie = True
            if isinstance(exc, DownloadError) and "已跳过" in str(exc):
                logger.info("skip low-res %s: %s", label_of(attempt), exc)
            elif attempt.get("cookiesfrombrowser"):
                logger.info("browser-cookie fallback %s failed: %s", label_of(attempt), exc)
            else:
                logger.warning("yt-dlp %s failed: %s", label_of(attempt), exc)
            continue
        picked = _picked_file(dest_dir, since=started)
        if not picked:
            last_error = DownloadError("下载完成但没有找到视频文件")
            notes.append(f"{label_of(attempt)}: missing file")
            continue
        try:
            picked = _ensure_mp4(picked, dest_dir, control=control)
        except JobStopped:
            raise
        except DownloadError as exc:
            last_error = exc
            notes.append(f"{label_of(attempt)}: {exc}")
            continue
        audio = _audio_status(picked)
        if audio is False:
            last_error = DownloadError("下载的文件没有音轨，正在改用备用格式")
            logger.warning("downloaded %s has no audio, retrying", picked)
            try:
                picked.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        height = _video_height(picked)
        want = quality_target(listed_ceiling)
        if height < HD_FLOOR:
            notes.append(f"{label_of(attempt)}: got {height}p < {HD_FLOOR}p")
            logger.warning("rejected %sp below HD floor %sp", height, HD_FLOOR)
            last_error = DownloadError(f"禁止保存低清晰度视频（{height}p < {HD_FLOOR}p）")
            try:
                picked.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        if height < want:
            notes.append(f"{label_of(attempt)}: got {height}p < listed {want}p")
            logger.info("keeping reachable %sp below listed %sp", height, want)
        if height > best_height:
            stash = dest_dir / f".best{picked.suffix.lower()}"
            if picked.resolve() != stash.resolve():
                shutil.copy2(picked, stash)
            best_path, best_height = stash, height
        if best_height >= want:
            break

    want = quality_target(listed_ceiling)
    if best_path and best_path.is_file() and (best_height >= want or best_height >= HD_FLOOR):
        if best_height < want:
            logger.warning("listed %sp unavailable; keeping reachable %sp", want, best_height)
        final = _ensure_mp4(best_path, dest_dir, control=control)
        try:
            best_path.unlink(missing_ok=True)
        except OSError:
            pass
        if on_progress:
            on_progress("ingest", end)
        return final
    if notes:
        log_path.write_text("\n".join(notes), encoding="utf-8")
    if is_youtube_url(url) and (
        stale_cookie or any("no longer valid" in note.lower() for note in notes)
    ) and (best_path is None or listed_ceiling == 0):
        raise DownloadError(
            explain_download_error(
                RuntimeError("The provided YouTube account cookies are no longer valid.")
            )
        ) from last_error
    if last_error and (best_path is None or listed_ceiling == 0):
        raise DownloadError(explain_download_error(last_error)) from last_error
    raise DownloadError(f"无法下载最高清（{want}p），已禁止保存低清晰度视频。")
