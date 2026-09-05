import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from bilingual_sub._data.bootstrap import download_assets as assets


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "FILES", ("model.bin",))
    cache = tmp_path / "hub"
    (cache / "pretrained_models").mkdir(parents=True)
    (cache / "pretrained_models/model.bin").write_bytes(b"correct-model")
    for name, entry in [("G2PWModel.zip", "G2PWModel/config.py"), ("nltk_data.zip", "nltk_data/taggers/data.bin")]:
        with zipfile.ZipFile(cache / name, "w") as archive:
            archive.writestr(entry, b"language-data")
    originals = {p.relative_to(cache).as_posix(): p.read_bytes() for p in cache.rglob("*") if p.is_file()}
    calls = []
    def download(repo, name, *, revision, force_download=False):
        calls.append((name, force_download))
        if force_download:
            (cache / name).write_bytes(originals[name])
        return str(cache / name)
    def metadata(name):
        return SimpleNamespace(etag=hashlib.sha256(originals[name]).hexdigest(), size=len(originals[name]))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(
        hf_hub_download=download, hf_hub_url=lambda repo, name, **kw: name,
        get_hf_file_metadata=metadata))
    return cache, calls


def test_assets_repair_same_size_damage_and_deleted_language_file(tmp_path, hub, monkeypatch):
    home = tmp_path / "runtime"
    assets.prepare(home)
    assert assets.assets_ready(home, full=True)
    model = home / "GPT_SoVITS/pretrained_models/model.bin"
    original = model.read_bytes()
    model.write_bytes(b"x" * len(original))
    stamp = model.stat().st_mtime_ns
    os.utime(model, ns=(stamp, stamp + 1_000_000))
    assert not assets.assets_ready(home)
    # A previous verified manifest allows cache repair without metadata requests.
    monkeypatch.setattr(sys.modules["huggingface_hub"], "get_hf_file_metadata",
                        lambda *a, **k: pytest.fail("known revision metadata should be reused"))
    assets.prepare(home)
    assert model.read_bytes() == original
    language = home / "nltk_data/taggers/data.bin"
    language.unlink()
    assert not assets.assets_ready(home)
    assets.prepare(home)
    assert language.read_bytes() == b"language-data"
    assert assets.assets_ready(home, full=True)


def test_corrupt_hub_cache_is_refetched_before_copy(tmp_path, hub):
    cache, calls = hub
    (cache / "pretrained_models/model.bin").write_bytes(b"damaged-model")
    home = tmp_path / "runtime"
    assets.prepare(home)
    assert ("pretrained_models/model.bin", True) in calls
    assert (home / "GPT_SoVITS/pretrained_models/model.bin").read_bytes() == b"correct-model"


def test_failed_checksum_refetch_preserves_old_model(tmp_path, hub, monkeypatch):
    cache, _ = hub
    model = cache / "pretrained_models/model.bin"
    model.write_bytes(b"damaged-model")
    monkeypatch.setattr(sys.modules["huggingface_hub"], "hf_hub_download", lambda *a, **k: str(model))
    home = tmp_path / "runtime"
    target = home / "GPT_SoVITS/pretrained_models/model.bin"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"previous usable model")
    with pytest.raises(ValueError, match="checksum mismatch"):
        assets.prepare(home)
    assert target.read_bytes() == b"previous usable model"
    assert not (home / assets.MANIFEST).exists()


def test_archive_extraction_failure_keeps_existing_files(tmp_path, monkeypatch):
    archive = tmp_path / "data.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("file.txt", "new")
    target = tmp_path / "target"
    target.mkdir()
    (target / "file.txt").write_text("old")
    def partial(self, path):
        (Path(path) / "file.txt").write_text("partial")
        raise zipfile.BadZipFile("CRC failed")
    monkeypatch.setattr(zipfile.ZipFile, "extractall", partial)
    with pytest.raises(zipfile.BadZipFile):
        assets.unpack(archive, target)
    assert (target / "file.txt").read_text() == "old"
    assert not list(tmp_path.glob(".subflow-unpack-*"))


def test_corrupt_copy_does_not_replace_destination(tmp_path, monkeypatch):
    source, target = tmp_path / "source.bin", tmp_path / "target.bin"
    source.write_bytes(b"correct")
    target.write_bytes(b"previous")
    monkeypatch.setattr(assets.shutil, "copyfile", lambda src, dest: Path(dest).write_bytes(b"corrupt"))
    with pytest.raises(ValueError, match="checksum mismatch"):
        assets._copy_verified(source, target)
    assert target.read_bytes() == b"previous"
    assert not list(tmp_path.glob("*.subflow-part"))


def test_full_verification_detects_damage_with_preserved_file_metadata(tmp_path, hub):
    home = tmp_path / "runtime"
    assets.prepare(home)
    target = home / "GPT_SoVITS/pretrained_models/model.bin"
    stat = target.stat()
    target.write_bytes(b"x" * stat.st_size)
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert not assets.assets_ready(home, full=True)


def test_damaged_manifest_is_repaired_from_pinned_metadata(tmp_path, hub):
    home = tmp_path / "runtime"
    assets.prepare(home)
    manifest = home / assets.MANIFEST
    data = json.loads(manifest.read_text())
    del data["files"]["GPT_SoVITS/pretrained_models/model.bin"]["sha256"]
    del data["remote"]["pretrained_models/model.bin"]["size"]
    manifest.write_text(json.dumps(data))
    assert not assets.assets_ready(home)
    assets.prepare(home)
    assert assets.assets_ready(home, full=True)
