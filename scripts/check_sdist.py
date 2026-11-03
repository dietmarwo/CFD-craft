"""Rebuild an extracted sdist and accept its wheel in a fresh environment.

Needs Python 3.12+, maturin on PATH and Rust. All paths are outside the checkout.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import venv


def run(command, cwd):
    subprocess.run([str(x) for x in command], cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdist", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.sdist.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="craft-sdist-") as temp:
        temp = Path(temp)
        with tarfile.open(source) as archive:
            archive.extractall(temp / "source", filter="data")
        roots = list((temp / "source").iterdir())
        if len(roots) != 1:
            raise RuntimeError("sdist must have one project root")
        project = roots[0]
        run(["maturin", "build", "--release", "--locked", "--out", output], project)
        wheels = list(output.glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(
                "use a clean output directory with exactly one rebuilt wheel"
            )
        env = temp / "env"
        venv.EnvBuilder(with_pip=True).create(env)
        python = env / (
            "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
        )
        run([python, "-m", "pip", "install", wheels[0]], temp)
        checker = project / "validation/check_installed.py"
        for flags, name in [
            ([], "installed.json"),
            (["-O"], "installed-optimized.json"),
        ]:
            run([python, "-I", *flags, checker, "--output", output / name], temp)
        normal = json.loads((output / "installed.json").read_text())
        optimized = json.loads((output / "installed-optimized.json").read_text())
        if normal != optimized or not normal.get("passed"):
            raise RuntimeError("sdist acceptance differs under -O")
    print("Extracted sdist and installed-wheel acceptance passed")


if __name__ == "__main__":
    main()
