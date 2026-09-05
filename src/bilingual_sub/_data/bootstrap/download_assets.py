"""Standalone asset preparation in the inference interpreter, with pinned revisions."""
from __future__ import annotations

import argparse
import shutil
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


def unpack(archive: Path, target: Path) -> None:
    target = target.resolve()
    with zipfile.ZipFile(archive) as zf:
        for item in zf.infolist():
            if not (target / item.filename).resolve().is_relative_to(target):
                raise ValueError("Unsafe archive path")
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Archive symlinks are not allowed")
        zf.extractall(target)


def prepare(home: Path) -> None:
    from huggingface_hub import hf_hub_download

    def download(name):
        print(f"Downloading {name}", flush=True)
        return Path(hf_hub_download(REPO, name, revision=REVISION))

    for name in FILES:
        source = download("pretrained_models/" + name)
        target = home / "GPT_SoVITS" / "pretrained_models" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or source.stat().st_size != target.stat().st_size:
            part = target.with_suffix(target.suffix + ".part")
            shutil.copyfile(source, part)
            part.replace(target)
    unpack(download("G2PWModel.zip"), home / "GPT_SoVITS" / "text")
    unpack(download("nltk_data.zip"), home)
    print("Inference assets ready", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("home", type=Path)
    prepare(parser.parse_args().home)
