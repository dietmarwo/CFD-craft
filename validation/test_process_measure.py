#!/usr/bin/env python3
"""Actual child exits, log retention and bounded process cleanup."""

from pathlib import Path
import sys
import tempfile
import unittest

from process_measure import measure


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
