"""Bounded shell-free process wall/RSS measurement for the accuracy sweep."""

import hashlib
import os
from pathlib import Path
import signal
import subprocess
import time


def live_processes(proc=Path("/proc")):
    """Namespace-local (PID, process group) pairs for live processes.

    A container can inherit an ancestor's procfs mount. Its stat PIDs/groups then
    differ from getpid()/killpg(); NSpid/NSpgid provide the local IDs. Matching
    the PID namespace first prevents aliases from another container's group.
    """
    try:
        namespace = os.readlink(proc / "self/ns/pid")
    except OSError as exc:
        raise ValueError(
            "CFD-B004 sweep.process.namespace: PID namespace unavailable"
        ) from exc
    for stat in proc.glob("[0-9]*/stat"):
        try:
            if os.readlink(stat.parent / "ns/pid") != namespace:
                continue
            text = stat.read_text()
            fields = text[text.rindex(")") + 2 :].split()
            if fields[0] in "ZX":
                continue
            status = {
                line.split(":", 1)[0]: line.split(":", 1)[1].split()
                for line in (stat.parent / "status").read_text().splitlines()
                if line.startswith(("NSpid:", "NSpgid:"))
            }
        except OSError:
            continue  # A process can disappear between any of these reads.
        try:
            pid, group = int(status["NSpid"][-1]), int(status["NSpgid"][-1])
            if pid <= 0 or group < 0:
                raise ValueError("invalid identity")
            if group == 0:
                continue  # An inherited ancestor group has no local group ID.
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError(
                "CFD-B004 sweep.process.namespace: local PID/group metadata unavailable"
            ) from exc
        yield pid, group


def members(group, proc=Path("/proc")):
    """Live (not zombie) members, identified in the caller's PID namespace."""
    return [pid for pid, pgid in live_processes(proc) if pgid == group]


def stop_group(group, grace_s=5.0):
    """TERM, then KILL, whatever is left of a group; True if anything was left."""
    if not members(group):
        return False
    for sig, wait_s in [(signal.SIGTERM, grace_s), (signal.SIGKILL, 5.0)]:
        try:
            os.killpg(group, sig)
        except ProcessLookupError:
            return True
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            if not members(group):
                return True
            time.sleep(0.05)
    return True


def measure(command, output, timeout_s):
    output = Path(output)
    if output.is_symlink() or output.exists():
        raise ValueError("CFD-B004 sweep.process.output: fresh directory required")
    output.mkdir()
    timer = Path("/usr/bin/time")
    rss = output / "rss-kib.txt"
    argv = list(map(str, command))
    wrapped = (
        [str(timer), "-f", "%M", "-o", str(rss.resolve()), "--", *argv]
        if timer.is_file()
        else argv
    )
    environment = dict(
        os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1"
    )
    start = time.monotonic()
    timed_out = False
    with (
        (output / "stdout.log").open("w") as out,
        (output / "stderr.log").open("w") as err,
    ):
        child = subprocess.Popen(
            wrapped, stdout=out, stderr=err, start_new_session=True, env=environment
        )
        try:
            code = child.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                code = child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                code = child.wait()
    wall = time.monotonic() - start
    # Waiting covers only the direct child (GNU time when present). Descendants
    # left in its group must not run on into the next measurement.
    stray = stop_group(child.pid)
    peak = None
    if rss.is_file():
        lines = rss.read_text().splitlines()
        if lines and lines[-1].isdigit():
            peak = int(lines[-1])
    return dict(
        command=argv,
        returncode=code,
        outer_timeout=timed_out,
        stray_processes_stopped=stray,
        process_wall_s=wall,
        peak_rss_kib_linux=peak,
        rss_scope="GNU time maximum individual process RSS, including waited descendants; not simultaneous aggregate memory"
        if timer.is_file()
        else "unavailable: GNU time not installed",
        timer_sha256=hashlib.sha256(timer.read_bytes()).hexdigest()
        if timer.is_file()
        else None,
    )
