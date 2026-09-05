from types import SimpleNamespace

import psutil
import pytest

import bilingual_sub.adapters.owned_process as owned


@pytest.mark.parametrize("status", [psutil.STATUS_ZOMBIE, psutil.STATUS_RUNNING])
def test_group_permission_error_is_ignored_only_without_live_members(monkeypatch, status):
    monkeypatch.setattr(owned.sys, "platform", "darwin")
    monkeypatch.setattr(owned.signal, "SIGKILL", 9, raising=False)
    def denied(*args):
        raise PermissionError("group cannot be signalled")
    monkeypatch.setattr(owned.os, "killpg", denied, raising=False)
    monkeypatch.setattr(owned.os, "getpgid", lambda pid: 100 if pid == 101 else 200, raising=False)
    monkeypatch.setattr(owned.psutil, "pids", lambda: [201, 101])
    monkeypatch.setattr(owned.psutil, "Process", lambda pid: SimpleNamespace(status=lambda: status))
    if status == psutil.STATUS_RUNNING:
        with pytest.raises(PermissionError):
            owned._kill_owned_group(100)
    else:
        owned._kill_owned_group(100)


def test_disappearing_group_member_during_cleanup(monkeypatch):
    monkeypatch.setattr(owned.sys, "platform", "darwin")
    monkeypatch.setattr(owned.signal, "SIGKILL", 9, raising=False)
    def denied(*args):
        raise PermissionError("group exited")
    def gone(*args):
        raise ProcessLookupError()
    monkeypatch.setattr(owned.os, "killpg", denied, raising=False)
    monkeypatch.setattr(owned.os, "getpgid", gone, raising=False)
    monkeypatch.setattr(owned.psutil, "pids", lambda: [101])
    owned._kill_owned_group(100)
