import importlib.util
import io
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient


@pytest.fixture
def server(monkeypatch, tmp_path):
    # Test the actual HTTP/transaction boundary without importing model weights.
    monkeypatch.setitem(sys.modules, "qwen_tts", SimpleNamespace(Qwen3TTSModel=object))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(StoppingCriteria=object, StoppingCriteriaList=list))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(manual_seed=lambda seed: None))
    path = Path(__file__).parents[2] / "src/bilingual_sub/_data/bootstrap/qwen_server.py"
    spec = importlib.util.spec_from_file_location("subflow_qwen_contract", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    class Talker:
        def generate(self, **kwargs):
            for stopping in kwargs.get("stopping_criteria", []):
                stopping(None, None)
    class Model:
        model = SimpleNamespace(talker=Talker())
        prompts = 0
        def create_voice_clone_prompt(self, **kwargs):
            self.prompts += 1
            return kwargs
        def generate_voice_clone(self, **kwargs):
            self.model.talker.generate()
            return [np.sin(np.arange(2400) * .1).astype("float32") * .1], 24000
    module.model = Model()
    module.device = "cpu"
    module.model_home = module.active_home = tmp_path / "native"
    ref = tmp_path / "ref.wav"
    sf.write(ref, np.sin(np.arange(4 * 16000) * .1) * .1, 16000)
    payload = {"text": "Bonjour.", "text_lang": "French", "ref_audio_path": str(ref), "prompt_text": "您好。"}
    return module, payload


def test_qwen_http_pcm_revision_and_reference_cache(server):
    module, payload = server
    with TestClient(module.app) as client:
        revision = client.get("/subflow/runtime").json()["model_revision"]
        for _ in range(2):
            response = client.post("/tts", json={**payload, "model_revision": revision})
            assert response.status_code == 200
            assert response.headers["X-SubFlow-Model-Revision"] == revision
            wave, rate = sf.read(io.BytesIO(response.content))
            assert len(wave) == 2400 and rate == 24000
        assert module.model.prompts == 1
        assert client.post("/tts", json={**payload, "model_revision": "old"}).status_code == 409
        assert client.post("/tts", json=payload, headers={"Origin": "https://example.com"}).status_code == 403


def test_cancel_reaches_actual_talker_even_when_wrapper_drops_kwargs(server):
    module, payload = server
    cancelled = threading.Event()
    original = module.model.generate_voice_clone
    generate = module.model.model.talker.generate
    def cancel_inside(**kwargs):
        cancelled.set()
        return original(**kwargs)
    module.model.generate_voice_clone = cancel_inside
    with pytest.raises(module.Cancelled):
        module.synthesize(module.Payload(**payload), cancelled)
    assert module.model.model.talker.generate == generate


@pytest.mark.parametrize('native,target', [(False, 'cuda:0'), (True, 'cuda:0'), (True, 'mps')])
def test_accelerator_fallback_invalidates_revision_before_retry(server, monkeypatch, native, target):
    module, payload = server
    module.native_voice = native
    module.device = target
    old_revision = module.revision
    calls = []
    def fail(payload, cancelled):
        raise RuntimeError(target + " out of memory")
    def reload(device):
        calls.append(device)
        module.device = device
        module.revision = "b" * 32
    monkeypatch.setattr(module, "synthesize", fail)
    monkeypatch.setattr(module, "load_model", reload)
    with TestClient(module.app) as client:
        response = client.post("/tts", json={**payload, "model_revision": old_revision})
        assert response.status_code == 409 and calls == ["cpu"]
        assert client.get("/subflow/runtime").json()["model_revision"] != old_revision


def test_bad_reference_does_not_trigger_gpu_fallback(server, monkeypatch):
    module, payload = server
    module.device = "cuda:0"
    monkeypatch.setattr(module, "load_model", lambda device: pytest.fail("Reference errors must not reload the model"))
    with TestClient(module.app) as client:
        response = client.post("/tts", json={**payload, "ref_audio_path": "https://example.com/ref.wav"})
        assert response.status_code == 500 and "参考音频不存在" in response.json()["detail"]


def test_standard_voice_http_needs_no_reference(server):
    module, _ = server
    module.native_voice = True
    calls = []
    def generate(**kwargs):
        calls.append(kwargs)
        return [np.sin(np.arange(2400) * .1).astype('float32') * .1], 24000
    module.model.generate_custom_voice = generate
    with TestClient(module.app) as client:
        state = client.get('/subflow/runtime').json()
        assert state['engine'] == 'qwen3-native'
        response = client.post('/tts', json={'text': 'Welcome back.', 'text_lang': 'English', 'speaker': 'Aiden'})
        assert response.status_code == 200
        assert len(sf.read(io.BytesIO(response.content))[0]) == 2400
    assert module.model.prompts == 0
    assert calls[0]['speaker'] == 'Aiden' and calls[0]['language'] == 'English'


def test_designed_voice_switches_model_and_preserves_service_revision(server, monkeypatch, tmp_path):
    import hashlib
    import shutil

    module, payload = server
    module.native_voice = True
    module.clone_home = tmp_path / 'base'
    folder = tmp_path / 'voices'
    folder.mkdir()
    ref = folder / 'voice.wav'
    shutil.copyfile(payload['ref_audio_path'], ref)
    monkeypatch.setattr(module, '__file__', str(tmp_path / 'qwen_server.py'))
    module.voice_bank = {'SubFlow_fr_female': dict(file='voice.wav', text='Bonjour.',
        sha256=hashlib.sha256(ref.read_bytes()).hexdigest())}
    loaded = []
    def load(device, home, *, preserve_revision):
        loaded.append((device, home, preserve_revision))
        module.active_home = home
        module.prompt_cache = module.prompt_key = None
    monkeypatch.setattr(module, 'load_model', load)
    module.model.generate_custom_voice = module.model.generate_voice_clone
    revision = module.revision
    with TestClient(module.app) as client:
        for speaker in ('SubFlow_fr_female', 'SubFlow_fr_female', 'Aiden'):
            response = client.post('/tts', json={'text':'Bonjour.', 'text_lang':'French', 'speaker':speaker,
                                               'model_revision': revision})
            assert response.status_code == 200, response.text
            assert response.headers['X-SubFlow-Model-Revision'] == revision
        assert [home for _, home, _ in loaded] == [module.clone_home, module.model_home]
        assert all(keep for _, _, keep in loaded)
        ref.write_bytes(b'corrupt')
        response = client.post('/tts', json={'text':'Bonjour.', 'text_lang':'French', 'speaker':'SubFlow_fr_female'})
        assert response.status_code == 500 and '校验失败' in response.json()['detail']
        response = client.post('/tts', json={'text':'Bonjour.', 'text_lang':'French', 'speaker':'SubFlow_missing'})
        assert response.status_code == 500 and '不存在' in response.json()['detail']


def test_m4a_reference_uses_ffmpeg_decoder(server, monkeypatch, tmp_path):
    import os

    from bilingual_sub.adapters.ffmpeg import find_ffmpeg, run_cmd

    module, payload = server
    ffmpeg = find_ffmpeg()
    monkeypatch.setenv("PATH", str(Path(ffmpeg).parent) + os.pathsep + os.environ.get("PATH", ""))
    ref = tmp_path / "参考.m4a"
    run_cmd([ffmpeg, "-y", "-i", payload["ref_audio_path"], "-c:a", "aac", str(ref)])
    payload["ref_audio_path"] = str(ref)
    with TestClient(module.app) as client:
        response = client.post("/tts", json=payload)
        assert response.status_code == 200
        assert len(sf.read(io.BytesIO(response.content))[0]) > 0


@pytest.mark.parametrize("requested,cuda,mps,expected", [
    ("auto", True, False, "cuda:0"), ("auto", False, True, "mps"),
    ("auto", False, False, "cpu"), ("cpu", True, True, "cpu"),
    ("", True, False, "cuda:0"), (" AUTO ", True, False, "cuda:0"),
    (" auto ", False, True, "mps"), (" mps ", False, False, "cpu"),
])
def test_accelerator_priority(server, monkeypatch, requested, cuda, mps, expected):
    module, _ = server
    monkeypatch.setenv("SUBFLOW_TORCH_BACKEND", requested)
    module.torch.cuda = SimpleNamespace(is_available=lambda: cuda)
    module.torch.backends = SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps))
    assert module.choose_device() == expected


@pytest.mark.parametrize('target', ['cuda:0', 'mps', 'cpu'])
def test_loader_places_model_on_selected_device(server, tmp_path, target):
    module, _ = server
    module.model_home = tmp_path
    module.torch.cuda = SimpleNamespace(is_available=lambda: True, empty_cache=lambda: None, is_bf16_supported=lambda: True)
    module.torch.backends = SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False))
    module.torch.float32, module.torch.float16, module.torch.bfloat16 = 'fp32', 'fp16', 'bf16'
    seen = []
    module.Qwen3TTSModel = SimpleNamespace(from_pretrained=lambda *a, **kw: seen.append(kw) or object())
    module.load_model(target)
    assert module.device == target
    assert seen[0]['device_map'] == target
    assert seen[0]['dtype'] == ('bf16' if target == 'cuda:0' else 'fp32')
    assert seen[0]['attn_implementation'] == 'sdpa'
