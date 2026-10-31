"""Bounded shell-free process wall/RSS measurement for the accuracy sweep."""

import hashlib
import os
from pathlib import Path
import signal
import subprocess
import time


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
    peak = None
    if rss.is_file():
        lines = rss.read_text().splitlines()
        if lines and lines[-1].isdigit():
            peak = int(lines[-1])
    return dict(
        command=argv,
        returncode=code,
        outer_timeout=timed_out,
        process_wall_s=wall,
        peak_rss_kib_linux=peak,
        rss_scope="GNU time maximum individual process RSS, including waited descendants; not simultaneous aggregate memory"
        if timer.is_file()
        else "unavailable: GNU time not installed",
        timer_sha256=hashlib.sha256(timer.read_bytes()).hexdigest()
        if timer.is_file()
        else None,
    )
