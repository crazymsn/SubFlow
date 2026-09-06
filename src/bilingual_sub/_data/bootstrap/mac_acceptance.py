"""Read-only, offline component checks using the interpreters inside a Mac app.

This checks environments and small tensor operations, not real voice quality or
end-to-end video acceptance. Those remain explicit manual acceptance items.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import plistlib
import subprocess
import sys
import time
from pathlib import Path

KINDS = ('asr', 'whisperx', 'qwentts', 'gptsovits')


def contained(root, relative):
    if not isinstance(relative, str):
        raise ValueError('Invalid bundle path')
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Bundle path escapes the app')
    return path


def worker(kind, device, sovits):
    import torch

    torch.set_num_threads(2)
    imported = {'asr': 'whisper', 'whisperx': 'whisperx', 'qwentts': 'qwen_tts', 'gptsovits': 'torchaudio'}
    importlib.import_module(imported[kind])
    target = 'cpu' if kind == 'whisperx' else device
    if target == 'mps' and not (torch.backends.mps.is_built() and torch.backends.mps.is_available()):
        raise RuntimeError('MPS is not available in this runtime; GPU acceptance failed')
    result = {'kind': kind, 'python': sys.version.split()[0], 'machine': platform.machine(),
              'torch': str(torch.__version__), 'device': target, 'checks': []}
    x = torch.ones((8, 8), device=target)
    assert torch.allclose((x @ x).cpu(), torch.full((8, 8), 8.0))
    result['checks'].append('tensor_matmul')
    if kind == 'asr':
        from whisper.model import ModelDimensions, Whisper

        model = Whisper(ModelDimensions(4, 8, 8, 2, 1, 32, 8, 8, 2, 1))
        alignment = model.alignment_heads
        if target == 'mps':
            model.alignment_heads = alignment.to_dense()
        model.to(target)
        if target == 'mps':
            model.alignment_heads = alignment
        with torch.no_grad():
            value = model(torch.zeros((1, 4, 16), device=target), torch.tensor([[1, 2]], device=target))
        assert value.device.type == target and torch.isfinite(value).all()
        result['checks'].append('whisper_encoder_decoder')
    elif kind == 'qwentts':
        import torch.nn.functional as functional

        value = functional.scaled_dot_product_attention(x[None, None], x[None, None], x[None, None])
        assert value.device.type == target and torch.isfinite(value).all()
        result['checks'].append('qwen_dependency_and_sdpa')
    elif kind == 'gptsovits':
        sys.path.insert(0, str(Path(sovits) / 'GPT_SoVITS'))
        from module.mel_processing import spectrogram_torch

        value = spectrogram_torch(torch.zeros((1, 4096), device=target), 512, 32000, 128, 512)
        assert value.device.type == target and torch.isfinite(value).all()
        result['checks'].append('sovits_spectrogram')
    else:
        import ctranslate2

        result['compute_types'] = sorted(ctranslate2.get_supported_compute_types('cpu'))
        assert result['compute_types']
        result['checks'].append('ctranslate2_cpu')
    if target == 'mps':
        torch.mps.synchronize()
    result['ok'] = True
    return result


def run_checks(app, output, device):
    app, output = app.resolve(), output.resolve()
    if output.is_relative_to(app):
        raise ValueError('Save evidence outside the application bundle')
    # Never overwrite evidence from another run.
    output.mkdir(parents=True, exist_ok=False)
    report = {'ok': False, 'gpu_components_verified': False, 'product_acceptance': 'pending_manual_tests',
              'system': {'macos': platform.mac_ver()[0], 'machine': platform.machine()}, 'runtimes': []}
    try:
        root = app / 'Contents/Resources/offline'
        data = json.loads((root / 'bundle.json').read_text(encoding='utf-8'))
        if data.get('schema') != 1 or data.get('platform') != 'darwin' or data.get('machine') != platform.machine():
            raise ValueError('Wrong system/architecture or invalid bundle manifest; use the native Mac package')
        with (app / 'Contents/Info.plist').open('rb') as stream:
            info = plistlib.load(stream)
        report['version'] = info.get('CFBundleShortVersionString')
        report['minimum_macos'] = info.get('LSMinimumSystemVersion')
        target = ('mps' if platform.machine() == 'arm64' else 'cpu') if device == 'auto' else device
        report['requested_device'] = target
        env = {key: value for key, value in os.environ.items() if key not in
               {'PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'SUBFLOW_OFFLINE_DIR'}}
        env.update(PYTHONDONTWRITEBYTECODE='1', SUBFLOW_AUTO_INSTALL='0', HF_HUB_OFFLINE='1',
                   TRANSFORMERS_OFFLINE='1', PYTORCH_ENABLE_MPS_FALLBACK='1', SUBFLOW_TORCH_BACKEND=target)
        sovits = contained(root, data['models']['gptsovits']['path'])
        for kind in KINDS:
            started = time.monotonic()
            entry = {'kind': kind, 'ok': False}
            try:
                record = data['runtimes'][kind]
                expected_build = 'mps' if platform.machine() == 'arm64' else 'cpu'
                if record['backend'] != expected_build:
                    raise ValueError(f'{kind}: incorrect packaged backend, expected {expected_build}')
                python = contained(root, record['python'])
                proc = subprocess.run([str(python), '-I', '-B', str(Path(__file__).resolve()), '--worker', kind,
                    '--device', target, '--sovits', str(sovits)], cwd=output, env=env,
                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
                (output / f'{kind}.log').write_text(proc.stdout + '\n' + proc.stderr, encoding='utf-8')
                if proc.returncode:
                    raise RuntimeError(f'Worker exited {proc.returncode}; see {kind}.log')
                entry = json.loads(proc.stdout.strip().splitlines()[-1])
                if entry['machine'] != platform.machine():
                    raise ValueError('Interpreter architecture does not match this Mac')
                expected_device = 'cpu' if kind == 'whisperx' else target
                if entry.get('device') != expected_device or not entry.get('checks') or not entry.get('ok'):
                    raise ValueError(f'{kind}: component checks did not finish on {expected_device}')
            except Exception as exc:
                entry.update(ok=False, error=str(exc))
            entry['seconds'] = round(time.monotonic() - started, 2)
            report['runtimes'].append(entry)
            print(f"{kind}: {'PASS' if entry['ok'] else 'FAIL'}", flush=True)
        report['ok'] = all(item['ok'] for item in report['runtimes'])
        report['gpu_components_verified'] = target == 'mps' and report['ok']
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, default=Path('/Applications/SubFlow.app'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--device', choices=('auto', 'mps', 'cpu'), default='auto')
    parser.add_argument('--worker', choices=KINDS, help=argparse.SUPPRESS)
    parser.add_argument('--sovits', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.worker, args.device, args.sovits)))
        return
    if sys.platform != 'darwin':
        parser.error('Run Mac acceptance on the actual Mac, not Windows or Linux')
    if args.output is None:
        parser.error('--output is required and must be a new evidence directory')
    result = run_checks(args.app, args.output, args.device)
    print(f"Report: {args.output / 'report.json'}")
    if not result['ok']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
