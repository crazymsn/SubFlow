"""Validate shared API/library inference inputs before touching model state."""
import math


class NoSpeechError(ValueError):
    pass


class SynthesisStopped(Exception):
    pass


def validate_request(request):
    text = request.get("text")
    if not isinstance(text, str) or not text.strip():
        raise NoSpeechError("text must contain non-whitespace characters")
    for name, default, minimum, maximum in (
        ("top_k", 15, 0, None), ("batch_size", 1, 1, None),
        ("sample_steps", 32, 1, None), ("overlap_length", 2, 1, None),
        ("min_chunk_length", 16, 1, None), ("seed", -1, -1, 2**32 - 1),
    ):
        value = request.get(name, default)
        if name == "seed" and value in (None, ""):
            value = -1
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum or (maximum is not None and value > maximum):
            raise ValueError(f"{name} must be an integer >= {minimum}" + (f" and <= {maximum}" if maximum is not None else ""))
    for name, default, minimum, inclusive, maximum in (
        ("top_p", 1.0, 0, True, 1), ("batch_threshold", 0.75, 0, True, 1),
        ("temperature", 1.0, 0, False, None), ("speed_factor", 1.0, 0, False, None),
        ("repetition_penalty", 1.35, 0, False, None), ("fragment_interval", 0.3, 0, True, None),
    ):
        value = request.get(name, default)
        try:
            finite = not isinstance(value, bool) and isinstance(value, (float, int)) and math.isfinite(value)
        except OverflowError:
            finite = False
        if (not finite or (value < minimum if inclusive else value <= minimum)
                or (maximum is not None and value > maximum)):
            lower = ">=" if inclusive else ">"
            raise ValueError(f"{name} must be finite and {lower} {minimum}" + (f" and <= {maximum}" if maximum is not None else ""))


def require_speech_segments(segments):
    if not segments:
        raise NoSpeechError("Text preprocessing produced no speakable segments")
