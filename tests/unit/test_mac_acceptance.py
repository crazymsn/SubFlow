import json
import plistlib
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

from bilingual_sub._data.bootstrap import mac_acceptance as audit

ROOT = Path(__file__).parents[2]


@pytest.fixture
def app_bundle(tmp_path, monkeypatch):
    app = tmp_path / 'SubFlow.app'
    root = app / 'Contents/Resources/offline'
    root.mkdir(parents=True)
    data = {'schema': 1, 'platform': 'darwin', 'machine': 'arm64', 'runtimes': {},
            'models': {'gptsovits': {'path': 'models/sovits'}}}
    for kind in audit.KINDS:
        path = root / 'runtimes' / kind / 'bin/python3'
        path.parent.mkdir(parents=True)
        path.touch()
        data['runtimes'][kind] = {'python': path.relative_to(root).as_posix(), 'backend': 'mps'}
    (root / 'bundle.json').write_text(json.dumps(data))
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString': 'test'}))
    monkeypatch.setattr(audit.platform, 'machine', lambda: 'arm64')
    return app, root, data


def test_mps_failure_writes_evidence_and_does_not_pass(app_bundle, tmp_path, monkeypatch):
    def run(args, **kwargs):
        assert '-B' in args and '-I' in args
        assert kwargs['env']['SUBFLOW_AUTO_INSTALL'] == '0'
        assert kwargs['env']['HF_HUB_OFFLINE'] == '1'
        return SimpleNamespace(returncode=1, stdout='', stderr='MPS out of memory')
    monkeypatch.setattr(audit.subprocess, 'run', run)
    output = tmp_path / 'evidence'
    report = audit.run_checks(app_bundle[0], output, 'mps')
    assert not report['ok'] and not report['gpu_components_verified']
    assert len(report['runtimes']) == 4
    assert 'MPS out of memory' in (output / 'qwentts.log').read_text()
    assert json.loads((output / 'report.json').read_text())['product_acceptance'] == 'pending_manual_tests'


def test_cpu_check_does_not_claim_gpu_or_overwrite_evidence(app_bundle, tmp_path, monkeypatch):
    def run(args, **kwargs):
        kind = args[args.index('--worker') + 1]
        return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps(
            {'kind': kind, 'machine': 'arm64', 'device': 'cpu', 'checks': ['matmul'], 'ok': True}))
    monkeypatch.setattr(audit.subprocess, 'run', run)
    output = tmp_path / 'evidence'
    report = audit.run_checks(app_bundle[0], output, 'cpu')
    assert report['ok'] and not report['gpu_components_verified']
    previous = (output / 'report.json').read_bytes()
    with pytest.raises(FileExistsError):
        audit.run_checks(app_bundle[0], output, 'cpu')
    assert (output / 'report.json').read_bytes() == previous
    report = audit.run_checks(app_bundle[0], tmp_path / 'gpu-evidence', 'mps')
    assert not report['ok'] and not report['gpu_components_verified']


def test_cold_start_timeout_preserves_partial_diagnostics(app_bundle, tmp_path, monkeypatch):
    def run(args, **kwargs):
        assert kwargs['timeout'] == 321
        raise audit.subprocess.TimeoutExpired(args, 321, output=b'loading model', stderr=b'cold import')
    monkeypatch.setattr(audit.subprocess, 'run', run)
    output = tmp_path / 'evidence'
    report = audit.run_checks(app_bundle[0], output, 'mps', timeout=321)
    assert not report['ok']
    assert report['worker_timeout_seconds'] == 321
    assert (output / 'qwentts.log').read_text() == 'loading model\ncold import'
    assert all('321s' in item['error'] for item in report['runtimes'])


def test_app_and_external_paths_are_protected(app_bundle, tmp_path, monkeypatch):
    app, root, data = app_bundle
    with pytest.raises(ValueError, match='outside'):
        audit.run_checks(app, app / 'evidence', 'auto')
    data['runtimes']['qwentts']['python'] = '../../../../external/python'
    (root / 'bundle.json').write_text(json.dumps(data))
    monkeypatch.setattr(audit.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stdout='', stderr='unavailable'))
    report = audit.run_checks(app, tmp_path / 'evidence', 'auto')
    qwen = next(item for item in report['runtimes'] if item['kind'] == 'qwentts')
    assert not qwen['ok'] and 'escapes' in qwen['error']


@pytest.mark.parametrize('machine,backend,valid', [('arm64', 'mps', True), ('arm64', 'cpu', False),
                                                ('x86_64', 'cpu', True), ('x86_64', 'mps', False)])
def test_mac_package_requires_native_backend(monkeypatch, machine, backend, valid):
    module = runpy.run_path(str(ROOT / 'scripts/bundle-offline.py'))
    monkeypatch.setattr(module['sys'], 'platform', 'darwin')
    monkeypatch.setattr(module['platform'], 'machine', lambda: machine)
    if valid:
        module['validate_release_backend'](backend)
    else:
        with pytest.raises(RuntimeError, match='require'):
            module['validate_release_backend'](backend)


@pytest.mark.parametrize('requested,actual,valid', [('mps', 'cpu', False), ('mps', 'mps', True),
                                                ('cuda', 'cpu', False), ('cuda', 'cuda:0', True)])
def test_synthesis_gpu_acceptance_rejects_cpu_fallback(requested, actual, valid):
    module = runpy.run_path(str(ROOT / 'scripts/check-offline-voices.py'))
    if valid:
        module['verify_device'](actual, requested)
    else:
        with pytest.raises(RuntimeError, match='acceptance failed'):
            module['verify_device'](actual, requested)


@pytest.mark.parametrize('magic', [bytes.fromhex('cafebabf'), bytes.fromhex('bfbafeca')])
def test_signs_and_verifies_fat64_native_binaries(tmp_path, monkeypatch, magic):
    module = runpy.run_path(str(ROOT / 'scripts/sign-offline-macos.py'))
    monkeypatch.setattr(module['sys'], 'platform', 'darwin')
    binary = tmp_path / 'native.dylib'
    binary.write_bytes(magic + b'payload')
    (tmp_path / 'readme.txt').write_text('text')
    calls = []
    monkeypatch.setattr(module['subprocess'], 'run', lambda args, **kwargs: calls.append((args, kwargs)))
    module['sign'](tmp_path)
    assert calls == [(['codesign', '--force', '--sign', '-', str(binary)], {'check': True}),
                     (['codesign', '--verify', str(binary)], {'check': True})]


def test_reusing_bundle_rejects_wrong_architecture_and_legacy_missing_asr(app_bundle, monkeypatch):
    module = runpy.run_path(str(ROOT / 'scripts/bundle-offline.py'))
    monkeypatch.setattr(module['sys'], 'platform', 'darwin')
    _, root, data = app_bundle
    for kind in ('qwen-native', 'qwen-clone', 'gptsovits'):
        path = root / 'models' / kind
        path.mkdir(parents=True)
        data['models'][kind] = {'path': path.relative_to(root).as_posix()}
    data['recognition_runtimes'] = True
    def write():
        (root / 'bundle.json').write_text(json.dumps(data))
    write()
    module['validate_reusable_bundle'](root, 'mps')
    data['machine'] = 'x86_64'
    write()
    with pytest.raises(RuntimeError, match='architecture'):
        module['validate_reusable_bundle'](root, 'mps')
    data['machine'] = 'arm64'
    data['recognition_runtimes'] = False
    write()
    with pytest.raises(RuntimeError, match='recognition runtimes'):
        module['validate_reusable_bundle'](root, 'mps')
    data['recognition_runtimes'] = True
    del data['runtimes']['whisperx']
    write()
    with pytest.raises(RuntimeError, match='whisperx'):
        module['validate_reusable_bundle'](root, 'mps')


def test_reused_payload_refreshes_source_and_hashes_without_modifying_original(tmp_path, monkeypatch):
    import hashlib
    import os

    module = runpy.run_path(str(ROOT / 'scripts/bundle-offline.py'))
    checkout = tmp_path / 'checkout'
    source = checkout / 'third_party/GPT-SoVITS/api_v2.py'
    source.parent.mkdir(parents=True)
    source.write_text('new inference fix')
    original = tmp_path / 'original.py'
    original.write_text('old code')
    root = tmp_path / 'bundle'
    home = root / 'models/GPT-SoVITS'
    home.mkdir(parents=True)
    os.link(original, home / 'api_v2.py')
    weights = home / 'weights.pth'
    weights.write_bytes(b'weights')
    data = {'models': {'gptsovits': {'path': 'models/GPT-SoVITS', 'files': {'weights.pth': {'unchanged': True}}}}}
    refresh = module['refresh_sovits_sources']
    monkeypatch.setitem(refresh.__globals__, 'ROOT', checkout)
    monkeypatch.setattr(module['subprocess'], 'run', lambda *a, **k: SimpleNamespace(
        stdout=b'third_party/GPT-SoVITS/api_v2.py\0'))
    refresh(root, data)
    assert original.read_text() == 'old code'
    assert (home / 'api_v2.py').read_text() == 'new inference fix'
    assert weights.read_bytes() == b'weights'
    assert data['models']['gptsovits']['files']['api_v2.py']['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert data['models']['gptsovits']['files']['weights.pth'] == {'unchanged': True}
