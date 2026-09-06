import hashlib
import json
import os
import platform
import sys

import pytest

from bilingual_sub.adapters import offline_bundle as bundle
from bilingual_sub.adapters import runtime_bootstrap as rt


@pytest.fixture
def payload(tmp_path, monkeypatch):
    root = tmp_path / 'complete client' / 'offline'
    python = root / 'runtimes' / 'python.exe'
    python.parent.mkdir(parents=True)
    python.write_bytes(b'python placeholder')
    home = root / 'models' / 'qwen'
    home.mkdir(parents=True)
    model = home / 'model.safetensors'
    model.write_bytes(b'model-data')
    data = {'schema': 1, 'platform': sys.platform, 'machine': platform.machine(),
            'runtimes': {kind: {'python': 'runtimes/python.exe', 'backend': 'cuda', 'torch': '2.5.1+cu124'}
                         for kind in ('qwentts', 'gptsovits')},
            'models': {'qwen-native': {'path': 'models/qwen', 'files': {
                'model.safetensors': {'size': 10, 'sha256': hashlib.sha256(b'model-data').hexdigest()}}}}}
    (root / 'bundle.json').write_text(json.dumps(data))
    monkeypatch.setenv('SUBFLOW_OFFLINE_DIR', str(root))
    monkeypatch.setenv('SUBFLOW_RUNTIME_DIR', str(tmp_path / 'blank-profile'))
    monkeypatch.setenv('SUBFLOW_AUTO_INSTALL', '0')
    return root, data


def test_no_gpu_reuses_bundled_cuda_environment(payload, monkeypatch):
    monkeypatch.setenv('SUBFLOW_TORCH_BACKEND', 'cpu')
    calls = []
    monkeypatch.setattr(rt, '_run', lambda args, *a, **kw: calls.append(args))
    monkeypatch.setattr(rt, 'inference_env', lambda: {})
    monkeypatch.setattr(rt, 'find_uv', lambda **kw: pytest.fail('offline build attempted installation'))
    python = rt.ensure_python_env('qwentts')
    assert python.is_relative_to(payload[0])
    assert '2.5.1+cu124' in calls[0][2]
    assert "torch.version.cuda != '12.4'" in calls[0][2]


@pytest.mark.parametrize('kind', ['asr', 'whisperx'])
def test_recognition_payload_and_legacy_voice_only_compatibility(payload, kind):
    root, data = payload
    assert bundle.runtime(kind, 'cpu') is None
    data['recognition_runtimes'] = True
    (root / 'bundle.json').write_text(json.dumps(data))
    with pytest.raises(RuntimeError, match=kind):
        bundle.runtime(kind, 'cpu')
    data['runtimes'][kind] = data['runtimes']['qwentts'].copy()
    (root / 'bundle.json').write_text(json.dumps(data))
    assert bundle.runtime(kind, 'cpu')[0] == root / 'runtimes/python.exe'


def test_relocated_and_retimestamped_models_work_offline(payload, monkeypatch):
    root, _ = payload
    model = root / 'models/qwen/model.safetensors'
    os.utime(model, (100, 100))  # ZIP extraction changed the original nanoseconds.
    moved = root.parent.parent / 'moved client'
    root.parent.rename(moved)
    monkeypatch.setenv('SUBFLOW_OFFLINE_DIR', str(moved / 'offline'))
    assert bundle.model_home('qwen-native', verify=True) == moved / 'offline/models/qwen'
    assert not list((moved / 'offline').rglob('*.ok'))  # All caches outside the app.


def test_same_size_corruption_is_rejected_after_validation(payload):
    root, _ = payload
    bundle.model_home('qwen-native', verify=True)
    (root / 'models/qwen/model.safetensors').write_bytes(b'wrong-data')
    with pytest.raises(RuntimeError, match='损坏'):
        bundle.model_home('qwen-native', verify=True)


@pytest.mark.parametrize('change', ['missing_python', 'wrong_machine', 'missing_model', 'traversal'])
def test_broken_complete_payload_never_falls_back_to_download(payload, change):
    root, data = payload
    if change == 'missing_python':
        (root / 'runtimes/python.exe').unlink()
    elif change == 'wrong_machine':
        data['machine'] = 'unsupported-chip'
    elif change == 'missing_model':
        (root / 'models/qwen/model.safetensors').unlink()
    else:
        data['models']['qwen-native']['path'] = '../../../outside'
    (root / 'bundle.json').write_text(json.dumps(data))
    with pytest.raises(RuntimeError):
        if change in {'missing_python', 'wrong_machine'}:
            bundle.runtime('qwentts', 'cpu')
        else:
            bundle.model_home('qwen-native', verify=True)


def test_explicit_gpt_python_override_remains_supported(payload, monkeypatch, tmp_path):
    from bilingual_sub.adapters.tts.gptsovits_runtime import find_sovits_python

    custom = tmp_path / 'custom.exe'
    custom.touch()
    monkeypatch.setenv('SUBFLOW_GPTSOVITS_PYTHON', str(custom))
    assert find_sovits_python() == custom


def test_native_apple_payload_supports_cpu_fallback(payload, monkeypatch):
    root, data = payload
    monkeypatch.setattr(bundle.sys, 'platform', 'darwin')
    monkeypatch.setattr(bundle.platform, 'machine', lambda: 'arm64')
    data['machine'], data['platform'] = 'aarch64', 'darwin'
    data['runtimes']['qwentts']['backend'] = 'mps'
    (root / 'bundle.json').write_text(json.dumps(data))
    assert bundle.runtime('qwentts', 'cpu')[2] == 'mps'
    assert bundle.runtime('qwentts', 'mps')[2] == 'mps'


def test_nltk_archives_have_the_paths_checked_by_g2p_en(tmp_path):
    import runpy
    import zipfile
    from pathlib import Path

    build = runpy.run_path(str(Path(__file__).parents[2] / 'scripts/bundle-offline.py'))
    for folder in ('taggers/averaged_perceptron_tagger', 'corpora/cmudict'):
        path = tmp_path / 'nltk_data' / folder
        path.mkdir(parents=True)
        (path / 'dictionary').write_bytes(b'data')
    build['nltk_compatibility'](tmp_path)
    with zipfile.ZipFile(tmp_path / 'nltk_data/corpora/cmudict.zip') as archive:
        assert archive.read('cmudict/dictionary') == b'data'


def test_hardlinked_bundles_keep_nltk_corpora_independent_even_when_reused(tmp_path):
    import runpy
    from pathlib import Path

    build = runpy.run_path(str(Path(__file__).parents[2] / 'scripts/bundle-offline.py'))
    source = tmp_path / 'source'
    relative = Path('models/GPT-SoVITS/nltk_data/corpora/cmudict/cmudict')
    dictionary = source / relative
    dictionary.parent.mkdir(parents=True)
    content = b'A 1 AH0\n' * 150000  # Exceeds the model hardlink threshold.
    dictionary.write_bytes(content)
    first, reused = tmp_path / 'first', tmp_path / 'reused'
    build['copy_tree'](source, first, hardlink=True)
    build['copy_tree'](first, reused, hardlink=True)
    for root in (source, first, reused):
        member = root / relative
        assert member.stat().st_nlink == 1  # Required by NLTK's secure corpus reader.
        assert member.read_bytes() == content
    assert not dictionary.samefile(first / relative)
    assert not (first / relative).samefile(reused / relative)


@pytest.mark.parametrize('installed', [True, False])
def test_korean_frontend_never_calls_upstream_installer(monkeypatch, installed):
    import ast
    from pathlib import Path
    from types import SimpleNamespace

    source = Path(__file__).parents[2] / 'third_party/GPT-SoVITS/GPT_SoVITS/text/korean.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    definition = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'G2p')
    class Base:
        def __init__(self):
            self.check_mecab()
            self.mecab = self.get_mecab()
        def check_mecab(self):
            pytest.fail('upstream attempted a pip install')
    dictionary = object()
    monkeypatch.setitem(sys.modules, 'mecab', SimpleNamespace(MeCab=lambda: dictionary) if installed else None)
    namespace = {'_BaseG2p': Base}
    exec(compile(ast.Module(body=[definition], type_ignores=[]), str(source), 'exec'), namespace)
    if installed:
        assert namespace['G2p']().mecab is dictionary
    else:
        with pytest.raises(RuntimeError, match='Korean dictionary missing'):
            namespace['G2p']()
