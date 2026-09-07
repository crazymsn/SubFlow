"""Use the user's native macOS proxy when no environment proxy is set."""
import ipaddress
import sys
from urllib.parse import urlsplit
from urllib.request import getproxies, getproxies_environment, proxy_bypass


def macos_proxy(url: str) -> str | None:
    # HTTPX already honors environment proxies and NO_PROXY. Explicit settings
    # take precedence; do not replace them with the desktop configuration.
    if sys.platform != 'darwin' or getproxies_environment():
        return None
    parsed = urlsplit(url)
    if not parsed.hostname or proxy_bypass(parsed.hostname):
        return None
    proxies = getproxies()
    return proxies.get(parsed.scheme) or proxies.get('all')


def is_loopback_url(url: str) -> bool:
    host = urlsplit(url).hostname or ''
    if host.casefold().rstrip('.') == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
