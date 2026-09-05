import asyncio
import importlib.util
import json
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
            self.model_revision = "a" * 32
        def run(self, req):
            yield 16000, b"audio"
        def reset_models(self, *, device=None, is_half=None):
            self.configs.device = device
            self.configs.is_half = is_half
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


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("field,value", [
    ("text", "\n  "), ("batch_size", 0), ("top_k", -1), ("top_p", 1.1), ("top_p", -0.1),
    ("temperature", 0), ("speed_factor", 0), ("speed_factor", float("nan")),
    ("fragment_interval", -1), ("repetition_penalty", 0), ("batch_threshold", 2),
    ("sample_steps", 0), ("overlap_length", 0), ("min_chunk_length", 0), ("seed", 2**32),
])
def test_invalid_request_rejected_before_model_execution(api, monkeypatch, method, field, value):
    monkeypatch.setattr(api.tts_pipeline, "run", lambda req: pytest.fail("invalid input reached model"))
    request = payload()
    request[field] = value
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.APP), base_url="http://local") as client:
            if method == "get":
                response = await client.get("/tts", params=request)
            else:
                response = await client.post("/tts", content=json.dumps(request), headers={"Content-Type": "application/json"})
            assert response.status_code == 400
            assert field in response.json()["message"]
    asyncio.run(scenario())


def test_supported_zero_boundaries_are_accepted(api):
    response = asyncio.run(api.tts_handle(payload(top_k=0, top_p=0, fragment_interval=0, batch_threshold=0)))
    assert response.status_code == 200


@pytest.mark.parametrize("method", ["get", "post"])
def test_model_revision_is_checked_after_waiting_for_lock(api, monkeypatch, method):
    monkeypatch.setattr(api.tts_pipeline, "run", lambda req: pytest.fail("stale request reached inference"))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.APP), base_url="http://local") as client:
            await api.model_operations.lock.acquire()
            try:
                request = payload(model_revision="a" * 32)
                pending = asyncio.create_task(client.request(method, "/tts", **{
                    "params" if method == "get" else "json": request}))
                await asyncio.sleep(0.02)
                api.tts_pipeline.model_revision = "b" * 32
            finally:
                api.model_operations.lock.release()
            response = await pending
            assert response.status_code == 409
            assert (await client.get("/subflow/runtime")).json()["model_revision"] == "b" * 32
    asyncio.run(scenario())


def test_audio_header_reports_model_after_cpu_fallback(api, monkeypatch):
    api.tts_pipeline.configs.device = "mps"
    def generate(req):
        if api.tts_pipeline.configs.device == "mps":
            raise RuntimeError("MPS operation unavailable")
        yield 16000, b"cpu audio"
    def reset(**kwargs):
        api.tts_pipeline.configs.device = "cpu"
        api.tts_pipeline.model_revision = "b" * 32
    monkeypatch.setattr(api.tts_pipeline, "run", generate)
    monkeypatch.setattr(api.tts_pipeline, "reset_models", reset)
    response = asyncio.run(api.tts_handle(payload(model_revision="a" * 32)))
    assert response.status_code == 200 and response.body == b"cpu audio"
    assert response.headers["X-SubFlow-Model-Revision"] == "b" * 32


def test_language_support_is_rechecked_under_model_lock(api, monkeypatch):
    monkeypatch.setattr(api.tts_pipeline, "run", lambda req: pytest.fail("unsupported language reached model"))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.APP), base_url="http://local") as client:
            await api.model_operations.lock.acquire()
            try:
                pending = asyncio.create_task(client.post("/tts", json=payload()))
                await asyncio.sleep(.02)
                api.tts_pipeline.configs.languages = ["zh"]
            finally:
                api.model_operations.lock.release()
            assert (await pending).status_code == 400
    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [0, 1, 2, 3])
def test_no_speech_error_is_not_reported_as_audio_or_mps_failure(api, monkeypatch, streaming):
    from tools.subflow_validation import NoSpeechError
    api.tts_pipeline.configs.device = "mps"
    def fail(req):
        raise NoSpeechError("No speakable segments")
    monkeypatch.setattr(api.tts_pipeline, "run", fail)
    response = asyncio.run(api.tts_handle(payload(streaming_mode=streaming)))
    assert response.status_code == 400
    assert api.tts_pipeline.configs.device == "mps"
    assert "No speakable" in json.loads(response.body)["Exception"]


def test_prefetched_stream_can_close_before_first_chunk_is_sent(api, monkeypatch):
    closed = threading.Event()
    def generate(req):
        try:
            yield 16000, b"audio"
        finally:
            closed.set()
    monkeypatch.setattr(api.tts_pipeline, "run", generate)
    async def scenario():
        response = await api.tts_handle(payload(streaming_mode=1))
        assert api.model_operations.lock.locked()
        await response.body_iterator.aclose()
        assert closed.is_set()
        assert not api.model_operations.lock.locked()
    asyncio.run(scenario())


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


def test_get_auxiliary_references_are_query_parameters(api, monkeypatch):
    seen = []
    def generate(req):
        seen.extend(req["aux_ref_audio_paths"])
        yield 16000, b"audio"
    monkeypatch.setattr(api.tts_pipeline, "run", generate)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.APP), base_url="http://local") as client:
            response = await client.get("/tts", params=[*payload().items(), ("aux_ref_audio_paths", "one.wav"),
                                                      ("aux_ref_audio_paths", "two.wav")])
            assert response.status_code == 200
    asyncio.run(scenario())
    assert seen == ["one.wav", "two.wav"]


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


def test_language_validation_uses_current_model_configuration(api):
    api.tts_pipeline.configs = SimpleNamespace(device="cpu", is_half=False, languages=["en"], version="v1")
    request = payload()
    request["text_lang"] = "zh"
    response = asyncio.run(api.tts_handle(request))
    assert response.status_code == 400
    assert "version v1" in json.loads(response.body)["message"]


def test_failed_cpu_recovery_does_not_mutate_serving_config(api, monkeypatch):
    config = api.tts_pipeline.configs
    config.device = "mps"
    def fail_inference(req):
        raise NotImplementedError("MPS failure")
    def fail_recovery(**kwargs):
        raise RuntimeError("CPU model failed to load")
    monkeypatch.setattr(api.tts_pipeline, "run", fail_inference)
    monkeypatch.setattr(api.tts_pipeline, "reset_models", fail_recovery)
    response = asyncio.run(api.tts_handle(payload()))
    assert response.status_code == 400
    assert api.tts_pipeline.configs is config and config.device == "mps"
