import zipfile
from pathlib import Path

import pytest
from filelock import FileLock

from bilingual_sub.adapters import runtime_bootstrap as rt
from bilingual_sub.core.control import JobControl, JobStopped


def test_install_isolated_and_cached(monkeypatch, tmp_path):
    monkeypatch.setenv('SUBFLOW_RUNTIME_DIR', str(tmp_path))
    monkeypatch.setenv('SUBFLOW_AUTO_INSTALL', '1')
    monkeypatch.setenv('SUBFLOW_TORCH_BACKEND', 'cpu')
    monkeypatch.setattr(rt, 'find_uv', lambda: Path('uv'))
    calls = []

    def run(args, *_a, **_k):
        calls.append(args)
        if args[1] == 'venv':
            py = rt.managed_python('asr')
            py.parent.mkdir(parents=True)
            py.touch()

    monkeypatch.setattr(rt, '_run', run)
    py = rt.ensure_python_env('asr')
    assert py.is_file()
    assert any('--managed-python' in c for c in calls)
    assert any('torch==2.5.1' in c or 'torch==2.2.2' in c for c in calls)
    before = len(calls)
    assert rt.ensure_python_env('asr') == py
    assert len(calls) == before
    (py.parent.parent / '.subflow-ready').write_text('outdated')
    rt.ensure_python_env('asr')
    assert len(calls) > before


def test_disabled_installer_never_spawns(monkeypatch, tmp_path):
    monkeypatch.setenv('SUBFLOW_RUNTIME_DIR', str(tmp_path))
    monkeypatch.setenv('SUBFLOW_AUTO_INSTALL', '0')
    monkeypatch.setattr(rt, '_run', lambda *_a, **_k: pytest.fail('must not spawn'))
    with pytest.raises(RuntimeError, match='SUBFLOW_AUTO_INSTALL=0'):
        rt.ensure_python_env('asr')


def test_cancel_before_install(monkeypatch, tmp_path):
    monkeypatch.setenv('SUBFLOW_RUNTIME_DIR', str(tmp_path))
    control = JobControl()
    control.stop()
    with pytest.raises(JobStopped):
        rt.ensure_python_env('asr', control=control)


def test_lock_released_on_failure(tmp_path):
    path = tmp_path / 'install.lock'
    with pytest.raises(ValueError), rt._locked(path, None):
        raise ValueError('failed')
    with FileLock(str(path), timeout=0):
        pass


def test_external_audio_env_uses_bundled_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setenv('PYTHONPATH', 'foreign-python')
    monkeypatch.setenv('PYTHONHOME', 'foreign-home')
    binary = tmp_path / 'ffmpeg'
    monkeypatch.setattr('bilingual_sub.adapters.ffmpeg.find_ffmpeg', lambda: str(binary))
    env = rt.inference_env()
    assert 'PYTHONPATH' not in env and 'PYTHONHOME' not in env
    assert env['PATH'].startswith(str(tmp_path))


def test_assets_reject_zip_traversal(tmp_path):
    from bilingual_sub._data.bootstrap.download_assets import unpack
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as zf:
        zf.writestr('../escape.txt', 'unsafe')
    with pytest.raises(ValueError, match='Unsafe'):
        unpack(archive, tmp_path / 'models')
    assert not (tmp_path / 'escape.txt').exists()
