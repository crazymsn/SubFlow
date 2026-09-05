"""Keep nested owned process groups inside one task session on POSIX."""
from __future__ import annotations

import os
import re
import signal
import uuid
from collections.abc import Callable

import psutil

SCOPE_ENV = "SUBFLOW_POSIX_SCOPES"


class PosixScope:
    def __init__(self, send_group: Callable[[int, int], None]):
        inherited = os.environ.get(SCOPE_ENV, "").split(":")
        self.ancestors = inherited if all(re.fullmatch(r"[0-9a-f]{32}", x) for x in inherited) else []
        self.token = uuid.uuid4().hex
        self.send_group = send_group
        self.pid = 0
        self.session = 0

    def configure(self, options: dict) -> None:
        options["env"][SCOPE_ENV] = ":".join([*self.ancestors, self.token])
        options["start_new_session"] = not self.ancestors
        options.pop("process_group", None)
        if self.ancestors:
            options["process_group"] = 0

    def bind(self, pid: int) -> None:
        self.pid = pid
        self.session = os.getsid(0) if self.ancestors else pid

    def _groups(self) -> tuple[set[int], set[int]]:
        groups: set[int] = set()
        denied: set[int] = set()
        for pid in psutil.pids():
            try:
                if os.getsid(pid) != self.session:
                    continue
                proc = psutil.Process(pid)
                if proc.status() == psutil.STATUS_ZOMBIE:
                    continue
                group = os.getpgid(pid)
                # The outer scope created this session. An inner scope owns
                # its original group and descendants carrying its scope token.
                if not self.ancestors or group == self.pid or self.token in proc.environ().get(SCOPE_ENV, "").split(":"):
                    groups.add(group)
            except (ProcessLookupError, psutil.NoSuchProcess):
                continue
            except (PermissionError, psutil.AccessDenied):
                denied.add(pid)
        return groups, denied

    def signal(self, sig: int) -> None:
        groups, denied = self._groups()
        if sig in (signal.SIGSTOP, signal.SIGKILL):
            stopped: set[int] = set()
            # Stop producers before collecting newly spawned groups, then kill
            # the frozen set. This also handles grandchildren after parent exit.
            while fresh := groups - stopped:
                for group in sorted(fresh, key=lambda g: (g != self.pid, g)):
                    self.send_group(group, signal.SIGSTOP)
                stopped.update(fresh)
                groups, blocked = self._groups()
                denied.update(blocked)
            groups = stopped
        if sig != signal.SIGSTOP:
            for group in groups:
                self.send_group(group, sig)
        if denied:
            raise PermissionError(f"Cannot verify owned process groups for PIDs: {sorted(denied)}")
