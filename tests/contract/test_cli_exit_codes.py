from pathlib import Path

from typer.testing import CliRunner

from bilingual_sub.adapters.meding import MedingAuthError
from bilingual_sub.cli.main import app

runner = CliRunner()


def test_run_missing_file():
    result = runner.invoke(app, ["run", "definitely-missing-video.mp4"])
    assert result.exit_code == 1


def test_run_url_only_reaches_pipeline(monkeypatch):
    class Dummy:
        cue_count = 0
        elapsed_sec = 0
        output_srt = Path("a.srt")
        output_mp4 = None
        report_path = Path("r.json")
        missing_en: list = []

    monkeypatch.setattr("bilingual_sub.cli.main.run", lambda *_a, **_k: Dummy())
    result = runner.invoke(app, ["run", "--url", "https://youtu.be/demo", "--no-burn"])
    assert result.exit_code == 0


def test_run_401(monkeypatch, tmp_path: Path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")

    def boom(*_a, **_k):
        raise MedingAuthError("Invalid API key")

    monkeypatch.setattr("bilingual_sub.cli.main.run", boom)
    result = runner.invoke(app, ["run", str(video), "--no-burn"])
    assert result.exit_code == 3
    assert "API key" in result.output
