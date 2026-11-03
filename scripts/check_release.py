"""Fail before packaging on inconsistent versions, names or local dependencies."""

import argparse
import json
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return tomllib.loads((ROOT / path).read_text())


def require(value, message):
    if not value:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version")
    args = parser.parse_args()
    root = read("Cargo.toml")
    version = root["workspace"]["package"]["version"]
    python = read("pyproject.toml")["project"]
    binding = read("bindings/python/Cargo.toml")["package"]
    require(
        version == python["version"] == binding["version"],
        "Rust/Python version mismatch",
    )
    require(
        args.version is None or args.version == version, "release/tag version mismatch"
    )
    names = []
    for member in root["workspace"]["members"]:
        manifest = read(member + "/Cargo.toml")
        pkg = manifest["package"]
        require(pkg.get("publish") is not False, "public crate has publish=false")
        require(
            pkg.get("version") == {"workspace": True}, "member version must inherit"
        )
        require((ROOT / member / "README.md").is_file(), "missing packaged readme")
        require(
            (ROOT / member / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes(),
            "license drift",
        )
        for name, dep in manifest.get("dependencies", {}).items():
            if isinstance(dep, dict) and dep.get("workspace"):
                dep = root["workspace"]["dependencies"][name]
            if isinstance(dep, dict) and "path" in dep:
                require(
                    dep.get("version") == version,
                    "unversioned/mismatched path dependency: " + name,
                )
        names.append(pkg["name"])
    for lock in [
        "Cargo.lock",
        "bindings/python/Cargo.lock",
        *[
            str(p.relative_to(ROOT))
            for p in (ROOT / "integrations").glob("*/Cargo.lock")
        ],
    ]:
        packages = read(lock)["package"]
        for pkg in packages:
            if pkg["name"] in names + [binding["name"]] and "source" not in pkg:
                require(pkg["version"] == version, "stale first-party lockfile version")
    print(json.dumps({"passed": True, "version": version, "crates": names}, indent=2))


if __name__ == "__main__":
    main()
