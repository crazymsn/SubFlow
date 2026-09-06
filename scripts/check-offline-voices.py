"""Synthesize with each bundled engine, empty user caches and blocked external sockets."""
from __future__ import annotations

import argparse
import array
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

GUARD = '''
import sys, runpy, socket, os
from pathlib import Path
bundle_root = Path(os.environ['SUBFLOW_OFFLINE_DIR']).resolve()
def offline(event, args):
    if event in {'subprocess.Popen', 'os.system'}:
        command = str(args[:2]).lower()
        if any(word in command for word in ('pip ', 'pip.exe', "'pip'", ' install ', 'curl ', 'wget ')):
            raise RuntimeError('OFFLINE_CHECK_BLOCKED_INSTALLER: ' + command)
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        writing = (args[2] or 0) & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        if writing and Path(os.fsdecode(args[0])).resolve().is_relative_to(bundle_root):
            raise PermissionError('OFFLINE_CHECK_READ_ONLY_BUNDLE: ' + str(args[0]))
    if event == 'socket.connect':
        address = args[1]
        if isinstance(address, tuple) and address[0] not in {'127.0.0.1', '::1', 'localhost'}:
            raise RuntimeError('OFFLINE_CHECK_BLOCKED_NETWORK: ' + str(address))
    if event == 'socket.getaddrinfo' and args[0] not in {'127.0.0.1', '::1', 'localhost', None}:
        raise RuntimeError('OFFLINE_CHECK_BLOCKED_DNS: ' + str(args[0]))
sys.addaudithook(offline)
script = sys.argv[1]
sys.argv = sys.argv[1:]
runpy.run_path(script, run_name='__main__')
'''

LANGUAGE_PROBE = '''
import sys, json
sys.path.insert(0, 'GPT_SoVITS')
from text.cleaner import clean_text
texts = {'zh': '您好，请问有什么能帮您？', 'en': 'Hello, how can I help you?',
         'ja': 'こんにちは。何かお手伝いできますか。', 'ko': '안녕하세요. 무엇을 도와드릴까요?',
         'yue': '你好，有咩可以幫你？'}
for language, text in texts.items():
    phones, _, _ = clean_text(text, language, 'v2')
    assert phones, language
    print(json.dumps({'language': language, 'phonemes': len(phones)}), flush=True)
'''


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def verify_device(actual, requested, require_gpu=False):
    if requested == 'cpu' and actual != 'cpu':
        raise RuntimeError(f'CPU acceptance selected but service used {actual}')
    if requested == 'mps' and actual != 'mps':
        raise RuntimeError(f'Apple GPU acceptance failed: service used {actual}')
    if requested == 'cuda' and not str(actual).startswith('cuda'):
        raise RuntimeError(f'CUDA acceptance failed: service used {actual}')
    if require_gpu and actual not in {'mps', 'cuda'} and not str(actual).startswith('cuda:'):
        raise RuntimeError(f'GPU acceptance required but service used {actual}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--backend', default='auto', choices=['auto', 'cpu', 'cuda', 'mps'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--engines', nargs='+', default=['qwen-native', 'qwen-clone', 'gptsovits'])
    parser.add_argument('--voice-bank', action='store_true', help='Also synthesize every shipped designed voice')
    parser.add_argument('--voices', nargs='+', help='Limit --voice-bank to these stable voice IDs')
    parser.add_argument('--require-gpu', action='store_true', help='Fail if synthesis falls back to CPU')
    args = parser.parse_args()
    if args.require_gpu and args.backend == 'cpu':
        parser.error('--require-gpu cannot be combined with --backend cpu')
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='subflow-empty-profile-') as temp:
        profile = Path(temp)
        os.environ.update(SUBFLOW_OFFLINE_DIR=str(args.bundle.resolve()), SUBFLOW_AUTO_INSTALL='0',
            SUBFLOW_RUNTIME_DIR=str(profile / 'managed'), APPDATA=str(profile), HOME=str(profile),
            USERPROFILE=str(profile), LOCALAPPDATA=str(profile), XDG_CACHE_HOME=str(profile / 'cache'),
            SUBFLOW_TORCH_BACKEND=args.backend, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
            HF_HOME=str(profile / 'huggingface'), NLTK_DATA=str(profile / 'nltk'))
        for key in ('SUBFLOW_GPTSOVITS_HOME', 'SUBFLOW_GPTSOVITS_PYTHON', 'SUBFLOW_GPTSOVITS_CONFIG',
                    'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'):
            os.environ.pop(key, None)
        if args.backend == 'cpu':
            os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
        import httpx
        import yaml

        from bilingual_sub.adapters import offline_bundle as bundle
        from bilingual_sub.adapters import runtime_bootstrap as rt
        from bilingual_sub.adapters.owned_process import owned_process

        report = []
        reference = args.output.resolve() / 'qwen-native.wav'
        for engine in args.engines:
            print(f'Checking {engine} / {args.backend}', flush=True)
            python = rt.ensure_python_env('gptsovits' if engine == 'gptsovits' else 'qwentts', progress=print)
            home = bundle.model_home(engine, verify=True, progress=print)
            assert python.is_relative_to(args.bundle.resolve())
            assert home.is_relative_to(args.bundle.resolve())
            port = free_port()
            endpoint = f'http://127.0.0.1:{port}'
            env = rt.inference_env()
            if engine == 'gptsovits':
                from bilingual_sub.adapters.tts.gptsovits_runtime import runtime_config
                config = profile / 'tts.yaml'
                config.write_text(yaml.safe_dump({'custom': runtime_config(home)}), encoding='utf-8')
                env['NLTK_DATA'] = str(home / 'nltk_data')
                language_probe = profile / 'language-data.py'
                language_probe.write_text(LANGUAGE_PROBE, encoding='utf-8')
                with (args.output / 'gptsovits-language-data.log').open('wb') as language_log, owned_process(
                    [str(python), '-c', GUARD, str(language_probe)], cwd=home, env=env,
                    stdout=language_log, stderr=subprocess.STDOUT) as checker:
                    if checker.wait(timeout=240):
                        raise RuntimeError('Offline language resource check failed; see gptsovits-language-data.log')
                command = [str(home / 'api_v2.py'), '-a', '127.0.0.1', '-p', str(port), '-c', str(config)]
            else:
                command = [str(rt.bootstrap_assets() / 'qwen_server.py'), '--model', str(home), '--port', str(port),
                           *(['--native'] if engine == 'qwen-native' else [])]
                if engine == 'qwen-native':
                    command += ['--clone-model', str(bundle.model_home('qwen-clone', verify=True))]
            started = time.monotonic()
            with (args.output / f'{engine}.log').open('wb') as log, owned_process(
                [str(python), '-c', GUARD, *command], cwd=home, env=env,
                stdout=log, stderr=subprocess.STDOUT) as proc, httpx.Client(trust_env=False, timeout=900) as client:
                deadline = time.monotonic() + 300
                while True:
                    if proc.poll() is not None:
                        raise RuntimeError(f'{engine} exited; see {args.output / (engine + ".log")}')
                    try:
                        response = client.get(endpoint + '/subflow/runtime', timeout=2)
                        response.raise_for_status()
                        status = response.json()
                        break
                    except httpx.HTTPError:
                        if time.monotonic() > deadline:
                            raise RuntimeError(f'{engine} did not start within 300 seconds') from None
                        time.sleep(0.5)
                text = 'Hello, how can I help you today? It is nice to meet you.'
                payload = {'text': text, 'text_lang': 'en' if engine == 'gptsovits' else 'English', 'speaker': 'Aiden',
                           'model_revision': status.get('model_revision', '')}
                if engine != 'qwen-native':
                    if not reference.is_file():
                        raise RuntimeError('Run qwen-native first to create the neutral test reference')
                    payload.update(ref_audio_path=str(reference), prompt_text=text, prompt_lang='en',
                                   text_split_method='cut5', media_type='wav', streaming_mode=False)
                response = client.post(endpoint + '/tts', json=payload)
                response.raise_for_status()
                with wave.open(io.BytesIO(response.content)) as audio:
                    seconds = audio.getnframes() / audio.getframerate()
                    assert 1 < seconds < 30, seconds
                    assert audio.getsampwidth() == 2
                    samples = array.array('h', audio.readframes(audio.getnframes()))
                    assert max(map(abs, samples)) > 100, 'Synthesis returned silence'
                (args.output / f'{engine}.wav').write_bytes(response.content)
                status = client.get(endpoint + '/subflow/runtime').json()
                verify_device(status.get('device'), args.backend, args.require_gpu)
                report.append({'engine': engine, 'device': status.get('device'), 'seconds': seconds,
                               'elapsed': round(time.monotonic() - started, 2), 'python': str(python),
                               'model': str(home), 'external_network': 'blocked', 'auto_install': False})
                print(json.dumps(report[-1]), flush=True)
                (args.output / f'{engine}-report.json').write_text(json.dumps(report[-1], indent=2), encoding='utf-8')
                if args.voice_bank and engine == 'qwen-native':
                    from bilingual_sub.adapters.tts.routing import QWEN_LANGS
                    from bilingual_sub.core.voice_preview import preview_sample

                    bank = json.loads((rt.bootstrap_assets() / 'voices/voices.json').read_text(encoding='utf-8'))
                    if args.voices:
                        if set(args.voices) - {v['id'] for v in bank['voices']}:
                            raise ValueError('Unknown designed voice ID')
                        bank['voices'] = [v for v in bank['voices'] if v['id'] in args.voices]
                    bank_report = []
                    for voice in bank['voices']:
                        response = client.post(endpoint + '/tts', json={
                            'text': preview_sample(voice['language']), 'text_lang': QWEN_LANGS[voice['language']],
                            'speaker': voice['id'], 'model_revision': status['model_revision']})
                        response.raise_for_status()
                        assert response.headers['X-SubFlow-Model-Revision'] == status['model_revision']
                        with wave.open(io.BytesIO(response.content)) as audio:
                            seconds = audio.getnframes() / audio.getframerate()
                            assert .8 < seconds < 20, (voice['id'], seconds)
                            assert max(map(abs, array.array('h', audio.readframes(audio.getnframes())))) > 100
                        actual = client.get(endpoint + '/subflow/runtime').json()
                        assert actual['device'] == status['device'], actual
                        (args.output / (voice['id'] + '.wav')).write_bytes(response.content)
                        result = dict(voice=voice['id'], language=voice['language'], seconds=seconds, device=actual['device'])
                        bank_report.append(result)
                        print(json.dumps(result), flush=True)
                    # Switch back to the official model after all designed voices.
                    response = client.post(endpoint + '/tts', json=payload)
                    response.raise_for_status()
                    assert response.headers['X-SubFlow-Model-Revision'] == status['model_revision']
                    (args.output / 'voice-bank-report.json').write_text(json.dumps(bank_report, indent=2), encoding='utf-8')
        (args.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
