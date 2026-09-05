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

    monkeypatch.setattr("bilingual_sub.cli.main.get_api_key", lambda: "sk-test")
    monkeypatch.setattr("bilingual_sub.cli.main.run", lambda *_a, **_k: Dummy())
    result = runner.invoke(app, ["run", "--url", "https://youtu.be/demo", "--no-burn"])
    assert result.exit_code == 0


def test_run_url_default_outputs_are_local(monkeypatch):
    seen: dict = {}

    class Dummy:
        cue_count = 0
        elapsed_sec = 0
        output_srt = Path("a.srt")
        output_mp4 = None
        report_path = Path("r.json")
        missing_en: list = []

    def capture(cfg, **_k):
        seen["cfg"] = cfg
        return Dummy()

    monkeypatch.setattr("bilingual_sub.cli.main.get_api_key", lambda: "sk-test")
    monkeypatch.setattr("bilingual_sub.cli.main.run", capture)
    result = runner.invoke(app, ["run", "--url", "https://youtu.be/abc123XYZ", "--no-burn"])
    assert result.exit_code == 0
    cfg = seen["cfg"]
    assert "youtu.be" not in str(cfg.output_srt)
    assert "abc123XYZ" in cfg.output_srt.name
    assert cfg.output_srt.name.endswith("-中英字幕.bilingual.srt")
    assert cfg.output_video is None


def test_run_bilingual_without_key_exits_before_pipeline(monkeypatch, tmp_path: Path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr("bilingual_sub.cli.main.get_api_key", lambda: None)

    def boom(*_a, **_k):
        raise AssertionError("pipeline should not start without a translation key")

    monkeypatch.setattr("bilingual_sub.cli.main.run", boom)
    result = runner.invoke(app, ["run", str(video), "--no-burn"])
    assert result.exit_code == 3
    assert "API key" in result.output


def test_run_401(monkeypatch, tmp_path: Path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")

    def boom(*_a, **_k):
        raise MedingAuthError("Invalid API key")

    monkeypatch.setattr("bilingual_sub.cli.main.run", boom)
    result = runner.invoke(app, ["run", str(video), "--no-burn"])
    assert result.exit_code == 3
    assert "API key" in result.output


def test_run_dub_loads_saved_gptsovits_settings(monkeypatch, tmp_path: Path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF....WAVE")
    seen: dict = {}

    class Dummy:
        cue_count = 0
        elapsed_sec = 0
        output_srt = Path("a.srt")
        output_mp4 = None
        report_path = Path("r.json")
        missing_en: list = []

    def capture(cfg, **_k):
        seen["cfg"] = cfg
        return Dummy()

    monkeypatch.setattr("bilingual_sub.cli.main.get_api_key", lambda: "sk-test")
    monkeypatch.setattr("bilingual_sub.cli.main.run", capture)
    monkeypatch.setattr(
        "bilingual_sub.config.load_gptsovits_settings",
        lambda: {
            "endpoint": "http://127.0.0.1:9880",
            "ref_audio": str(ref),
            "prompt_text": "参考台词",
            "prompt_lang": "zh",
        },
    )
    result = runner.invoke(
        app,
        [
            "run",
            str(video),
            "--no-burn",
            "--dub",
            "--source-lang",
            "zh",
            "--target-lang",
            "en",
            "--subtitle-mode",
            "single:zh",
        ],
    )
    assert result.exit_code == 0
    cfg = seen["cfg"]
    assert cfg.tts_provider == "gptsovits"
    assert cfg.tts_ref_audio == str(ref)
    assert cfg.tts_prompt_text == "参考台词"
    assert cfg.tts_endpoint == "http://127.0.0.1:9880"
    assert cfg.tts_prompt_lang == "zh"


def test_run_dub_auto_source_skips_saved_prompt_lang(monkeypatch, tmp_path: Path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF....WAVE")
    seen: dict = {}

    class Dummy:
        cue_count = 0
        elapsed_sec = 0
        output_srt = Path("a.srt")
        output_mp4 = None
        report_path = Path("r.json")
        missing_en: list = []

    def capture(cfg, **_k):
        seen["cfg"] = cfg
        return Dummy()

    monkeypatch.setattr("bilingual_sub.cli.main.get_api_key", lambda: "sk-test")
    monkeypatch.setattr("bilingual_sub.cli.main.run", capture)
    monkeypatch.setattr(
        "bilingual_sub.config.load_gptsovits_settings",
        lambda: {
            "endpoint": "http://127.0.0.1:9880",
            "ref_audio": str(ref),
            "prompt_text": "参考台词",
            "prompt_lang": "zh",
        },
    )
    result = runner.invoke(
        app,
        [
            "run",
            str(video),
            "--no-burn",
            "--dub",
            "--source-lang",
            "auto",
            "--target-lang",
            "en",
            "--subtitle-mode",
            "single:zh",
        ],
    )
    assert result.exit_code == 0
    assert seen["cfg"].tts_prompt_lang == ""
