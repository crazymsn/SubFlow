from pathlib import Path

from typer.testing import CliRunner

from bilingual_sub.adapters.meding import MedingAuthError
from bilingual_sub.cli.main import app

runner = CliRunner()


def test_run_missing_file():
    result = runner.invoke(app, ["run", "definitely-missing-video.mp4"])
    assert result.exit_code == 1


def test_run_401(monkeypatch, tmp_path: Path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")

    def boom(*_a, **_k):
        raise MedingAuthError("Invalid API key")

    monkeypatch.setattr("bilingual_sub.cli.main.run", boom)
    result = runner.invoke(app, ["run", str(video), "--no-burn"])
    assert result.exit_code == 3
    assert "API key" in result.output
