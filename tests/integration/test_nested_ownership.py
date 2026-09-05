import json
import os
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

import psutil
import pytest

from bilingual_sub.adapters.owned_process import owned_process
from bilingual_sub.core.control import JobControl

WORKER = '''import json,os,sys,time,subprocess
from pathlib import Path
import psutil
from bilingual_sub.adapters.owned_process import owned_process
from bilingual_sub.core.control import JobControl
folder=Path(sys.argv[1]); mode=sys.argv[2]; name=sys.argv[3]
def ready(name):
    deadline=time.monotonic()+8
    while not (folder/(name+'.json')).exists():
        if time.monotonic()>deadline: raise RuntimeError('child not ready')
        time.sleep(.02)
def spawn(mode,name):
    env={k:v for k,v in os.environ.items() if not k.startswith('SUBFLOW_')}
    return owned_process([sys.executable,__file__,str(folder),mode,name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env)
if mode=='leaf':
    p=psutil.Process()
    (folder/(name+'.json')).write_text(json.dumps({'pid':p.pid,'created':p.create_time()}))
    while True:
        with (folder/(name+'.ticks')).open('ab') as stream: stream.write(b'x')
        time.sleep(.03)
elif mode.startswith('deep-'):
    with spawn('wait','middle'):
        ready('leaf')
        if mode=='deep-exit': os._exit(0)
        while True: time.sleep(.05)
elif mode=='inner-pause':
    with spawn('leaf','sibling'), spawn('wait','branch') as branch:
        ready('sibling'); ready('leaf')
        control=JobControl(); control.attach_proc(branch)
        control.pause(); time.sleep(.2)
        counts=[(folder/(n+'.ticks')).stat().st_size for n in ('leaf','sibling')]
        time.sleep(.3)
        after=[(folder/(n+'.ticks')).stat().st_size for n in ('leaf','sibling')]
        assert counts[0]==after[0] and after[1]>counts[1], (counts,after)
        control.resume(); time.sleep(.3)
        assert (folder/'leaf.ticks').stat().st_size>after[0]
        (folder/'pause-verified').touch()
        while True: time.sleep(.05)
elif mode=='siblings':
    with spawn('leaf','sibling'):
        ready('sibling')
        with spawn('exit','branch') as branch:
            ready('leaf'); branch.wait(timeout=8)
        (folder/'branch-closed').touch()
        while True: time.sleep(.05)
else:
    with spawn('leaf','leaf'):
        ready('leaf')
        if mode in ('exit','crash'): os._exit(0 if mode=='exit' else 7)
        while True: time.sleep(.05)
'''


def wait_until(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.03)
    assert predicate(), "process condition did not become true"


def alive(folder, name):
    info = json.loads((folder / f"{name}.json").read_text())
    try:
        p = psutil.Process(info["pid"])
        return p.create_time() == info["created"] and p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


@contextmanager
def parent(tmp_path, mode):
    script = tmp_path / "worker.py"
    script.write_text(WORKER, encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parents[2] / "src") + os.pathsep + env.get("PYTHONPATH", "")
    try:
        with ExitStack() as owner:
            proc = owner.enter_context(owned_process(
                [sys.executable, str(script), str(tmp_path), mode, "parent"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env))
            wait_until(lambda: (tmp_path / "leaf.json").exists())
            yield proc, owner
    finally:
        # Match known child birth times; failed baseline tests must also clean up.
        for file in tmp_path.glob("*.json"):
            try:
                info = json.loads(file.read_text())
                child = psutil.Process(info["pid"])
                if child.create_time() == info["created"]:
                    child.kill()
                    child.wait(timeout=3)
            except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                pass


@pytest.mark.parametrize("mode", ["exit", "crash", "stop", "deep-exit", "deep-stop"])
def test_outer_exit_cleans_nested_scope(tmp_path, mode):
    control = JobControl()
    with parent(tmp_path, mode) as (proc, owner):
        if mode in ("stop", "deep-stop"):
            control.attach_proc(proc)
            control.stop()
            control.detach_proc(proc)
        proc.wait(timeout=8)
        owner.close()
        wait_until(lambda: not alive(tmp_path, "leaf"), timeout=2)


def test_pause_resume_reaches_nested_scope(tmp_path):
    control = JobControl()
    with parent(tmp_path, "wait") as (proc, _):
        control.attach_proc(proc)
        try:
            counter = tmp_path / "leaf.ticks"
            wait_until(counter.exists)
            control.pause()
            time.sleep(.15)
            before = counter.stat().st_size
            time.sleep(.25)
            assert counter.stat().st_size == before
            control.resume()
            wait_until(lambda: counter.stat().st_size > before)
        finally:
            control.stop()
            control.detach_proc(proc)


def test_inner_cleanup_preserves_sibling_scope(tmp_path):
    with parent(tmp_path, "siblings"):
        wait_until(lambda: (tmp_path / "branch-closed").exists())
        wait_until(lambda: not alive(tmp_path, "leaf"), timeout=2)
        assert alive(tmp_path, "sibling")
        counter = tmp_path / "sibling.ticks"
        before = counter.stat().st_size
        wait_until(lambda: counter.stat().st_size > before)


def test_inner_pause_preserves_sibling_and_resumes_descendants(tmp_path):
    with parent(tmp_path, "inner-pause"):
        wait_until(lambda: (tmp_path / "pause-verified").exists())
