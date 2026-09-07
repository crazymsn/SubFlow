from unittest.mock import Mock

import pytest

from bilingual_sub.adapters import meding, system_proxy


@pytest.fixture
def desktop_proxy(monkeypatch):
    monkeypatch.setattr(system_proxy.sys, 'platform', 'darwin')
    monkeypatch.setattr(system_proxy, 'getproxies_environment', lambda: {})
    monkeypatch.setattr(system_proxy, 'proxy_bypass', lambda host: False)
    monkeypatch.setattr(system_proxy, 'getproxies', lambda: {'https': 'http://127.0.0.1:1082'})


def test_api_client_uses_native_proxy(desktop_proxy, monkeypatch):
    sdk, transport = Mock(), Mock()
    monkeypatch.setattr(meding, 'OpenAI', sdk)
    monkeypatch.setattr(meding, 'DefaultHttpxClient', transport)
    meding.OpenAIMedingClient('test')
    transport.assert_called_once_with(proxy='http://127.0.0.1:1082')
    assert sdk.call_args.kwargs['http_client'] is transport.return_value
    assert sdk.call_args.kwargs['base_url'] == 'https://api.meding.site/v1'


@pytest.mark.parametrize('environment', [{'https': 'http://explicit:8080'}, {'no': '*'}])
def test_explicit_proxy_and_bypass_are_not_overridden(desktop_proxy, monkeypatch, environment):
    monkeypatch.setattr(system_proxy, 'getproxies_environment', lambda: environment)
    assert system_proxy.macos_proxy('https://api.meding.site') is None


def test_native_bypass_is_respected(desktop_proxy, monkeypatch):
    monkeypatch.setattr(system_proxy, 'proxy_bypass', lambda host: host == 'api.meding.site')
    assert system_proxy.macos_proxy('https://api.meding.site') is None


def test_other_platforms_keep_existing_proxy_behavior(desktop_proxy, monkeypatch):
    monkeypatch.setattr(system_proxy.sys, 'platform', 'win32')
    assert system_proxy.macos_proxy('https://api.meding.site') is None


@pytest.mark.parametrize('host,local', [('localhost', True), ('127.0.0.1', True),
    ('127.0.0.2', True), ('[::1]', True), ('localhost.example.org', False),
    ('192.168.1.2', False), ('api.meding.site', False)])
def test_media_proxy_only_bypasses_literal_loopback(tmp_path, host, local):
    from bilingual_sub.adapters.ytdlp import ydl_options

    options = ydl_options(tmp_path, f'http://{host}:8000/video.mp4', impersonate=False)
    assert ('proxy' in options) == local
    if local:
        assert options['proxy'] == ''
