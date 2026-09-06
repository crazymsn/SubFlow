"""Standard/design voice startup must prepare both local model homes."""
from pathlib import Path

import pytest

from bilingual_sub.adapters.tts import qwen_runtime as qr
from bilingual_sub.adapters.tts.base import TtsUnavailable


def test_missing_design_model_respects_disabled_install(monkeypatch, tmp_path):
    monkeypatch.setattr(qr, 'runtime_root', lambda: tmp_path)
    monkeypatch.setattr(qr, 'probe_endpoint', lambda *a, **k: False)
    monkeypatch.setattr(qr, 'ensure_python_env', lambda *a, **k: Path('python'))
    monkeypatch.setattr('bilingual_sub.adapters.offline_bundle.model_home', lambda *a, **k: None)
    monkeypatch.setattr('bilingual_sub._data.bootstrap.download_qwen.ready', lambda home, spec=None: spec is not None)
    monkeypatch.setattr(qr, 'auto_install_enabled', lambda: False)
    monkeypatch.setattr(qr, '_run', lambda *a, **k: pytest.fail('Offline mode must not install'))
    with pytest.raises(TtsUnavailable, match='Base.*自动安装已关闭'):
        qr.ensure_running('http://127.0.0.1:19882', native=True)


def test_native_starts_with_verified_bundled_clone_path(monkeypatch, tmp_path):
    from contextlib import contextmanager

    calls = []
    probes = iter((False, False, True))
    monkeypatch.setattr(qr, 'runtime_root', lambda: tmp_path)
    monkeypatch.setattr(qr, 'probe_endpoint', lambda *a, **k: next(probes))
    monkeypatch.setattr(qr, 'ensure_python_env', lambda *a, **k: Path('python'))
    def bundled(name, **kwargs):
        assert kwargs['verify'] is True
        return tmp_path / name
    monkeypatch.setattr('bilingual_sub.adapters.offline_bundle.model_home', bundled)
    monkeypatch.setattr(qr, '_run', lambda *a, **k: pytest.fail('Complete bundle must not download'))
    @contextmanager
    def process(command, **kwargs):
        calls.append(command)
        yield type('Process', (), {'poll': lambda self: None})()
    monkeypatch.setattr(qr, 'owned_process', process)
    assert qr.ensure_running('http://127.0.0.1:19882', native=True) == 'started'
    command = calls[0]
    assert command[command.index('--model') + 1] == str(tmp_path / 'qwen-native')
    assert command[command.index('--clone-model') + 1] == str(tmp_path / 'qwen-clone')
