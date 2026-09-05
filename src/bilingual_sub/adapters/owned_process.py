"""Contain a worker and its descendants for the lifetime of one task."""
from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
from contextlib import contextmanager

import psutil

from bilingual_sub.adapters.procwin import hidden_run_kwargs


def _signal_owned_group(pid: int, sig: int) -> None:
    if sys.platform == "win32":
        raise NotImplementedError("POSIX process groups are unavailable on Windows")
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        return
    except PermissionError:
        # Darwin can report EPERM for a group containing only exiting zombies.
        # Suppress that race only after verifying that no live member remains.
        for candidate in psutil.pids():
            try:
                if os.getpgid(candidate) == pid and psutil.Process(candidate).status() != psutil.STATUS_ZOMBIE:
                    raise
            except (ProcessLookupError, psutil.NoSuchProcess):
                continue


def _kill_owned_group(pid: int) -> None:
    _signal_owned_group(pid, signal.SIGKILL)


class _WindowsJob:
    def __init__(self) -> None:
        from ctypes import wintypes as w

        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", w.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                        ("active", w.DWORD), ("affinity", ctypes.c_size_t),
                        ("priority", w.DWORD), ("scheduling", w.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t),
                        ("peak_job", ctypes.c_size_t)]

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.api.CreateJobObjectW.restype = w.HANDLE
        self.api.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.api.SetInformationJobObject.restype = w.BOOL
        self.api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.api.AssignProcessToJobObject.restype = w.BOOL
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.api.CloseHandle.restype = w.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, proc: subprocess.Popen) -> None:
        if not self.api.AssignProcessToJobObject(self.handle, int(getattr(proc, "_handle"))):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


@contextmanager
def owned_process(args: list[str], **kwargs):
    options = hidden_run_kwargs()
    options.update(kwargs)
    environment = options.get("env")
    options["env"] = dict(os.environ if environment is None else environment)
    options["env"]["SUBFLOW_WORKER_PROCESS_GROUP"] = "1"
    job = _WindowsJob() if os.name == "nt" else None
    scope = None
    proc = None
    try:
        if job:
            # Contain the suspended process before it can create descendants.
            options["creationflags"] = options.get("creationflags", 0) | 0x4  # CREATE_SUSPENDED
        else:
            from bilingual_sub.adapters.posix_scope import PosixScope

            scope = PosixScope(_signal_owned_group)
            scope.configure(options)
        proc = subprocess.Popen(args, **options)
        if job:
            job.assign(proc)
            psutil.Process(proc.pid).resume()
        elif scope:
            scope.bind(proc.pid)
            proc._subflow_posix_scope = scope
        yield proc
    finally:
        try:
            if job:
                job.close()
            elif proc is not None and scope is not None:
                scope.signal(signal.SIGKILL)
        finally:
            if proc is not None:
                if proc.poll() is None:
                    proc.kill()
                proc.wait(timeout=10)
