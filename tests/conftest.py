import io
import os
import wave

import pytest

from bilingual_sub.i18n import set_locale


@pytest.fixture(autouse=True)
def _isolate_resource_claims(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("SUBFLOW_LOCK_DIR", str(tmp_path_factory.mktemp("resource-claims")))


@pytest.fixture(autouse=True)
def _reset_ui_locale():
    set_locale("zh-Hans")
    yield
    set_locale("zh-Hans")


@pytest.fixture(autouse=True)
def _runtime_lifecycle(monkeypatch):
    from bilingual_sub.adapters.tts import gptsovits_runtime as rt

    monkeypatch.setenv("SUBFLOW_SOVITS_AUTOSTART", "0")
    monkeypatch.setenv("SUBFLOW_AUTO_INSTALL", "0")
    if os.environ.get("SUBFLOW_SOVITS_LIVE") != "1":
        monkeypatch.setattr(rt, "probe_endpoint", lambda *a, **k: True)
    rt.reset_boot_state()
    yield
    rt.reset_boot_state()


@pytest.fixture
def pcm_wav():
    def make(seconds=0.1):
        out = io.BytesIO()
        with wave.open(out, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\0\0" * int(seconds * 16000))
        return out.getvalue()
    return make


@pytest.fixture
def mock_sovits_runtime(monkeypatch, pcm_wav):
    """Unit pipeline tests mock the boundary explicitly; production has no test bypass."""
    from bilingual_sub.adapters.tts import gptsovits_runtime as rt

    monkeypatch.setattr(rt, "ensure_running", lambda *a, **k: "ready")
    def extract(video, dest, *args, **kwargs):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(pcm_wav(5))
        return dest
    monkeypatch.setattr(rt, "extract_ref_audio", extract)
