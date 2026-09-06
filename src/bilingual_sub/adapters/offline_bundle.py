"""Relocatable, read-only inference payload shipped with a desktop release."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from pathlib import Path

MANIFEST = 'bundle.json'


def architecture(value: str) -> str:
    return {'amd64': 'x86_64', 'aarch64': 'arm64'}.get(value.lower(), value.lower())


def bundle_root() -> Path | None:
    override = os.environ.get('SUBFLOW_OFFLINE_DIR', '').strip()
    if override:
        root = Path(override).expanduser().resolve()
        if not (root / MANIFEST).is_file():
            raise RuntimeError(f'完整配音包缺少清单：{root / MANIFEST}')
        return root
    if getattr(sys, 'frozen', False):
        exe = Path(sys.executable).resolve().parent
        candidates = (exe / 'offline', exe.parent / 'Resources' / 'offline')
        for root in candidates:
            if root.exists() or (root.parent / 'offline-required.json').exists():
                if not (root / MANIFEST).is_file():
                    raise RuntimeError(f'完整配音包尚未复制完成：{root}')
                return root
    return None


def contained(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise RuntimeError('完整配音包含有无效路径')
    return path


def manifest() -> tuple[Path, dict] | None:
    root = bundle_root()
    if root is None:
        return None
    try:
        data = json.loads((root / MANIFEST).read_text(encoding='utf-8'))
        if (data['schema'] != 1 or data['platform'] != sys.platform
                or architecture(data['machine']) != architecture(platform.machine())):
            raise ValueError('platform mismatch')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError('完整配音包清单损坏或与本机系统/芯片不匹配，请使用对应平台的完整客户端') from exc
    return root, data


def runtime(kind: str, backend: str) -> tuple[Path, str, str] | None:
    if kind not in {'qwentts', 'gptsovits', 'asr', 'whisperx'}:
        return None
    payload = manifest()
    if payload is None:
        return None
    root, data = payload
    # Older voice-only bundles can still provision recognition separately.
    if kind in {'asr', 'whisperx'} and kind not in data.get('runtimes', {}) and not data.get('recognition_runtimes'):
        return None
    try:
        record = data['runtimes'][kind]
        build = record['backend']
        # CUDA and native Apple wheels include CPU kernels. Never install another
        # environment merely because this computer has no usable GPU.
        if backend != 'cpu' and backend != build:
            raise ValueError('backend mismatch')
        python = contained(root, record['python'])
        if not python.is_file():
            raise ValueError('missing Python')
        return python, record['torch'], build
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f'完整配音包的 {kind} 运行环境缺失或不兼容，请重新解压完整包') from exc


def model_home(name: str, *, verify: bool = False, progress=None, control=None) -> Path | None:
    payload = manifest()
    if payload is None:
        return None
    root, data = payload
    try:
        record = data['models'][name]
        home = contained(root, record['path'])
        files = record['files']
        if not files or not home.is_dir():
            raise ValueError('empty model')
        if verify:
            _verify(home, files, name, progress, control)
        return home
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f'内置 {name} 模型缺失或损坏，请重新解压完整客户端；无需重新安装 Python') from exc


def _verify(home, files, name, progress, control):
    from bilingual_sub.adapters.runtime_bootstrap import runtime_root

    signature = []
    for relative, record in files.items():
        path = contained(home, relative)
        st = path.stat()
        if st.st_size != record['size']:
            raise ValueError(f'size mismatch: {relative}')
        signature.append((relative, st.st_size, st.st_mtime_ns, st.st_ctime_ns, record['sha256']))
    fingerprint = hashlib.sha256(json.dumps([str(home), signature]).encode()).hexdigest()
    cache = runtime_root() / 'bundle-checks' / (fingerprint + '.ok')
    if cache.is_file():
        return
    if progress:
        progress(f'正在校验内置 {name} 模型（本地文件，无需下载）…')
    for relative, record in files.items():
        digest = hashlib.sha256()
        with contained(home, relative).open('rb') as stream:
            for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                if control:
                    control.wait_if_paused()
                digest.update(block)
        if digest.hexdigest() != record['sha256']:
            raise ValueError(f'checksum mismatch: {relative}')
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(name, encoding='utf-8')
