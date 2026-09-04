"""ASR facade — Whisper lives in adapters.whisper_backend."""

from bilingual_sub.adapters.whisper_backend import load_transcript, probe_whisper, transcribe

__all__ = ["load_transcript", "probe_whisper", "transcribe"]
