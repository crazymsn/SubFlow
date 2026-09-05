import httpx
import pytest

from bilingual_sub.adapters.tts import model_identity as identity
from bilingual_sub.adapters.tts.base import TtsRequest
from bilingual_sub.adapters.tts.gptsovits import GptSovitsTts
from bilingual_sub.adapters.tts.model_identity import fetch_model_revision


@pytest.mark.parametrize("body,expected", [
    ({"model_revision": "a" * 32}, "a" * 32), ({}, None),
    ({"model_revision": 42}, None), ({"model_revision": "a" * 10000}, None), ([], None),
])
def test_runtime_identity_requires_protocol_token(monkeypatch, body, expected):
    client = httpx.Client
    def request(req):
        assert str(req.url) == "http://local/subflow/runtime"
        return httpx.Response(200, json=body)
    monkeypatch.setattr(httpx, "Client", lambda **kw: client(**kw, transport=httpx.MockTransport(request)))
    assert fetch_model_revision("http://local/") == expected


@pytest.mark.parametrize("failure", ["missing", "invalid", "offline"])
def test_legacy_or_unavailable_server_has_no_reusable_identity(monkeypatch, failure):
    client = httpx.Client
    def request(req):
        if failure == "offline":
            raise httpx.ConnectError("offline")
        return httpx.Response(404 if failure == "missing" else 200, content=b"not JSON")
    monkeypatch.setattr(httpx, "Client", lambda **kw: client(**kw, transport=httpx.MockTransport(request)))
    assert fetch_model_revision("http://local") is None


@pytest.mark.parametrize("status,header", [(409, None), (200, None), (200, "b" * 32)])
def test_synth_does_not_publish_audio_from_wrong_model(tmp_path, monkeypatch, pcm_wav, status, header):
    ref, dest = tmp_path / "ref.wav", tmp_path / "out.wav"
    ref.write_bytes(pcm_wav(1))
    dest.write_bytes(b"previous output")
    async def post(url, payload, control):
        assert payload["model_revision"] == "a" * 32
        return httpx.Response(status, content=pcm_wav(), headers={"X-SubFlow-Model-Revision": header} if header else {})
    monkeypatch.setattr("bilingual_sub.adapters.tts.gptsovits._post_audio", post)
    with pytest.raises(identity.ModelChanged):
        GptSovitsTts(ref_audio=ref).synth(TtsRequest("hello", "en", "", dest, "a" * 32))
    assert dest.read_bytes() == b"previous output"
