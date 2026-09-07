"""Build all three offline voices with real, relocatable CPython interpreters.

Run on the target OS/architecture. --hardlink saves build-host disk space;
the resulting directory contains ordinary files and can be archived normally.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def validate_release_backend(backend):
    machine = platform.machine().lower()
    if sys.platform == 'win32' and backend != 'cuda':
        raise RuntimeError('Full Windows releases require --backend cuda (also supports CPU inference)')
    if sys.platform == 'darwin':
        expected = 'mps' if machine in {'arm64', 'aarch64'} else 'cpu'
        if machine not in {'arm64', 'aarch64', 'x86_64', 'amd64'} or backend != expected:
            raise RuntimeError(f'Full macOS {machine} releases require --backend {expected}; Apple MPS wheels also support CPU')


def validate_reusable_bundle(source, backend=None):
    data = json.loads((source / 'bundle.json').read_text(encoding='utf-8'))
    if (data.get('schema') != 1 or data.get('platform') != sys.platform
            or data.get('machine', '').lower() != platform.machine().lower()):
        raise RuntimeError('Reusable bundle must match the target system and architecture')
    if data.get('recognition_runtimes') is not True:
        raise RuntimeError('Reusable full bundle must include both recognition runtimes')
    backend = backend or data['runtimes']['qwentts']['backend']
    validate_release_backend(backend)
    def member(relative):
        path = (source / relative).resolve()
        if not path.is_relative_to(source.resolve()):
            raise RuntimeError('Reusable bundle path escapes its directory')
        return path
    for kind in ('qwentts', 'gptsovits', 'asr', 'whisperx'):
        record = data['runtimes'].get(kind, {})
        if record.get('backend') != backend or not member(record.get('python', '')).is_file():
            raise RuntimeError(f'Reusable bundle has a missing or incompatible {kind} runtime')
    for kind in ('qwen-native', 'qwen-clone', 'gptsovits'):
        record = data['models'].get(kind, {})
        if not record.get('path') or not member(record['path']).is_dir():
            raise RuntimeError(f'Reusable bundle has a missing {kind} model directory')


def copy_file(source, target, *, hardlink=False):
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if source.samefile(target):
            return str(target)
        raise FileExistsError(f'Use an empty staging directory: {target}')
    # NLTK's path security rejects multiply-linked corpus files, even inside the
    # bundle. Keep dictionaries independent in both new and reused payloads.
    corpus = any(part.casefold() == 'nltk_data' for part in target.parts)
    if hardlink and not corpus and source.stat().st_size >= 1024 * 1024:
        try:
            os.link(source, target)
            return str(target)
        except OSError:
            pass
    return shutil.copy2(source, target)


def copy_tree(source, target, *, hardlink=False, ignore=None):
    # Dereference links into standalone files. Python base executables/libraries
    # must never retain links to the build host's uv directory.
    return shutil.copytree(source, target, dirs_exist_ok=True, ignore=ignore,
        copy_function=lambda s, d: copy_file(s, d, hardlink=hardlink))


def run(python, code, **kwargs):
    from bilingual_sub.adapters.runtime_bootstrap import inference_env

    result = subprocess.run([str(python), '-c', code], check=True, capture_output=True,
        text=True, encoding='utf-8', env=inference_env(), timeout=240, **kwargs)
    return result.stdout.strip()


def portable_python(python, dest, backend, kind, hardlink):
    from bilingual_sub.adapters.runtime_bootstrap import _runtime_probe

    info = json.loads(run(python, "import sys,sysconfig,json,torch;print(json.dumps([sys.base_prefix,sysconfig.get_path('purelib'),str(torch.__version__)]))"))
    base, packages, wheel = Path(info[0]), Path(info[1]), info[2]
    relative_packages = packages.relative_to(python.parent.parent)
    # A venv launcher alone contains an absolute dependency on sys.base_prefix.
    # uv's managed CPython distribution is relocatable; copy its actual base.
    if not (base / 'LICENSE.txt').exists() and not list(base.glob('**/LICENSE*')):
        raise RuntimeError(f'Python distribution is missing its license: {base}')
    copy_tree(base, dest, hardlink=hardlink,
        ignore=shutil.ignore_patterns('site-packages', '__pycache__', '*.pyc'))
    copy_tree(packages, dest / relative_packages, hardlink=hardlink,
        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.egg-link', '__editable__*'))
    executable = dest / ('python.exe' if os.name == 'nt' else 'bin/python3')
    extra = '\nfrom mecab import MeCab; assert MeCab().pos("안녕하세요")' if kind == 'gptsovits' else ''
    output = run(executable, _runtime_probe(kind, wheel, backend) + extra + '\nprint("PORTABLE_IMPORT_OK")', cwd=dest)
    print(f'{kind}: {output}', flush=True)
    return {'python': executable, 'torch': wheel, 'backend': backend}


def inventory(home):
    result = {}
    for path in sorted(home.rglob('*')):
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                digest.update(block)
        result[path.relative_to(home).as_posix()] = {'size': path.stat().st_size, 'sha256': digest.hexdigest()}
    return result


def refresh_sovits_sources(root, data):
    """Reuse weights/interpreters, but ship this checkout's inference fixes."""
    source = ROOT / 'third_party/GPT-SoVITS'
    home = (root / data['models']['gptsovits']['path']).resolve()
    if not home.is_relative_to(root.resolve()):
        raise RuntimeError('Reusable GPT-SoVITS path escapes its directory')
    tracked = subprocess.run(['git', 'ls-files', '-z', 'third_party/GPT-SoVITS'], cwd=ROOT,
        capture_output=True, check=True).stdout.decode('utf-8').split('\0')
    if not any(p.endswith('/api_v2.py') for p in tracked):
        raise RuntimeError('The vendored GPT-SoVITS source must be tracked in Git')
    for relative in filter(None, tracked):
        item = ROOT / relative
        name = item.relative_to(source)
        target = home / name
        target.parent.mkdir(parents=True, exist_ok=True)
        # A reused hardlink must not rewrite the source bundle.
        target.unlink(missing_ok=True)
        shutil.copy2(item, target)
        content = target.read_bytes()
        data['models']['gptsovits']['files'][name.as_posix()] = {
            'size': len(content), 'sha256': hashlib.sha256(content).hexdigest(),
        }


def nltk_compatibility(home):
    # g2p-en checks the .zip names at import time, even when NLTK can read the
    # extracted directories. Ship valid archives as well to avoid its downloader.
    for relative in ('taggers/averaged_perceptron_tagger', 'corpora/cmudict'):
        directory = home / 'nltk_data' / relative
        archive = directory.with_suffix('.zip')
        if not directory.is_dir():
            raise RuntimeError(f'Missing required NLTK dictionary: {directory}')
        if not archive.exists():
            with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as output:
                for item in sorted(directory.rglob('*')):
                    if item.is_file():
                        output.write(item, item.relative_to(directory.parent).as_posix())


def bundle(dest, *, hardlink=False):
    from bilingual_sub.__version__ import __version__
    from bilingual_sub._data.bootstrap import download_qwen
    from bilingual_sub.adapters import runtime_bootstrap as rt
    from bilingual_sub.adapters.tts import gptsovits_runtime as sovits

    dest = dest.resolve()
    if dest.exists() and any(dest.iterdir()):
        raise RuntimeError('Build into a new, empty offline staging directory')
    if os.environ.get('SUBFLOW_OFFLINE_DIR'):
        raise RuntimeError('Unset SUBFLOW_OFFLINE_DIR when assembling a release')
    backend = rt.torch_backend()
    validate_release_backend(backend)
    if os.environ.get('SUBFLOW_GPTSOVITS_CONFIG'):
        raise RuntimeError('Unset custom GPT-SoVITS model configuration before building')
    dest.mkdir(parents=True, exist_ok=True)
    data = {'schema': 1, 'version': __version__, 'platform': sys.platform,
            'machine': platform.machine(), 'runtimes': {}, 'models': {}}
    data['recognition_runtimes'] = True
    for kind in ('qwentts', 'gptsovits', 'asr', 'whisperx'):
        print(f'Preparing {kind} runtime…', flush=True)
        python = rt.ensure_python_env(kind, progress=lambda s: print(s, flush=True))
        record = portable_python(python, dest / 'runtimes' / kind, backend, kind, hardlink)
        record['python'] = record['python'].relative_to(dest).as_posix()
        data['runtimes'][kind] = record
    qpython = dest / data['runtimes']['qwentts']['python']
    qlicense = Path(run(qpython, "import importlib.metadata;d=importlib.metadata.distribution('qwen-tts');print(d.locate_file(next(f for f in d.files if str(f).endswith('/licenses/LICENSE'))))"))
    copy_file(qlicense, dest / 'licenses' / 'Qwen3-TTS-APACHE-2.0.txt')
    copy_file(ROOT / 'NOTICE', dest / 'licenses' / 'SubFlow-NOTICE.txt')
    copy_file(ROOT / 'LICENSE', dest / 'licenses' / 'SubFlow-LICENSE.txt')
    for native in (True, False):
        name = 'qwen-native' if native else 'qwen-clone'
        spec_file = rt.bootstrap_assets() / ('qwen-native-model.json' if native else 'qwen-model.json')
        spec = json.loads(spec_file.read_text(encoding='utf-8'))
        source = rt.runtime_root() / ('qwen3-native-0.6b' if native else 'qwen3-tts-0.6b')
        print(f'Preparing {name} models…', flush=True)
        subprocess.run([str(qpython), str(rt.bootstrap_assets() / 'download_qwen.py'), str(source),
            *(['--native'] if native else [])], check=True, env=rt.inference_env())
        home = dest / 'models' / name
        for relative in spec['files']:
            copy_file(source / relative, home / relative, hardlink=hardlink)
        copy_file(source / download_qwen.MARKER, home / download_qwen.MARKER)
        data['models'][name] = {'path': home.relative_to(dest).as_posix(),
            'repo': spec['repo'], 'revision': spec['revision'], 'files': inventory(home)}
    source = ROOT / 'third_party' / 'GPT-SoVITS'
    if sovits.missing_pretrained(source):
        source = rt.ensure_sovits_runtime(progress=lambda s: print(s, flush=True))
    home = dest / 'models' / 'GPT-SoVITS'
    # Only tracked upstream source, never developer recordings, logs or configs.
    tracked = subprocess.run(['git', 'ls-files', '-z', 'third_party/GPT-SoVITS'], cwd=ROOT,
        capture_output=True, check=True).stdout.decode('utf-8').split('\0')
    if not any(p.endswith('/api_v2.py') for p in tracked):
        raise RuntimeError('The vendored GPT-SoVITS source must be tracked in Git')
    for relative in filter(None, tracked):
        item = ROOT / relative
        copy_file(item, home / item.relative_to(ROOT / 'third_party' / 'GPT-SoVITS'))
    config = sovits.runtime_config(source)
    if config['version'] != 'v2':
        raise RuntimeError('Offline release requires the validated GPT-SoVITS v2 weight pair')
    for key in ('t2s_weights_path', 'vits_weights_path', 'bert_base_path', 'cnhuhbert_base_path'):
        item = Path(config[key])
        target = home / item.relative_to(source)
        if item.is_dir():
            copy_tree(item, target, hardlink=hardlink, ignore=shutil.ignore_patterns('.cache', '__pycache__'))
        else:
            copy_file(item, target, hardlink=hardlink)
    for relative in ('GPT_SoVITS/text/G2PWModel', 'GPT_SoVITS/pretrained_models/fast_langdetect', 'nltk_data'):
        copy_tree(source / relative, home / relative, hardlink=hardlink,
                  ignore=shutil.ignore_patterns('.cache', '__pycache__', '*.pyc'))
    nltk_compatibility(home)
    missing = sovits.missing_pretrained(home)
    if missing:
        raise RuntimeError('Incomplete GPT-SoVITS payload: ' + '; '.join(missing))
    data['models']['gptsovits'] = {'path': home.relative_to(dest).as_posix(), 'files': inventory(home)}
    # Publish last: partially assembled payloads are never treated as ready.
    (dest / 'bundle.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    (dest / 'README.txt').write_text('SubFlow 完整配音包：Qwen 标准音色、Qwen 原声克隆、GPT-SoVITS v2。\n'
        '请保留目录结构。模型仅在本地加载，首次校验不需要下载。\n'
        'Python 与依赖许可证保留在 runtimes 内，GPT-SoVITS 许可证保留在模型源码目录内。\n', encoding='utf-8')
    total = sum(p.stat().st_size for p in dest.rglob('*') if p.is_file())
    print(f'OFFLINE_BUNDLE_READY: {dest} ({total / 1024**3:.2f} GiB)', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dest', type=Path)
    parser.add_argument('--hardlink', action='store_true')
    parser.add_argument('--backend', choices=['cuda', 'mps', 'cpu'])
    parser.add_argument('--copy-bundle', type=Path, help='Reuse an already assembled offline payload')
    args = parser.parse_args()
    if args.backend:
        os.environ['SUBFLOW_TORCH_BACKEND'] = args.backend
    if args.copy_bundle:
        source = args.copy_bundle.resolve()
        if not (source / 'bundle.json').is_file():
            parser.error('--copy-bundle must contain a completed bundle.json')
        target = args.dest.resolve()
        if target == source or target.is_relative_to(source) or source.is_relative_to(target):
            parser.error('Source and destination must be separate trees')
        validate_reusable_bundle(source, args.backend)
        copy_tree(source, target, hardlink=args.hardlink)
        from bilingual_sub.__version__ import __version__

        manifest_path = target / 'bundle.json'
        data = json.loads(manifest_path.read_text(encoding='utf-8'))
        refresh_sovits_sources(target, data)
        data['version'] = __version__
        # Large future manifests may also have been copied as hardlinks.
        manifest_path.unlink()
        manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        bundle(args.dest, hardlink=args.hardlink)
