import json

import pytest

from bilingual_sub.core.cache_records import InvalidCache, verify_artifacts
from bilingual_sub.core.control import JobControl, JobStopped
from bilingual_sub.pipeline import _save_state


@pytest.mark.parametrize("record", [None, {}, {"../secret": "0" * 64},
                                   {"transcript.json": "bad"}, {"transcript.json": 5}])
def test_invalid_transcript_record_does_not_read_arbitrary_files(tmp_path, monkeypatch, record):
    monkeypatch.setattr("bilingual_sub.core.cache_records.file_digest",
                        lambda *a, **kw: pytest.fail("reject record before reading files"))
    with pytest.raises(InvalidCache, match="transcribe"):
        verify_artifacts(tmp_path, {"artifact_schema": 1, "artifacts": {"transcribe": record}}, "transcribe")


def test_partial_generated_glossary_is_not_a_completed_stage(tmp_path):
    with pytest.raises(InvalidCache, match="glossary"):
        verify_artifacts(tmp_path, {"artifact_schema": 1, "artifacts": {
            "glossary": {"glossary.merged.yaml": "0" * 64}}}, "glossary")


def test_cancelled_artifact_hash_keeps_previous_completion(tmp_path):
    _save_state(tmp_path, "silence", {"job_id": "same-job"})
    before = (tmp_path / "job_state.json").read_bytes()
    (tmp_path / "transcript.json").write_bytes(b"data" * 1024 * 1024)
    control = JobControl()
    control.stop()
    with pytest.raises(JobStopped):
        _save_state(tmp_path, "transcribe", {"job_id": "same-job"}, control=control,
                    produced={"transcribe": ["transcript.json"]})
    assert (tmp_path / "job_state.json").read_bytes() == before
    assert json.loads(before)["completed_stage"] == "silence"
