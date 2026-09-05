"""Standalone asset preparation in the inference interpreter, with pinned revisions."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

REPO = "XXXXRT/GPT-SoVITS-Pretrained"
REVISION = "0c47645e02a7bc3688d7b263b0042c81e3cd82cd"
FILES = (
    "chinese-hubert-base/config.json",
    "chinese-hubert-base/preprocessor_config.json",
    "chinese-hubert-base/pytorch_model.bin",
    "chinese-roberta-wwm-ext-large/config.json",
    "chinese-roberta-wwm-ext-large/tokenizer.json",
    "chinese-roberta-wwm-ext-large/pytorch_model.bin",
    "gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt",
    "gsv-v2final-pretrained/s2G2333k.pth",
    "fast_langdetect/lid.176.bin",
    "fast_langdetect/lid.176.ftz",
)
ARCHIVES = {"G2PWModel.zip": "GPT_SoVITS/text", "nltk_data.zip": "."}
MANIFEST = ".subflow-assets.json"


def digest(path: Path, *, git_blob: bool = False) -> str:
    h = hashlib.sha1() if git_blob else hashlib.sha256()
    if git_blob:
        h.update(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_manifest(home: Path) -> dict:
    try:
        data = json.loads((home / MANIFEST).read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("schema") == 1 and data.get("revision") == REVISION and data.get("repo") == REPO:
            return data
    except (OSError, ValueError):
        pass
    return {}


def assets_ready(home: Path, *, full: bool = False) -> bool:
    data = _read_manifest(home)
    files, archives = data.get("files"), data.get("archives")
    if not isinstance(files, dict) or not isinstance(archives, dict) or set(archives) != set(ARCHIVES):
        return False
    required = {"GPT_SoVITS/pretrained_models/" + name for name in FILES}
    if not required.issubset(files):
        return False
    for names in archives.values():
        if not isinstance(names, list) or not names or any(not isinstance(name, str) or name not in files for name in names):
            return False
    for name, record in files.items():
        if not isinstance(record, dict) or not isinstance(record.get("sha256"), str):
            return False
        if not re.fullmatch(r"[0-9a-f]{64}", record["sha256"]):
            return False
        path = home / name
        try:
            if not path.resolve().is_relative_to(home.resolve()) or not path.is_file():
                return False
            stat = path.stat()
            if stat.st_size != record.get("size") or stat.st_mtime_ns != record.get("mtime_ns"):
                return False
            if full and digest(path) != record.get("sha256"):
                return False
        except (OSError, ValueError):
            return False
    return True


def _copy_verified(source: Path, target: Path, sha256: str | None = None) -> None:
    expected = sha256 or digest(source)
    if target.is_file() and digest(target) == expected:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".subflow-part")
    try:
        shutil.copyfile(source, part)
        if digest(part) != expected:
            raise ValueError(f"Copied asset checksum mismatch: {target.name}")
        part.replace(target)
    finally:
        part.unlink(missing_ok=True)


def unpack(archive: Path, target: Path) -> list[Path]:
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for item in zf.infolist():
            if not (target / item.filename).resolve().is_relative_to(target):
                raise ValueError("Unsafe archive path")
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Archive symlinks are not allowed")
        # CRC or extraction failures must not overwrite the previous install.
        with tempfile.TemporaryDirectory(prefix=".subflow-unpack-", dir=target.parent) as scratch:
            staging = Path(scratch)
            zf.extractall(staging)
            installed = []
            for source in staging.rglob("*"):
                if source.is_file():
                    path = target / source.relative_to(staging)
                    _copy_verified(source, path)
                    installed.append(path)
            return installed


def prepare(home: Path) -> None:
    from filelock import FileLock

    home.mkdir(parents=True, exist_ok=True)
    with FileLock(str(home / ".subflow-assets.lock")):
        _prepare(home)


def _prepare(home: Path) -> None:
    from huggingface_hub import get_hf_file_metadata, hf_hub_download, hf_hub_url

    previous = _read_manifest(home)
    remote = previous.get("remote", {})
    remote = remote if isinstance(remote, dict) else {}

    def download(name: str) -> Path:
        print(f"Verifying {name}", flush=True)
        known = remote.get(name, {})
        if (not isinstance(known, dict) or not isinstance(known.get("size"), int)
                or known["size"] < 0
                or not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", str(known.get("etag", "")))):
            meta = get_hf_file_metadata(hf_hub_url(REPO, name, revision=REVISION))
            known = {"etag": (meta.etag or "").strip('"'), "size": meta.size}
        etag = known["etag"]
        if not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", etag):
            raise ValueError(f"Missing content checksum for {name}")
        for force in (False, True):
            path = Path(hf_hub_download(REPO, name, revision=REVISION, force_download=force))
            if path.stat().st_size == known["size"] and digest(path, git_blob=len(etag) == 40) == etag:
                remote[name] = known
                return path
        raise ValueError(f"Downloaded asset checksum mismatch: {name}")

    installed = []
    for name in FILES:
        source = download("pretrained_models/" + name)
        target = home / "GPT_SoVITS" / "pretrained_models" / name
        _copy_verified(source, target)
        installed.append(target)
    archives = {}
    for name, target_dir in ARCHIVES.items():
        paths = unpack(download(name), home / target_dir)
        if not paths:
            raise ValueError(f"Empty asset archive: {name}")
        archives[name] = [p.relative_to(home.resolve()).as_posix() for p in paths]
        installed.extend(paths)
    files = {}
    for path in installed:
        stat = path.stat()
        files[path.resolve().relative_to(home.resolve()).as_posix()] = {
            "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest(path)}
    pending = home / (MANIFEST + ".pending")
    try:
        pending.write_text(json.dumps({"schema": 1, "repo": REPO, "revision": REVISION,
                                       "files": files, "archives": archives, "remote": remote},
                                      ensure_ascii=False), encoding="utf-8")
        pending.replace(home / MANIFEST)
    finally:
        pending.unlink(missing_ok=True)
    print("Inference assets ready", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("home", type=Path)
    prepare(parser.parse_args().home)
