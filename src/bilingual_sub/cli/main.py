from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from bilingual_sub.adapters.ffmpeg import (
    FfmpegError,
    ffmpeg_version,
    find_ffprobe,
    has_nvenc,
    parse_ffmpeg_major,
)
from bilingual_sub.adapters.meding import MedingAuthError, create_client
from bilingual_sub.adapters.whisper_backend import load_transcript, probe_whisper, transcribe
from bilingual_sub.brand import CLI_NAME, PRODUCT_FULL, TAGLINE
from bilingual_sub.config import (
    bundled_fonts_dir,
    default_glossary_path,
    load_settings,
    load_style_preset,
    save_user_overrides,
)
from bilingual_sub.core.audio import detect_silences, extract_wav
from bilingual_sub.core.burn import burn_subtitles
from bilingual_sub.core.cues import build_cues
from bilingual_sub.core.glossary import Glossary
from bilingual_sub.core.render import load_cues_json, save_cues_json, write_subtitles
from bilingual_sub.core.translate import translate_cues
from bilingual_sub.models import STAGES, JobConfig
from bilingual_sub.pipeline import run
from bilingual_sub.secrets.store import delete_api_key, get_api_key, mask_api_key, set_api_key

app = typer.Typer(
    name=CLI_NAME,
    help=f"{PRODUCT_FULL} — {TAGLINE}",
    no_args_is_help=True,
)
config_app = typer.Typer(help="Manage local API key and preferred model (this machine only).")
app.add_typer(config_app, name="config")

console = Console()


def _exit(code: int) -> None:
    raise typer.Exit(code)


@config_app.command("set-api-key")
def config_set_api_key(
    key: Annotated[
        str | None,
        typer.Option("--key", "-k", help="API key (prompted if omitted)"),
    ] = None,
) -> None:
    """Save meding API key locally."""
    if not key:
        key = typer.prompt("API key", hide_input=True)
    try:
        set_api_key(key)
        console.print("[green]API key saved locally.[/green]")
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        _exit(1)
    try:
        _print_remote_models(key)
    except typer.Exit:
        console.print("[yellow]Key 已保存。稍后执行 subflow models 拉取列表。[/yellow]")


@config_app.command("show")
def config_show() -> None:
    """Show masked API key status."""
    console.print(f"API key: {mask_api_key(get_api_key())}")


@config_app.command("delete-api-key")
def config_delete() -> None:
    """Remove stored API key."""
    delete_api_key()
    console.print("[green]API key deleted.[/green]")


def _print_remote_models(key: str | None = None) -> list[str]:
    token = key or get_api_key()
    if not token:
        console.print("[red]API key not configured.[/red]")
        _exit(3)
    try:
        models = create_client(token).list_models()
    except MedingAuthError as exc:
        console.print(f"[red]{exc}[/red]")
        _exit(3)
    except Exception as exc:
        console.print(f"[red]Failed to list models: {exc}[/red]")
        _exit(4)
    if not models:
        console.print("[yellow]No models returned. You can still pass --translate-model manually.[/yellow]")
        return []
    console.print(f"[green]{len(models)} model(s) available:[/green]")
    for mid in models:
        console.print(f"  • {mid}")
    current = load_settings().translate.model
    if current not in models:
        save_user_overrides({"translate": {"model": models[0]}})
        console.print(f"[dim]Default model set to {models[0]}[/dim]")
    return models


@config_app.command("set-model")
def config_set_model(
    model: Annotated[str, typer.Argument(help="Model id from `subflow models`")],
) -> None:
    """Remember preferred translation model."""
    save_user_overrides({"translate": {"model": model}})
    console.print(f"[green]Preferred model: {model}[/green]")


@app.command("models")
def models_cmd() -> None:
    """Fetch translation models for the saved API key."""
    _print_remote_models()


@app.command()
def doctor() -> None:
    """Check ffmpeg, whisper, fonts, and meding API connectivity."""
    table = Table(title=f"{PRODUCT_FULL} doctor")
    table.add_column("Check")
    table.add_column("Status")
    ok = True

    try:
        ver = ffmpeg_version()
        major = parse_ffmpeg_major(ver)
        if major is not None and major < 6:
            table.add_row("ffmpeg", f"[red]FAIL[/red] need >= 6.0 ({ver[:50]})")
            ok = False
        else:
            table.add_row("ffmpeg", f"[green]OK[/green] {ver[:60]}")
    except FfmpegError as exc:
        table.add_row("ffmpeg", f"[red]FAIL[/red] {exc}")
        ok = False

    try:
        find_ffprobe()
        table.add_row("ffprobe", "[green]OK[/green]")
    except FfmpegError as exc:
        table.add_row("ffprobe", f"[red]FAIL[/red] {exc}")
        ok = False

    nvenc = False
    try:
        nvenc = has_nvenc()
    except FfmpegError:
        pass
    table.add_row(
        "NVENC",
        "[green]available[/green]" if nvenc else "[yellow]not found (will use libx264)[/yellow]",
    )

    if probe_whisper("tiny"):
        table.add_row("whisper", "[green]OK[/green] (tiny model loaded)")
    else:
        table.add_row("whisper", "[red]FAIL[/red] pip install subflow[cuda] 或使用 Docker")
        ok = False

    fonts = bundled_fonts_dir()
    if fonts.is_dir() and any(fonts.iterdir()):
        table.add_row("fonts", f"[green]OK[/green] {fonts}")
    else:
        table.add_row("fonts", f"[red]FAIL[/red] empty {fonts}")
        ok = False

    probe_dir = Path(tempfile.gettempdir()) / "bilingual-sub-probe"
    try:
        probe_dir.mkdir(parents=True, exist_ok=True)
        marker = probe_dir / "write-test.txt"
        marker.write_text("ok", encoding="utf-8")
        marker.unlink(missing_ok=True)
        table.add_row("temp", f"[green]OK[/green] {probe_dir}")
    except OSError as exc:
        table.add_row("temp", f"[red]FAIL[/red] {exc}")
        ok = False

    key = get_api_key()
    if not key:
        table.add_row("API key", "[red]not configured[/red]")
        ok = False
    else:
        try:
            client = create_client(key)
            models = client.list_models()
            if models:
                table.add_row("meding API", f"[green]OK[/green] {len(models)} models")
            elif client.healthcheck():
                table.add_row("meding API", "[yellow]reachable, empty model list[/yellow]")
            else:
                table.add_row("meding API", "[yellow]reachable but healthcheck failed[/yellow]")
        except MedingAuthError as exc:
            table.add_row("meding API", f"[red]FAIL[/red] {exc}")
            ok = False
        except Exception as exc:
            table.add_row("meding API", f"[red]FAIL[/red] {exc}")
            ok = False

    console.print(table)
    if not ok:
        _exit(2)


@app.command("run")
def run_cmd(
    input_video: Annotated[Path | None, typer.Argument(help="Input video file")] = None,
    output: Annotated[Path | None, typer.Option("-o", "--output", help="Output MP4")] = None,
    srt: Annotated[Path | None, typer.Option("--srt", help="Output SRT path")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    preset: Annotated[str, typer.Option("--preset")] = "no-plate-large",
    whisper_model: Annotated[str, typer.Option("--whisper-model")] = "medium",
    device: Annotated[str, typer.Option("--device")] = "auto",
    glossary: Annotated[Path | None, typer.Option("--glossary")] = None,
    no_burn: Annotated[bool, typer.Option("--no-burn", help="Skip FFmpeg burn-in")] = False,
    resume_from: Annotated[str | None, typer.Option("--resume-from")] = None,
    preview_minutes: Annotated[float | None, typer.Option("--preview-minutes")] = None,
    translate_model: Annotated[
        str | None,
        typer.Option("--translate-model", "--model", help="Translation model (default: saved preference)"),
    ] = None,
    source_lang: Annotated[str, typer.Option("--source-lang")] = "zh",
    target_lang: Annotated[str, typer.Option("--target-lang")] = "zh",
    subtitle_mode: Annotated[str, typer.Option("--subtitle-mode")] = "bilingual",
    asr_backend: Annotated[str, typer.Option("--asr-backend")] = "whisper",
    refine: Annotated[bool, typer.Option("--refine", help="3-step translate-reflect-adapt")] = False,
    url: Annotated[str | None, typer.Option("--url", help="YouTube / video URL")] = None,
    glossary_generate: Annotated[bool, typer.Option("--glossary-generate")] = False,
    enable_dub: Annotated[bool, typer.Option("--dub")] = False,
    tts_provider: Annotated[str, typer.Option("--tts-provider")] = "none",
    tts_voice: Annotated[str, typer.Option("--tts-voice")] = "",
    tts_endpoint: Annotated[str, typer.Option("--tts-endpoint")] = "",
    zh_color: Annotated[str, typer.Option("--zh-color", help="Chinese subtitle hex color")] = "#FFFFFF",
    en_color: Annotated[str, typer.Option("--en-color", help="English subtitle hex color")] = "#F2F2F2",
) -> None:
    """Full pipeline: ASR → translate → render → burn."""
    if not url and (input_video is None or not input_video.is_file()):
        console.print(f"[red]File not found: {input_video}[/red]")
        _exit(1)
    from bilingual_sub.core.langs import effective_target_lang, is_valid_subtitle_mode

    if not is_valid_subtitle_mode(subtitle_mode):
        console.print("[red]--subtitle-mode must be bilingual, enzh, netflix_single, or single:<lang>[/red]")
        _exit(1)
    target_lang = effective_target_lang(source_lang, target_lang, subtitle_mode)
    if asr_backend not in ("whisper", "whisperx"):
        console.print("[red]--asr-backend must be whisper or whisperx[/red]")
        _exit(1)
    if tts_provider not in ("none", "openai", "azure", "gptsovits"):
        console.print("[red]--tts-provider must be none, openai, azure, or gptsovits[/red]")
        _exit(1)
    if device not in ("auto", "cuda", "cpu"):
        console.print("[red]--device must be auto, cuda, or cpu[/red]")
        _exit(1)
    if resume_from and resume_from not in STAGES:
        console.print(f"[red]--resume-from must be one of: {', '.join(STAGES)}[/red]")
        _exit(1)

    settings = load_settings()
    chosen_model = translate_model or settings.translate.model
    source = input_video.resolve() if input_video else Path(url or "source.mp4")
    out_srt = srt or source.with_name(source.stem + ".bilingual.srt")
    out_mp4 = output or source.with_name(source.stem + "-中英字幕.mp4")

    cfg = JobConfig(
        input_video=source,
        output_video=None if no_burn else out_mp4.resolve(),
        output_srt=out_srt.resolve(),
        work_dir=work_dir or Path("auto"),
        glossary_path=glossary or default_glossary_path(),
        style_preset=preset,
        whisper_model=whisper_model,
        device=device,  # type: ignore[arg-type]
        burn=not no_burn,
        resume_from=resume_from,
        preview_minutes=preview_minutes,
        translate_model=chosen_model,
        source_lang=source_lang,
        target_lang=target_lang,
        subtitle_mode=subtitle_mode,
        asr_backend=asr_backend,  # type: ignore[arg-type]
        refine_translate=refine,
        source_url=None if (input_video and input_video.is_file()) else url,
        glossary_generate=glossary_generate,
        enable_dub=enable_dub,
        tts_provider=tts_provider,  # type: ignore[arg-type]
        tts_voice=tts_voice,
        tts_endpoint=tts_endpoint,
        subtitle_zh_color=zh_color,
        subtitle_en_color=en_color,
    )

    def on_progress(stage: str, pct: float) -> None:
        console.print(f"  [{pct * 100:5.1f}%] {stage}")

    try:
        result = run(cfg, on_progress=on_progress)
    except MedingAuthError as exc:
        console.print(f"[red]API key error: {exc}[/red]")
        _exit(3)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        if "API key" in str(exc) or "401" in str(exc):
            _exit(3)
        _exit(4)

    console.print(f"[green]Done[/green] cues={result.cue_count} elapsed={result.elapsed_sec:.1f}s")
    console.print(f"  SRT: {result.output_srt}")
    if result.output_mp4:
        console.print(f"  MP4: {result.output_mp4}")
    console.print(f"  Report: {result.report_path}")
    if result.missing_en:
        console.print(f"[yellow]missing_en: {len(result.missing_en)}[/yellow]")
        _exit(5)


@app.command()
def extract(
    input_video: Path,
    output_dir: Annotated[Path, typer.Option("-o", "--output-dir")],
    preview_minutes: Annotated[float | None, typer.Option("--preview-minutes")] = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    wav = output_dir / "speech.wav"
    preview = preview_minutes * 60 if preview_minutes else None
    extract_wav(input_video, wav, preview_sec=preview)
    silences = detect_silences(wav)
    sil_path = output_dir / "silences.json"
    sil_path.write_text(json.dumps(silences), encoding="utf-8")
    console.print(f"Wrote {wav}")
    console.print(f"Wrote {sil_path} ({len(silences)} islands)")


@app.command("transcribe")
def transcribe_cmd(
    wav: Path,
    output: Annotated[Path, typer.Option("-o", "--output")],
    model: Annotated[str, typer.Option("--model")] = "medium",
    device: Annotated[str, typer.Option("--device")] = "auto",
) -> None:
    transcribe(wav, model_name=model, device=device, out_json=output)
    console.print(f"Wrote {output}")


@app.command("build-cues")
def build_cues_cmd(
    transcript: Path,
    silences: Path,
    output: Annotated[Path, typer.Option("-o", "--output")],
    glossary: Annotated[Path | None, typer.Option("--glossary")] = None,
) -> None:
    settings = load_settings()
    segments = load_transcript(transcript)
    sil = [tuple(x) for x in json.loads(silences.read_text())]
    glo = Glossary.load(glossary or default_glossary_path())
    cues = build_cues(
        segments,
        sil,
        glo,
        snap_tolerance=settings.cues.snap_tolerance,
        min_duration=settings.cues.min_duration,
        max_duration=settings.cues.max_duration,
        silence_split_threshold=settings.cues.silence_split_threshold,
    )
    save_cues_json(cues, output)
    console.print(f"Wrote {len(cues)} cues -> {output}")


@app.command("translate")
def translate_cmd(
    cues_path: Path,
    output: Annotated[Path, typer.Option("-o", "--output")],
    model: Annotated[str | None, typer.Option("--model")] = None,
) -> None:
    cues = load_cues_json(cues_path)
    settings = load_settings()
    out, stats, missing = translate_cues(
        cues,
        model=model or settings.translate.model,
        batch_size=settings.translate.batch_size,
        max_en_chars=settings.translate.max_en_chars,
    )
    save_cues_json(out, output)
    console.print(f"Translated -> {output} (missing={len(missing)}, api_calls={stats.api_calls})")


@app.command()
def render(
    cues_path: Path,
    output_ass: Annotated[Path, typer.Option("-o", "--output")],
    srt: Annotated[Path | None, typer.Option("--srt")] = None,
    preset: Annotated[str, typer.Option("--preset")] = "no-plate-large",
) -> None:
    cues = load_cues_json(cues_path)
    p = load_style_preset(preset)
    srt_path = srt or output_ass.with_suffix(".srt")
    write_subtitles(cues, p, output_ass, srt_path)
    console.print(f"Wrote {output_ass} and {srt_path}")


@app.command()
def burn(
    video: Path,
    ass_file: Path,
    output: Annotated[Path, typer.Option("-o", "--output")],
) -> None:
    settings = load_settings()
    burn_subtitles(
        video,
        ass_file,
        output,
        encoder=settings.burn.encoder,
        cq=settings.burn.cq,
        preset=settings.burn.preset,
    )
    console.print(f"Wrote {output}")


@app.command()
def gui() -> None:
    """Launch desktop GUI."""
    try:
        from bilingual_sub.gui.app import main as gui_main
    except ImportError:
        console.print("[red]GUI requires: pip install subflow[gui][/red]")
        _exit(2)
    gui_main()


if __name__ == "__main__":
    app()
