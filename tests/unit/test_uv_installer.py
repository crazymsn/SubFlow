import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from bilingual_sub.adapters import runtime_bootstrap as rt
from bilingual_sub.adapters.installer import UV_VERSION
from bilingual_sub.core.control import JobControl, JobStopped


@pytest.fixture
def installer(tmp_path, monkeypatch):
    module = getattr(rt, "_installer", rt)
    suffix = ".exe" if module.os.name == "nt" else ""
    package = tmp_path / "package" / f"uv{suffix}"
    foreign = tmp_path / "foreign" / f"uv{suffix}"
    bundled = tmp_path / "bundle" / f"uv{suffix}"
    for path in (package, foreign, bundled):
        path.parent.mkdir()
        path.write_bytes(b"test executable")
    monkeypatch.setattr(module, "sys", SimpleNamespace(frozen=False, executable=str(tmp_path / "client")))
    monkeypatch.setattr(module.shutil, "which", lambda name: str(foreign))
    monkeypatch.setattr(module, "_package_uv", lambda: package, raising=False)
    monkeypatch.setattr(module, "_uv_version", lambda path, control=None: "0.11.8", raising=False)
    return module, package, foreign, bundled


def test_source_prefers_python_package_installer_to_path(installer):
    _, package, _, _ = installer
    assert rt.find_uv() == package


def test_source_can_use_verified_path_installer(installer, monkeypatch):
    module, _, foreign, _ = installer
    monkeypatch.setattr(module, "_package_uv", lambda: None)
    assert rt.find_uv() == foreign


def test_source_rejects_wrong_installer_version(installer, monkeypatch):
    module, _, _, _ = installer
    monkeypatch.setattr(module, "_uv_version", lambda *a, **kw: "0.5.31")
    with pytest.raises(RuntimeError, match="0.11.8"):
        rt.find_uv()


def test_frozen_missing_installer_does_not_use_path(installer, monkeypatch):
    module, _, _, _ = installer
    module.sys.frozen = True
    with pytest.raises(RuntimeError, match="客户端|内置"):
        rt.find_uv()


def test_frozen_uses_verified_bundle(installer):
    module, _, _, bundled = installer
    module.sys.frozen = True
    module.sys._MEIPASS = str(bundled.parent)
    assert rt.find_uv() == bundled


def test_frozen_wrong_bundle_does_not_fall_back_to_path(installer, monkeypatch):
    module, _, _, bundled = installer
    module.sys.frozen = True
    module.sys._MEIPASS = str(bundled.parent)
    monkeypatch.setattr(module, "_uv_version", lambda path, control=None: "0.5.31")
    with pytest.raises(RuntimeError, match="0.11.8"):
        rt.find_uv()


def test_frozen_without_meipass_does_not_search_current_directory(installer, monkeypatch, tmp_path):
    module, _, _, bundled = installer
    module.sys.frozen = True
    module.sys.executable = str(bundled.parent / "client")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / bundled.name).write_bytes(b"unrelated executable")
    monkeypatch.chdir(cwd)
    assert rt.find_uv() == bundled


def test_installer_version_matches_project_dependency():
    project = Path(__file__).parents[2] / "pyproject.toml"
    data = tomllib.loads(project.read_text(encoding="utf-8"))
    assert f"uv=={UV_VERSION}" in data["project"]["dependencies"]


def test_cancelled_lookup_does_not_probe_any_installer(installer, monkeypatch):
    module, _, _, _ = installer
    control = JobControl()
    control.stop()
    monkeypatch.setattr(module, "_uv_version", lambda *a, **kw: pytest.fail("cancelled lookup started uv"))
    with pytest.raises(JobStopped):
        rt.find_uv(control=control)
