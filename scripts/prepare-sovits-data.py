"""Install the fixed NLTK resources needed by the official English frontend."""
from __future__ import annotations

import argparse
import hashlib
import io
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

BASE = "https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/"
PACKAGES = ("cmudict", "averaged_perceptron_tagger", "averaged_perceptron_tagger_eng")


def prepare(dest: Path) -> None:
    with urllib.request.urlopen(BASE + "index.xml", timeout=60) as response:
        index = ET.fromstring(response.read())
    dest.mkdir(parents=True, exist_ok=True)
    for name in PACKAGES:
        package = index.find(f"packages/package[@id='{name}']")
        if package is None:
            raise RuntimeError(f"NLTK package missing from official index: {name}")
        subdir = package.attrib["subdir"]
        url = BASE + f"packages/{subdir}/{name}.zip"
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
        checksum = package.attrib.get("sha256_checksum")
        if not checksum or hashlib.sha256(data).hexdigest() != checksum:
            raise RuntimeError(f"NLTK checksum mismatch: {name}")
        target = (dest / subdir).resolve()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.infolist():
                if not (target / member.filename).resolve().is_relative_to(target):
                    raise RuntimeError("Unsafe NLTK archive path")
            archive.extractall(target)
        print(f"Ready: {name}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dest", type=Path)
    prepare(parser.parse_args().dest)
