"""Drain diagnostics with bounded memory while owning the complete process tree."""
from __future__ import annotations

import codecs
import re
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from bilingual_sub.adapters.owned_process import owned_process
from bilingual_sub.core.control import JobControl, wait_for_process

STDERR_LIMIT = 65536


def capture_process(args: list[str], *, control: JobControl | None = None,
                    cwd: Path | None = None,
                    stderr_callback: Callable[[str], None] | None = None) -> subprocess.CompletedProcess[str]:
    if control:
        control.wait_if_paused()
    tail = bytearray()
    errors: list[BaseException] = []
    reader: threading.Thread | None = None
    proc = None

    def drain(pipe):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        pending = ""
        try:
            while chunk := pipe.read1(8192):
                tail.extend(chunk)
                if len(tail) > STDERR_LIMIT:
                    del tail[:-STDERR_LIMIT]
                if stderr_callback is not None:
                    parts = re.split(r"[\r\n]", pending + decoder.decode(chunk))
                    pending = parts.pop()
                    for line in parts:
                        if len(line) > STDERR_LIMIT:
                            raise RuntimeError("FFmpeg diagnostic line is too long")
                        stderr_callback(line)
                    if len(pending) > STDERR_LIMIT:
                        raise RuntimeError("FFmpeg diagnostic line is too long")
            if stderr_callback is not None:
                pending += decoder.decode(b"", final=True)
                if pending:
                    stderr_callback(pending)
        except BaseException as exc:
            errors.append(exc)

    def check_reader():
        if errors:
            raise errors[0]

    # stdout carries actual results (e.g. ffprobe JSON), so preserve it in full.
    # Spooling avoids blocking the worker or accumulating it while it runs.
    with tempfile.TemporaryFile() as output:
        try:
            with owned_process(args, cwd=cwd, stdin=subprocess.DEVNULL,
                               stdout=output, stderr=subprocess.PIPE) as proc:
                reader = threading.Thread(target=drain, args=(proc.stderr,), name="subflow-stderr", daemon=True)
                reader.start()
                code = wait_for_process(proc, control=control, on_tick=check_reader)
        finally:
            # Closing the owned process scope first also closes inherited pipe
            # writers held by descendants, even when the parent exited cleanly.
            if reader is not None:
                reader.join(timeout=5)
                if reader.is_alive():
                    raise RuntimeError("FFmpeg diagnostic reader did not finish")
            if proc is not None and proc.stderr is not None:
                proc.stderr.close()
        check_reader()
        output.seek(0)
        stdout = output.read().decode("utf-8", errors="replace")
    return subprocess.CompletedProcess(args, code, stdout, tail.decode("utf-8", errors="replace"))
