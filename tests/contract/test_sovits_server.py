import asyncio
import importlib.util
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import httpx
import pytest


@pytest.fixture
def api(monkeypatch):
    root = Path(__file__).resolve().parents[2] / "third_party" / "GPT-SoVITS"
    monkeypatch.setattr(sys, "argv", ["api_v2.py"])
    monkeypatch.setattr(sys, "path", list(sys.path))
    tools = ModuleType("tools")
    tools.__path__ = [str(root / "tools")]
    monkeypatch.setitem(sys.modules, "tools", tools)
    monkeypatch.delitem(sys.modules, "tools.subflow_concurrency", raising=False)
    for name, module in {
        "numpy": SimpleNamespace(ndarray=bytes), "soundfile": SimpleNamespace(), "uvicorn": SimpleNamespace(),
        "torch": SimpleNamespace(device=str, __version__="fixture", backends=SimpleNamespace(
            mps=SimpleNamespace(is_available=lambda: False))),
        "tools.i18n.i18n": SimpleNamespace(I18nAuto=lambda: lambda text: text),
        "GPT_SoVITS.TTS_infer_pack.text_segmentation_method": SimpleNamespace(get_method_names=lambda: ["cut5"]),
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    def config(_):
        return SimpleNamespace(device="cpu", is_half=False, languages=["en", "zh", "auto"], version="v2")
    class Pipeline:
        def __init__(self, configs):
            self.configs = configs
        def run(self, req):
            yield 16000, b"audio"
    monkeypatch.setitem(sys.modules, "GPT_SoVITS.TTS_infer_pack.TTS", SimpleNamespace(TTS=Pipeline, TTS_Config=config))
    spec = importlib.util.spec_from_file_location("subflow_api_contract", root / "api_v2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def pack(buffer, data, *args):
        buffer.write(data)
        return buffer
    monkeypatch.setattr(module, "pack_audio", pack)
    return module


def payload(**kwargs):
    return dict(text="hello", text_lang="en", ref_audio_path="ref.wav", prompt_lang="auto", **kwargs)


async def reached(event):
    assert await asyncio.to_thread(event.wait, 3), "worker did not start"


def test_health_responds_during_synthesis_and_model_change_waits(api, monkeypatch):
    entered, release, changed, closed = [threading.Event() for _ in range(4)]
    def generate(req):
        entered.set()
        assert release.wait(5)
        try:
            yield 16000, b"audio"
        finally:
            closed.set()
    monkeypatch.setattr(api.tts_pipeline, "run", generate)
    monkeypatch.setattr(api.tts_pipeline, "set_ref_audio", lambda path: changed.set(), raising=False)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.APP), base_url="http://local") as client:
            speech = asyncio.create_task(client.post("/tts", json=payload()))
            try:
                await reached(entered)
                health = await asyncio.wait_for(client.get("/subflow/runtime"), 1)
                assert health.json()["busy"] is True
                change = asyncio.create_task(client.get("/set_refer_audio", params={"refer_audio_path": "new.wav"}))
                await asyncio.sleep(0.05)
                assert not changed.is_set()
                release.set()
                assert (await speech).content == b"audio"
                assert (await change).status_code == 200
                assert changed.is_set() and closed.is_set()
            finally:
                release.set()
                await speech
    asyncio.run(scenario())


def test_stream_owns_model_until_closed(api, monkeypatch):
    closed, changed = threading.Event(), threading.Event()
    def generate(req):
        try:
            yield 16000, b"first"
            yield 16000, b"second"
        finally:
            closed.set()
    monkeypatch.setattr(api.tts_pipeline, "run", generate)
    monkeypatch.setattr(api.tts_pipeline, "init_t2s_weights", lambda path: changed.set(), raising=False)
    async def scenario():
        response = await api.tts_handle(payload(streaming_mode=1, media_type="raw"))
        iterator = response.body_iterator
        assert await anext(iterator) == b"first"
        change = asyncio.create_task(api.set_gpt_weights("weights.ckpt"))
        await asyncio.sleep(0.05)
        assert not changed.is_set()
        await iterator.aclose()
        assert (await change).status_code == 200
        assert closed.is_set() and changed.is_set()
    asyncio.run(scenario())


@pytest.mark.parametrize("version", ["2.0", "2.4"])
def test_http_stream_disconnect_closes_generator_immediately(api, monkeypatch, version):
    from starlette.requests import ClientDisconnect
    closed = threading.Event()
    def generate(req):
        try:
            yield 16000, b"first"
            yield 16000, b"second"
        finally:
            closed.set()
    monkeypatch.setattr(api.tts_pipeline, "run", generate)
    async def scenario():
        first = asyncio.Event()
        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                if version == "2.4":
                    raise OSError("client disconnected")
                first.set()
                await asyncio.Event().wait()
        async def receive():
            await first.wait()
            return {"type": "http.disconnect"}
        response = await api.tts_handle(payload(streaming_mode=1, media_type="raw"))
        invocation = response({"type": "http", "asgi": {"spec_version": version}}, receive, send)
        if version == "2.4":
            with pytest.raises(ClientDisconnect):
                await asyncio.wait_for(invocation, 2)
        else:
            await asyncio.wait_for(invocation, 2)
        assert closed.is_set()
        assert not api.model_operations.lock.locked()
    asyncio.run(scenario())


@pytest.mark.parametrize("during_stream", [False, True])
def test_cancelled_request_waits_for_running_thread_before_unlock(api, during_stream):
    entered, release, next_call = [threading.Event() for _ in range(3)]
    def blocking():
        entered.set()
        assert release.wait(5)
        return b"audio"
    def generate():
        yield blocking()
    async def scenario():
        gate = api.model_operations
        iterator = gate.stream(generate)
        request = asyncio.create_task(anext(iterator) if during_stream else gate.call(blocking))
        try:
            await reached(entered)
            request.cancel()
            other = asyncio.create_task(gate.call(next_call.set))
            await asyncio.sleep(0.05)
            assert not next_call.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await request
            await other
            assert next_call.is_set()
        finally:
            release.set()
            await iterator.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["get", "post"])
def test_missing_language_is_client_error(api, method):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.APP), base_url="http://local") as client:
            response = await client.get("/tts") if method == "get" else await client.post("/tts", json={})
            assert response.status_code == 400
    asyncio.run(scenario())


def test_preprocessing_failure_retries_once_on_cpu_and_closes_generators(api, monkeypatch):
    calls, closed = [], []
    api.tts_pipeline.configs.device = "mps"
    def generate(req):
        device = api.tts_pipeline.configs.device
        calls.append(device)
        try:
            if device == "mps":
                raise NotImplementedError("MPS operation unavailable")
            yield 16000, b"cpu audio"
        finally:
            closed.append(device)
    monkeypatch.setattr(api.tts_pipeline, "run", generate)
    response = asyncio.run(api.tts_handle(payload()))
    assert response.body == b"cpu audio"
    assert calls == closed == ["mps", "cpu"]
    assert api.tts_pipeline.configs.is_half is False
