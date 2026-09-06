from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, current_thread

import pytest
import yaml
from filelock import Timeout

from bilingual_sub import config


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("ui:\n  theme: dark\ntts:\n  gptsovits:\n    prompt_text: 原有参考文字\n", encoding="utf-8")
    monkeypatch.setattr(config, "_user_config_path", lambda: path)
    return path


@pytest.mark.parametrize("error", [OSError, KeyboardInterrupt])
def test_interrupted_settings_write_keeps_previous_file(settings_file, monkeypatch, error):
    original = settings_file.read_bytes()
    original_open = Path.open

    class FailingWriter:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            self.stream.__enter__()
            return self
        def __exit__(self, *args):
            return self.stream.__exit__(*args)
        def __getattr__(self, key):
            return getattr(self.stream, key)
        def write(self, text):
            self.stream.write(text[:6])
            self.stream.flush()
            raise error("injected partial write")

    def failing_open(path, mode="r", *a, **k):
        stream = original_open(path, mode, *a, **k)
        if path.parent == settings_file.parent and "w" in mode:
            return FailingWriter(stream)
        return stream

    monkeypatch.setattr(Path, "open", failing_open)
    with pytest.raises(error, match="injected partial write"):
        config.save_user_overrides({"ui": {"theme": "light"}})
    assert settings_file.read_bytes() == original
    assert not list(settings_file.parent.glob(".subflow-*.tmp"))


@pytest.mark.parametrize("existing", ["- wrong\n- root\n", "false\n", "0\n", "[]\n", "[broken"])
def test_save_does_not_replace_invalid_existing_config(settings_file, existing):
    settings_file.write_text(existing, encoding="utf-8")
    with pytest.raises((ValueError, yaml.YAMLError)):
        config.save_user_overrides({"ui": {"theme": "light"}})
    assert settings_file.read_text(encoding="utf-8") == existing


def test_concurrent_settings_updates_preserve_both_changes(settings_file, monkeypatch):
    first_loaded, release_first, second_finished = Event(), Event(), Event()
    load = config._load_yaml
    first_name = []

    def paused_load(path, **kwargs):
        data = load(path, **kwargs)
        if current_thread().name == first_name[0]:
            first_loaded.set()
            assert release_first.wait(10)
        return data

    monkeypatch.setattr(config, "_load_yaml", paused_load)

    def first_save():
        first_name.append(current_thread().name)
        config.save_user_overrides({"ui": {"theme": "light"}})

    def second_save():
        try:
            config.save_user_overrides({"translate": {"model": "chosen-model"}})
        finally:
            second_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_save)
        try:
            assert first_loaded.wait(10)
            second = pool.submit(second_save)
            second_finished.wait(2)
        finally:
            release_first.set()
        first.result(timeout=10)
        second.result(timeout=10)
    data = load(settings_file)
    assert data["ui"]["theme"] == "light"
    assert data["translate"]["model"] == "chosen-model"
    assert data["tts"]["gptsovits"]["prompt_text"] == "原有参考文字"


def test_failed_replacement_keeps_previous_settings(settings_file, monkeypatch):
    original = settings_file.read_bytes()
    replace = Path.replace
    def fail_commit(path, target):
        if Path(target) == settings_file:
            raise PermissionError("injected replacement failure")
        return replace(path, target)
    monkeypatch.setattr(Path, "replace", fail_commit)
    with pytest.raises(PermissionError, match="injected replacement failure"):
        config.save_user_overrides({"ui": {"theme": "light"}})
    assert settings_file.read_bytes() == original
    assert not list(settings_file.parent.glob(".subflow-*.tmp"))


def test_unserializable_override_keeps_previous_settings(settings_file):
    original = settings_file.read_bytes()
    with pytest.raises(yaml.YAMLError):
        config.save_user_overrides({"unsupported": object()})
    assert settings_file.read_bytes() == original


@pytest.mark.parametrize("contents", [None, "", "# empty configuration\n"])
def test_initial_settings_save_creates_valid_config(settings_file, contents):
    if contents is None:
        settings_file.unlink()
    else:
        settings_file.write_text(contents, encoding="utf-8")
    assert config.save_user_overrides({"ui": {"theme": "light"}}) == settings_file
    assert yaml.safe_load(settings_file.read_text(encoding="utf-8")) == {"ui": {"theme": "light"}}


def test_settings_save_preserves_user_managed_symlink(settings_file, monkeypatch):
    link = settings_file.with_name("linked.yaml")
    try:
        link.symlink_to(settings_file.name)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    monkeypatch.setattr(config, "_user_config_path", lambda: link)
    assert config.save_user_overrides({"ui": {"theme": "light"}}) == link
    assert link.is_symlink() and link.read_bytes() == settings_file.read_bytes()
    assert yaml.safe_load(settings_file.read_text(encoding="utf-8"))["ui"]["theme"] == "light"


def test_busy_settings_file_reports_error_without_writing(settings_file, monkeypatch):
    original = settings_file.read_bytes()
    class Busy:
        def __init__(self, *a, **k):
            pass
        def __enter__(self):
            raise Timeout("config lock")
        def __exit__(self, *a):
            pass
    monkeypatch.setattr(config, "FileLock", Busy)
    with pytest.raises(RuntimeError, match="配置正在被其他窗口保存"):
        config.save_user_overrides({"ui": {"theme": "light"}})
    assert settings_file.read_bytes() == original
