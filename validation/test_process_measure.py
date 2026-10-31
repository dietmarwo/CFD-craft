#!/usr/bin/env python3
"""Actual child exits, log retention and bounded process cleanup."""

from pathlib import Path
import sys
import tempfile
import unittest

from process_measure import measure, live_processes, members


class Processes(unittest.TestCase):
    def test_success_and_nonzero_exit_retain_logs_and_usage(self):
        with tempfile.TemporaryDirectory(prefix="cfd-process-") as d:
            for code in [0, 2]:
                out = Path(d) / str(code)
                r = measure(
                    [
                        sys.executable,
                        "-c",
                        f"import sys; print('retained'); print('error-log',file=sys.stderr); sys.exit({code})",
                    ],
                    out,
                    10,
                )
                self.assertEqual(r["returncode"], code)
                self.assertFalse(r["outer_timeout"])
                self.assertIn("retained", (out / "stdout.log").read_text())
                self.assertIn("error-log", (out / "stderr.log").read_text())
                self.assertGreater(r["process_wall_s"], 0)
                if r["peak_rss_kib_linux"] is not None:
                    self.assertGreater(r["peak_rss_kib_linux"], 0)

    def test_outer_deadline_stops_the_process_group(self):
        with tempfile.TemporaryDirectory(prefix="cfd-process-") as d:
            r = measure(
                [
                    sys.executable,
                    "-c",
                    "import time; print('started',flush=True); time.sleep(30)",
                ],
                Path(d) / "out",
                0.2,
            )
            self.assertTrue(r["outer_timeout"])
            self.assertNotEqual(r["returncode"], 0)
            self.assertLess(r["process_wall_s"], 6)

    def grandchild(self, d, parent_code):
        """A child that starts a TERM-ignoring grandchild in its group."""
        pid_file = Path(d) / "grandchild.pid"
        script = (
            "import subprocess, sys, time\n"
            "g = subprocess.Popen([sys.executable, '-c', "
            "'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "time.sleep(60)'])\n"
            f"open({str(pid_file)!r}, 'w').write(str(g.pid))\n"
            f"{parent_code}\n"
        )
        return [sys.executable, "-c", script], pid_file

    def alive(self, pid):
        return any(local_pid == pid for local_pid, _ in live_processes())

    def test_ancestor_procfs_ids_are_translated_and_other_namespaces_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            proc = Path(temp)
            (proc / "self/ns").mkdir(parents=True)
            (proc / "self/ns/pid").symlink_to("pid:[1]")
            for host_pid, local_pid, state, namespace in [
                (100, 11, "S", 1),
                (101, 12, "Z", 1),
                (102, 11, "S", 2),
                (103, 14, "S", 1),
            ]:
                p = proc / str(host_pid)
                (p / "ns").mkdir(parents=True)
                (p / "ns/pid").symlink_to(f"pid:[{namespace}]")
                (p / "stat").write_text(
                    f"{host_pid} (name with ) parentheses) {state} 1 900 900 0"
                )
                (p / "status").write_text(
                    f"NSpid:\t{host_pid}\t{local_pid}\nNSpgid:\t900\t9\n"
                )
            (proc / "103/status").write_text("NSpid: 103 14\nNSpgid: 900 0\n")
            self.assertEqual(members(9, proc), [11])
            self.assertEqual(members(900, proc), [])
            (proc / "100/status").write_text("NSpid: 100 11\n")
            with self.assertRaisesRegex(ValueError, "CFD-B004 sweep.process.namespace"):
                members(9, proc)

    def test_descendants_do_not_outlive_a_timeout_or_a_normal_exit(self):
        with tempfile.TemporaryDirectory(prefix="cfd-process-") as d:
            for name, parent_code, timeout_s in [
                ("timeout", "time.sleep(30)", 1.0),
                ("exit", "sys.exit(0)", 20.0),
            ]:
                with self.subTest(name=name):
                    sub = Path(d) / name
                    sub.mkdir()
                    command, pid_file = self.grandchild(sub, parent_code)
                    r = measure(command, sub / "out", timeout_s)
                    pid = int(pid_file.read_text())
                    self.assertFalse(self.alive(pid))
                    self.assertTrue(r["stray_processes_stopped"])
                    self.assertEqual(r["outer_timeout"], name == "timeout")

    def test_occupied_and_dangling_output_are_refused(self):
        with tempfile.TemporaryDirectory(prefix="cfd-process-") as d:
            for symlink in [False, True]:
                out = Path(d) / str(symlink)
                if symlink:
                    out.symlink_to(Path(d) / "missing")
                else:
                    out.mkdir()
                with self.assertRaisesRegex(
                    ValueError, "CFD-B004 sweep.process.output"
                ):
                    measure([sys.executable, "-c", "pass"], out, 10)


if __name__ == "__main__":
    unittest.main()
