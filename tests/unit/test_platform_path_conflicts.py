import sys
from pathlib import PurePosixPath
from types import SimpleNamespace

import pytest

from bilingual_sub.core import file_io
from bilingual_sub.core import output_guard as guard
from bilingual_sub.core import resource_claims as claims


class MissingPosixPath:
    """An absent POSIX path, without pretending the host has a Mac filesystem."""
    def __init__(self, name):
        self.name = name

    def resolve(self):
        return PurePosixPath(self.name)

    def samefile(self, other):
        raise FileNotFoundError(self.name)

    def exists(self):
        return False

    @property
    def parent(self):
        pytest.fail("output preparation began before detecting a duplicate path")

    def __str__(self):
        return self.name


@pytest.fixture
def mac_policy(monkeypatch):
    # Replace module attributes, never the global sys.platform used by pathlib.
    monkeypatch.setattr(guard, "sys", SimpleNamespace(platform="darwin"), raising=False)
    monkeypatch.setattr(claims, "sys", SimpleNamespace(platform="darwin"), raising=False)


@pytest.mark.parametrize("left,right", [
    ("/out/movie.srt", "/out/MOVIE.SRT"),
    ("/Out/movie.srt", "/out/movie.srt"),
    ("/out/caf\u00e9.srt", "/out/cafe\u0301.srt"),
    ("/out/\u00e9/movie.srt", "/out/e\u0301/movie.srt"),
])
@pytest.mark.parametrize("operation", ["outputs", "input", "commit"])
def test_missing_mac_aliases_rejected_before_writes(mac_policy, left, right, operation):
    a, b = MissingPosixPath(left), MissingPosixPath(right)
    with pytest.raises(ValueError):
        if operation == "outputs":
            guard.validate_outputs({"ASS": a, "SRT": b}, [])
        elif operation == "input":
            guard.validate_outputs({"ASS": a}, [b])
        else:
            file_io.write_text_files([(a, "one", "utf-8"), (b, "two", "utf-8")])


@pytest.mark.parametrize("left,right", [
    ("/out/movie.srt", "/out/MOVIE.SRT"),
    ("/out/caf\u00e9.srt", "/out/cafe\u0301.srt"),
])
def test_reservation_equivalence_is_not_file_identity(mac_policy, left, right):
    assert not guard.same_file(MissingPosixPath(left), MissingPosixPath(right))


def test_resource_keys_reserve_unicode_equivalent_names(mac_policy):
    assert claims._key("/out/caf\u00e9.srt") == claims._key("/out/cafe\u0301.srt")


@pytest.mark.parametrize("tree", [False, True])
def test_mac_unicode_claims_block_overlapping_jobs(mac_policy, tmp_path, tree):
    first, second = tmp_path / "caf\u00e9", tmp_path / "cafe\u0301"
    with claims.claim_resources(reads=[], writes=[] if tree else [first], trees=[first] if tree else []):
        with pytest.raises(RuntimeError, match="另一任务|正在被另一任务"):
            with claims.claim_resources(reads=[], writes=[second / "out.srt" if tree else second]):
                pytest.fail("second writer acquired an equivalent Mac path")


@pytest.mark.parametrize("aliases", [("a.ass", "A.ASS"), ("caf\u00e9.srt", "cafe\u0301.srt")])
def test_host_alias_policy_preserves_distinct_outputs(tmp_path, aliases):
    """On CI this exercises the native volume, including both macOS runners."""
    a, b = (tmp_path / name for name in aliases)
    a.write_bytes(b"probe")
    native_alias = b.exists() and a.samefile(b)
    a.unlink()
    if native_alias:
        with pytest.raises(ValueError):
            file_io.write_text_files([(a, "first", "utf-8"), (b, "second", "utf-8")])
        assert not a.exists() and not b.exists()
    elif sys.platform == "darwin":
        # A Mac case-sensitive volume still gets conservative reservations.
        with pytest.raises(ValueError):
            file_io.write_text_files([(a, "first", "utf-8"), (b, "second", "utf-8")])
    else:
        file_io.write_text_files([(a, "first", "utf-8"), (b, "second", "utf-8")])
        assert a.read_text() == "first" and b.read_text() == "second"


def test_missing_distinct_outputs_still_commit(tmp_path):
    a, b = tmp_path / "one.ass", tmp_path / "two.srt"
    file_io.write_text_files([(a, "first", "utf-8"), (b, "second", "utf-8")])
    assert a.read_text() == "first" and b.read_text() == "second"


def test_actual_hardlinks_remain_same_file(tmp_path):
    a, b = tmp_path / "source", tmp_path / "link"
    a.write_bytes(b"contents")
    b.hardlink_to(a)
    assert guard.same_file(a, b)
    file_io.copy_file(a, b)
    assert a.samefile(b)
