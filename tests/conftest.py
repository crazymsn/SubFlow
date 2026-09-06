import io
import os
import wave

import pytest

from bilingual_sub.i18n import set_locale


@pytest.fixture(scope="session", autouse=True)
def _qt_application_lifetime():
    """Keep Qt's application/TLS alive across playback and worker tests.

    Recreating QApplication between tests leaves deferred QProcess events and
    thread-local state behind. Production already owns one app for its lifetime.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        yield None
        return
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture(autouse=True)
def _qt_widget_cleanup(_qt_application_lifetime):
    app = _qt_application_lifetime
    if app is None:
        yield
        return
    from PySide6.QtCore import QCoreApplication, QEvent, QThread

    previous = set(app.topLevelWidgets())
    yield
    # Closing a widget alone does not delete it. Retained hidden windows make
    # each subsequent global stylesheet update restyle the entire test history.
    for widget in app.topLevelWidgets():
        if widget in previous:
            continue
        widget.close()
        workers = widget.findChildren(QThread)
        workers += [value for name, value in vars(widget).items()
                    if name.endswith('worker') and isinstance(value, QThread)]
        if any(worker.isRunning() for worker in workers):
            continue  # Never destroy a running thread, including on test failure.
        for worker in workers:
            worker.wait()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture(autouse=True)
def _isolate_user_state(tmp_path, monkeypatch):
    """GUI persistence and credential tests must never touch the developer's profile."""
    import keyring

    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM") or "offscreen")
    for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(name, str(profile))
    for name in ("SUBFLOW_API_KEY", "MEDING_API_KEY", "SUBFLOW_GPTSOVITS_REF",
                 "SUBFLOW_GPTSOVITS_PROMPT", "SUBFLOW_GPTSOVITS_PROMPT_LANG"):
        monkeypatch.delenv(name, raising=False)
    credentials = {}
    monkeypatch.setattr(keyring, "get_password", lambda service, user: credentials.get((service, user)))
    monkeypatch.setattr(keyring, "set_password", lambda service, user, value: credentials.__setitem__((service, user), value))
    monkeypatch.setattr(keyring, "delete_password", lambda service, user: credentials.pop((service, user), None))


@pytest.fixture(autouse=True)
def _isolate_resource_claims(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("SUBFLOW_LOCK_DIR", str(tmp_path_factory.mktemp("resource-claims")))


@pytest.fixture(autouse=True)
def _isolate_last_job(tmp_path_factory, monkeypatch):
    pointer = tmp_path_factory.mktemp("last-job") / "last_job.json"
    monkeypatch.setattr("bilingual_sub.pipeline.last_job_pointer", lambda: pointer)


@pytest.fixture(autouse=True)
def _reset_ui_locale():
    set_locale("zh-Hans")
    yield
    set_locale("zh-Hans")


@pytest.fixture(autouse=True)
def _runtime_lifecycle(monkeypatch):
    from bilingual_sub.adapters.tts import gptsovits_runtime as rt
    from bilingual_sub.adapters.tts import qwen_runtime as qr

    monkeypatch.setenv("SUBFLOW_SOVITS_AUTOSTART", "0")
    monkeypatch.setenv("SUBFLOW_AUTO_INSTALL", "0")
    if os.environ.get("SUBFLOW_SOVITS_LIVE") != "1":
        # Host hardware must not select real CUDA installations during unit tests.
        monkeypatch.setattr("bilingual_sub.adapters.runtime_bootstrap._cuda_driver_available", lambda: False)
        monkeypatch.setattr(rt, "probe_endpoint", lambda *a, **k: True)
        monkeypatch.setattr(qr, "probe_endpoint", lambda *a, **k: True)
        monkeypatch.setattr(qr, "runtime_device", lambda *a, **k: 'cpu')
        monkeypatch.setattr("bilingual_sub.adapters.tts.model_identity.fetch_model_revision", lambda endpoint: "a" * 32)
    rt.reset_boot_state()
    qr.reset_boot_state()
    yield
    rt.reset_boot_state()
    qr.stop_servers()
    qr.reset_boot_state()


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
