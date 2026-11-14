"""Run and check the code blocks of documentation pages.

    python scripts/check_docs.py [--smoke] [--root DIR] PAGE.md ...

Every fenced block of a page must name its language, and each language has one
meaning:

- `python`: run. The blocks of one level-2 section share one interpreter.
- `bash`: run with `bash -euo pipefail`, each block in its own shell.
- `text`: the standard output of the runnable block directly before it.
- `json`: strict JSON (no duplicate keys). A document whose `schema_version`
  starts with `cfd-craft.case/` must pass `cfd-craft check`.
- `sh`: syntax only (`bash -n`); a `python PATH.py` it names must exist.
- `toml`: parsed. `rust`: bound to a compiled file. `mermaid`: not checked.

Markers are HTML comments: under the level-1 title for the page, under a
level-2 heading for the section, directly before a fence for the block.

    <!-- check: rel=1e-4 -->            page: tolerance of floats in text blocks
    <!-- check: long -->                page, section: not executed with --smoke
    <!-- check: openfoam -->            page, section: executed with --foam-root
    <!-- check: jobs -->                page, section: executed with --runner
    <!-- check: fragment -->            json block: parsed, not sent to `check`
    <!-- check: fragment of PATH -->    rust block: its lines occur in PATH, in order
    <!-- check: none: REASON -->        block, page: not checked
    <!-- file: NAME -->                 json block: written to NAME in the session
    <!-- file: NAME = REPO_PATH -->     and equal, as JSON, to the committed file

A page is one session under a new temporary directory, never inside the
checkout. A first level-2 section named `Setup` runs once; every other section
starts from its own copy of what the setup left. The session directory links
the top-level directories of the checkout and has an empty `runs/`, so commands
read as they do from the repository root. `target/release` of the checkout and
the directory of the running interpreter are put on `PATH`.

A `text` block must have as many lines as the output. Number literals with a
decimal point or an exponent are compared with the declared tolerance,
`|actual - shown| <= rel * max(|actual|, |shown|) + abs`; integers and all other
text must be identical. Digits inside a word, a hash, a version string or a
schema name (`cfd-craft.result/0.1`) are text. A block that is not executed (a `long` section with
`--smoke`, `openfoam` without `--foam-root`, `jobs` without `--runner`) is
checked for syntax and script paths, and its `text` blocks are not compared.

Prints a JSON report on stdout and exits 1 when a page fails. Failures are
reported on stderr as `CFD-R003 docs.<field>: PAGE:LINE: message`
(docs/diagnostics.md). Needs bash and a POSIX host.
"""

import argparse
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib

HERE = Path(__file__).resolve().parents[1]
SCHEMA = "cfd-craft.docs-check/0.1"
LANGUAGES = ("python", "bash", "text", "json", "sh", "toml", "rust", "mermaid")
LINKS = (
    "cases",
    "crates",
    "examples",
    "integrations",
    "target",
    "tutorials",
    "validation",
)
RAW_URL = "https://raw.githubusercontent.com/dietmarwo/CFD-craft/main/"
FOAM_LINK = "runs/openfoam13/runtime/opt/openfoam13"
RUNNER_LINK = "optimization-jobs/target/release/optimization-run"
CASE_SCHEMA = "cfd-craft.case/"
REL_MAX = 1e-4
SENTENCE = (
    "Outputs on this page are real. The documentation check compares "
    "floating-point numbers with a relative tolerance of {rel}{absolute}; "
    "everything else must match exactly."
)
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
MARKER = re.compile(r"^<!--\s*(check|file):\s*(.*?)\s*-->$")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
TOLERANCE = re.compile(r"^rel=(\S+)(?:\s+abs=(\S+))?$")
# A number that is not part of a word, a hash, a version string or a schema
# name such as `cfd-craft.result/0.1`.
NUMBER = re.compile(
    r"(?<![\w.])(?<![A-Za-z]/)[-+]?(?:\d+\.\d+|\.\d+|\d+)(?:[eE][-+]?\d+)?(?!\w|\.\d)"
)
SCRIPT = re.compile(
    r"(?:^|[\s;&|(])python[0-9.]*\s+(?:-[A-Za-z]\s+)*((?:[\w.-]+/)*[\w.-]+\.py)\b"
)
# Runs the python blocks of one section: one request per line on the request
# pipe, one reply per line on the reply pipe; output goes to the named files.
INTERPRETER = r"""
import json, os, sys, traceback
requests = os.fdopen(int(sys.argv[1]), encoding="utf-8")
replies = os.fdopen(int(sys.argv[2]), "w", encoding="utf-8")
namespace = {"__name__": "__main__"}
for line in requests:
    request = json.loads(line)
    saved = os.dup(1), os.dup(2)
    for name, number in ((request["stdout"], 1), (request["stderr"], 2)):
        handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.dup2(handle, number)
        os.close(handle)
    passed = True
    try:
        with open(request["source"], encoding="utf-8") as handle:
            source = handle.read()
        exec(compile(source, request["name"], "exec"), namespace)
    except BaseException:
        passed = False
        traceback.print_exc()
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        for handle, number in zip(saved, (1, 2), strict=True):
            os.dup2(handle, number)
            os.close(handle)
    replies.write(json.dumps({"passed": passed}) + "\n")
    replies.flush()
"""


class Failure(Exception):
    """One coded finding: the field of `docs.<field>`, the page line, the text."""

    def __init__(self, field, line, message):
        super().__init__(message)
        self.field = field
        self.line = line


class NotRun:
    """Why the runnable block before a `text` block has no output to compare."""

    def __init__(self, reason):
        self.reason = reason


# --- parsing --------------------------------------------------------------


def tolerance(value, line):
    match = TOLERANCE.match(value)
    if not match:
        raise Failure("marker", line, f"unknown marker `check: {value}`")
    try:
        rel = float(match.group(1))
        absolute = 0.0 if match.group(2) is None else float(match.group(2))
    except ValueError:
        raise Failure("marker", line, f"`{value}` is not a tolerance") from None
    if not 0.0 < rel <= REL_MAX or not 0.0 <= absolute < float("inf"):
        raise Failure(
            "marker",
            line,
            f"`{value}`: rel must be positive and at most {REL_MAX:g}, abs finite",
        )
    return dict(
        rel=rel,
        abs=absolute,
        sentence=SENTENCE.format(
            rel=match.group(1),
            absolute=(
                ""
                if match.group(2) is None
                else f" and an absolute tolerance of {match.group(2)}"
            ),
        ),
    )


def parse(text):
    """The page as sections of blocks, and the failures found while reading it."""
    page = dict(flags=set(), none=None, tolerance=None, prose=[], title=None)
    sections = [dict(title=None, line=1, flags=set(), blocks=[])]
    failures = []
    fence = None
    context = None
    pending = []

    def marker(kind, value, line):
        if kind == "file":
            name, _, committed = (part.strip() for part in value.partition("="))
            parts = Path(name).parts
            if not name or Path(name).is_absolute() or ".." in parts:
                raise Failure("marker", line, f"`file: {value}` needs a relative name")
            pending.append(("file", (name, committed or None), line))
        elif value in ("long", "openfoam", "jobs"):
            if context == "title":
                page["flags"].add(value)
            elif context == "section":
                sections[-1]["flags"].add(value)
            else:
                raise Failure(
                    "marker",
                    line,
                    f"`check: {value}` belongs under the title or a level-2 heading",
                )
        elif value.startswith("none"):
            reason = value[4:].lstrip(":").strip()
            if not value[4:].startswith(":") or not reason:
                raise Failure("marker", line, "`check: none` needs `: REASON`")
            if context == "title":
                page["none"] = reason
            else:
                pending.append(("none", reason, line))
        elif value == "fragment" or value.startswith("fragment of "):
            pending.append(("fragment", value[12:].strip() or None, line))
        elif context == "title":
            page["tolerance"] = tolerance(value, line)
        else:
            raise Failure("marker", line, f"unknown or misplaced `check: {value}`")

    for number, line in enumerate(text.splitlines(), 1):
        if fence is not None:
            closing = FENCE.match(line)
            if (
                closing
                and closing.group(1)[0] == fence["mark"][0]
                and len(closing.group(1)) >= len(fence["mark"])
                and not closing.group(2).strip()
            ):
                fence["text"] = "\n".join(fence.pop("body")) + "\n"
                del fence["mark"]
                sections[-1]["blocks"].append(fence)
                fence = None
            else:
                fence["body"].append(line)
            continue
        opening = FENCE.match(line)
        if opening:
            language = opening.group(2).strip()
            fence = dict(
                language=language,
                line=number,
                mark=opening.group(1),
                body=[],
                markers={kind: value for kind, value, _ in pending},
            )
            if language not in LANGUAGES:
                failures.append(
                    Failure(
                        "fence",
                        number,
                        f"the info string `{language}` is not one of "
                        f"{', '.join(LANGUAGES)}"
                        if language
                        else "a fenced block needs an info string",
                    )
                )
            pending.clear()
            context = None
            continue
        stripped = line.strip()
        if not stripped:
            continue
        found = MARKER.match(stripped)
        if found:
            try:
                marker(found.group(1), found.group(2), number)
            except Failure as failure:
                failures.append(failure)
            continue
        if pending:
            failures.append(
                Failure("marker", pending[0][2], "not directly before a fenced block")
            )
            pending.clear()
        heading = HEADING.match(line)
        context = None
        if heading and len(heading.group(1)) == 1 and page["title"] is None:
            page["title"] = heading.group(2)
            context = "title"
        elif heading and len(heading.group(1)) == 2:
            sections.append(
                dict(title=heading.group(2), line=number, flags=set(), blocks=[])
            )
            context = "section"
        else:
            page["prose"].append(stripped)
    if fence is not None:
        failures.append(Failure("fence", fence["line"], "the fence is not closed"))
    if pending:
        failures.append(
            Failure("marker", pending[0][2], "not directly before a fenced block")
        )
    page["sections"] = sections
    return page, failures


def static_failures(page):
    """Rules that need no execution: markers per language, setup, tolerance."""
    failures = []
    titles = [section["title"] for section in page["sections"][1:]]
    if "Setup" in titles[1:]:
        line = page["sections"][1 + titles.index("Setup")]["line"]
        failures.append(
            Failure("setup", line, "`## Setup` must be the first level-2 section")
        )
    allowed = dict(json={"file", "fragment", "none"}, rust={"fragment", "none"})
    for section in page["sections"]:
        for block in section["blocks"]:
            extra = set(block["markers"]) - allowed.get(block["language"], {"none"})
            if extra and block["language"] in LANGUAGES:
                failures.append(
                    Failure(
                        "marker",
                        block["line"],
                        f"`{sorted(extra)[0]}` does not apply to a "
                        f"`{block['language']}` block",
                    )
                )
    prose = " ".join(" ".join(page["prose"]).split())
    declared = page["tolerance"]
    if declared and declared["sentence"] not in prose:
        failures.append(
            Failure(
                "marker",
                1,
                f"the page declares a tolerance and lacks the sentence: "
                f"{declared['sentence']}",
            )
        )
    if not declared and SENTENCE.split("{")[0] in prose:
        failures.append(
            Failure(
                "marker", 1, "the tolerance sentence needs `<!-- check: rel=... -->`"
            )
        )
    return failures


# --- comparison -----------------------------------------------------------


def is_float(literal):
    return any(mark in literal for mark in ".eE")


def compare(shown, actual, declared, line):
    """Raise a `text` failure unless the output agrees with the shown block."""
    shown_lines = [row.rstrip() for row in shown.rstrip().splitlines()]
    actual_lines = [row.rstrip() for row in actual.rstrip().splitlines()]
    if len(shown_lines) != len(actual_lines):
        raise Failure(
            "text",
            line,
            f"shows {len(shown_lines)} lines, the output has {len(actual_lines)}:\n"
            + "\n".join(actual_lines[:40]),
        )
    for offset, (want, got) in enumerate(
        zip(shown_lines, actual_lines, strict=True), 1
    ):
        where = line + offset
        want_numbers = NUMBER.findall(want)
        got_numbers = NUMBER.findall(got)
        if NUMBER.split(want) != NUMBER.split(got):
            raise Failure("text", where, f"shows `{want}`, the output is `{got}`")
        for a, b in zip(want_numbers, got_numbers, strict=True):
            if not is_float(a) and not is_float(b):
                if a != b:
                    raise Failure("text", where, f"shows {a}, the output is {b}")
                continue
            if not declared:
                raise Failure(
                    "text",
                    where,
                    f"shows the float {a}, and the page declares no tolerance "
                    "(`<!-- check: rel=1e-4 -->` under the title)",
                )
            if is_float(a) != is_float(b):
                raise Failure("text", where, f"shows {a}, the output is {b}")
            x, y = float(a), float(b)
            if (
                not abs(x - y)
                <= declared["rel"] * max(abs(x), abs(y)) + declared["abs"]
            ):
                raise Failure(
                    "text",
                    where,
                    f"shows {a}, the output is {b} (rel={declared['rel']:g}, "
                    f"abs={declared['abs']:g})",
                )


# --- single blocks --------------------------------------------------------


def strict_json(text, line):
    def pairs(items):
        keys = [key for key, _ in items]
        repeated = sorted({key for key in keys if keys.count(key) > 1})
        if repeated:
            raise ValueError(f"duplicate key `{repeated[0]}`")
        return dict(items)

    def constant(name):
        raise ValueError(f"`{name}` is not JSON")

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except ValueError as error:
        raise Failure("json", line, f"not strict JSON: {error}") from None


def tail(text, rows=15):
    return "\n".join(text.rstrip().splitlines()[-rows:])


def bash_syntax(code, line, field):
    try:
        done = subprocess.run(
            ["bash", "-n"],
            input=code,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise Failure(field, line, f"cannot run `bash -n`: {error}") from None
    if done.returncode != 0:
        raise Failure(field, line, f"shell syntax:\n{tail(done.stderr)}")


def script_paths(code, line, field, root):
    for path in SCRIPT.findall(code):
        if not (root / path).is_file():
            raise Failure(field, line, f"`python {path}`: no such file in the checkout")


def rust_fragment(block, root):
    line = block["line"]
    path = block["markers"].get("fragment")
    if not path:
        raise Failure(
            "rust",
            line,
            "needs `<!-- check: fragment of PATH -->` or `<!-- check: none: REASON -->`",
        )
    try:
        source = (root / path).read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise Failure("rust", line, f"cannot read `{path}`: {error}") from None
    rows = iter(row.strip() for row in source)
    for offset, row in enumerate(block["text"].splitlines(), 1):
        wanted = row.strip()
        if not wanted or wanted.startswith("//"):
            continue
        if not any(candidate == wanted for candidate in rows):
            raise Failure(
                "rust", line + offset, f"`{wanted}` does not occur, in order, in {path}"
            )


class Session:
    """What the blocks of all pages share: checkout, mode, environment, counts."""

    def __init__(self, root, args, temporary):
        self.root = root
        self.smoke = args.smoke
        self.foam_root = args.foam_root
        self.runner = args.runner
        self.timeout = args.timeout
        self.temporary = temporary
        self.control = temporary / "control"
        self.control.mkdir()
        # Blocks read an empty standard input.
        (self.control / "empty").write_bytes(b"")
        self.empty = open(self.control / "empty", "rb")
        paths = [str(Path(sys.executable).parent), str(root / "target/release")]
        if HERE != root:
            paths.append(str(HERE / "target/release"))
        self.env = dict(os.environ)
        self.env["PATH"] = os.pathsep.join(paths + [os.environ.get("PATH", "")])
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.binary = shutil.which("cfd-craft", path=self.env["PATH"])

    def new_directory(self, path):
        path.mkdir(parents=True)
        for name in LINKS:
            if (self.root / name).is_dir():
                (path / name).symlink_to(self.root / name)
        (path / "runs").mkdir()
        return path

    def check_case(self, text, line):
        if self.binary is None:
            raise Failure(
                "binary", line, "`cfd-craft` is not on PATH or in target/release"
            )
        case = self.control / "case.json"
        case.write_text(text, encoding="utf-8")
        try:
            done = subprocess.run(
                [self.binary, "check", str(case)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise Failure(
                "binary", line, f"cannot run `cfd-craft check`: {error}"
            ) from None
        if done.returncode != 0:
            try:
                found = [
                    f"{d['code']} {d['path']}"
                    for d in json.loads(done.stdout)["check"]["diagnostics"]
                    if d["severity"] == "error"
                ]
            except (ValueError, KeyError, TypeError):
                found = [tail(done.stdout + done.stderr)]
            raise Failure(
                "json",
                line,
                f"`cfd-craft check` exits {done.returncode}: {'; '.join(found)}",
            )

    def bash(self, code, line, directory):
        process = subprocess.Popen(
            ["bash", "-euo", "pipefail", "-c", code],
            cwd=directory,
            env=self.env,
            stdin=self.empty,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
        try:
            output, errors = process.communicate(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            stop(process)
            process.communicate()
            raise Failure(
                "bash", line, f"no end after {self.timeout:g} s; stopped"
            ) from None
        if process.returncode != 0:
            raise Failure(
                "bash",
                line,
                f"exit {process.returncode}\n{tail(output)}\n{tail(errors)}".rstrip(),
            )
        return output


def stop(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


class Interpreter:
    """One Python process for the `python` blocks of one section."""

    def __init__(self, session, directory, name):
        self.session = session
        self.name = name
        request_read, self.request = os.pipe()
        self.reply, reply_write = os.pipe()
        self.process = subprocess.Popen(
            [sys.executable, "-c", INTERPRETER, str(request_read), str(reply_write)],
            cwd=directory,
            env=session.env,
            stdin=session.empty,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            pass_fds=(request_read, reply_write),
            start_new_session=True,
        )
        os.close(request_read)
        os.close(reply_write)

    def run(self, code, line):
        control = self.session.control
        source, output, errors = (control / n for n in ("block.py", "out", "err"))
        # Leading blank lines make traceback lines the lines of the page.
        source.write_text("\n" * line + code, encoding="utf-8")
        request = dict(
            source=str(source),
            stdout=str(output),
            stderr=str(errors),
            name=f"{self.name}",
        )
        os.write(self.request, (json.dumps(request) + "\n").encode("utf-8"))
        ready, _, _ = select.select([self.reply], [], [], self.session.timeout)
        if not ready:
            stop(self.process)
            self.close()
            raise Failure(
                "python", line, f"no end after {self.session.timeout:g} s; stopped"
            )
        reply = b""
        while not reply.endswith(b"\n"):
            chunk = os.read(self.reply, 4096)
            if not chunk:
                break
            reply += chunk
        try:
            passed = json.loads(reply)["passed"]
        except (ValueError, KeyError, TypeError):
            raise Failure("python", line, "the interpreter ended") from None
        if passed is not True:
            raise Failure(
                "python",
                line,
                tail(errors.read_text(encoding="utf-8", errors="replace")),
            )
        return output.read_text(encoding="utf-8", errors="replace")

    def close(self):
        if self.request is not None:
            os.close(self.request)
            self.request = None
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                stop(self.process)
                self.process.wait()
            os.close(self.reply)


# --- pages ----------------------------------------------------------------

COUNTS = ("python", "bash", "text", "json", "cases", "sh", "toml", "rust", "not_run")


def run_section(session, page, section, directory, counts, unchecked, name):
    """Check the blocks of one section in page order; the failures found."""
    flags = page["flags"] | section["flags"]
    not_run = None
    if "long" in flags and session.smoke:
        not_run = "long"
    elif "openfoam" in flags and session.foam_root is None:
        not_run = "openfoam"
    elif "jobs" in flags and session.runner is None:
        not_run = "jobs"
    failures = []
    interpreter = None
    previous = None
    try:
        for block in section["blocks"]:
            language, line, code = block["language"], block["line"], block["text"]
            markers = block["markers"]
            output = None
            try:
                if "none" in markers:
                    unchecked.append(dict(line=line, reason=markers["none"]))
                elif language in ("python", "bash"):
                    if language == "bash":
                        bash_syntax(code, line, "bash")
                    else:
                        try:
                            compile(code, name, "exec")
                        except (SyntaxError, ValueError) as error:
                            raise Failure("python", line, f"syntax: {error}") from None
                    if not_run:
                        script_paths(code, line, language, session.root)
                        counts["not_run"] += 1
                        output = NotRun(not_run)
                    else:
                        code = code.replace(RAW_URL, session.root.as_uri() + "/")
                        if language == "bash":
                            output = session.bash(code, line, directory)
                        else:
                            if interpreter is None:
                                interpreter = Interpreter(session, directory, name)
                            output = interpreter.run(code, line)
                        counts[language] += 1
                elif language == "text":
                    if previous is None:
                        raise Failure(
                            "text", line, "no runnable block directly before it"
                        )
                    if not isinstance(previous, NotRun):
                        compare(code, previous, page["tolerance"], line)
                        counts["text"] += 1
                elif language == "json":
                    value = strict_json(code, line)
                    name_and_path = markers.get("file")
                    if (
                        "fragment" not in markers
                        and isinstance(value, dict)
                        and str(value.get("schema_version", "")).startswith(CASE_SCHEMA)
                    ):
                        session.check_case(code, line)
                        counts["cases"] += 1
                    if name_and_path and name_and_path[1]:
                        committed = session.root / name_and_path[1]
                        try:
                            same = strict_json(
                                committed.read_text(encoding="utf-8"), line
                            )
                        except OSError as error:
                            raise Failure(
                                "json",
                                line,
                                f"cannot read `{name_and_path[1]}`: {error}",
                            ) from None
                        if same != value:
                            raise Failure(
                                "json",
                                line,
                                f"differs, as JSON, from `{name_and_path[1]}`",
                            )
                    if name_and_path and not not_run:
                        target = directory / name_and_path[0]
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(code, encoding="utf-8")
                    counts["json"] += 1
                elif language == "sh":
                    bash_syntax(code, line, "sh")
                    script_paths(code, line, "sh", session.root)
                    counts["sh"] += 1
                elif language == "toml":
                    try:
                        tomllib.loads(code)
                    except tomllib.TOMLDecodeError as error:
                        raise Failure("toml", line, f"not TOML: {error}") from None
                    counts["toml"] += 1
                elif language == "rust":
                    rust_fragment(block, session.root)
                    counts["rust"] += 1
            except Failure as failure:
                failures.append(failure)
                if failure.field in ("python", "bash", "binary"):
                    break  # the rest of the section depends on this block
            previous = output
    finally:
        if interpreter is not None:
            interpreter.close()
    return failures


def check_page(session, path, index):
    try:
        shown = str(path.relative_to(session.root))
    except ValueError:
        shown = str(path)
    counts = dict.fromkeys(COUNTS, 0)
    unchecked = []
    record = dict(page=shown, passed=False, **counts, unchecked=unchecked, failures=[])

    def finish(failures):
        for failure in failures:
            text = f"CFD-R003 docs.{failure.field}: {shown}:{failure.line}: {failure}"
            print(text, file=sys.stderr)
            record["failures"].append(text.splitlines()[0])
        record.update(counts)
        record["passed"] = not record["failures"]
        return record

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return finish([Failure("page", 0, f"cannot read the page: {error}")])
    page, failures = parse(text)
    if page["none"] is not None:
        unchecked.append(dict(line=1, reason=page["none"]))
        return finish([])
    failures += static_failures(page)
    if failures:
        return finish(failures)
    base = session.temporary / f"{index:02d}-{path.stem}"
    setup = session.new_directory(base / "setup")
    if session.foam_root is not None:
        (setup / FOAM_LINK).parent.mkdir(parents=True)
        (setup / FOAM_LINK).symlink_to(session.foam_root)
    if session.runner is not None:
        (base / RUNNER_LINK).parent.mkdir(parents=True)
        (base / RUNNER_LINK).symlink_to(session.runner)
    sections = page["sections"]
    has_setup = len(sections) > 1 and sections[1]["title"] == "Setup"
    if has_setup:
        failures += run_section(
            session, page, sections[1], setup, counts, unchecked, shown
        )
        if failures:
            return finish(failures)
    for number, section in enumerate(sections):
        if not section["blocks"] or (has_setup and number == 1):
            continue
        directory = base / f"section-{number:02d}"
        shutil.copytree(setup, directory, symlinks=True)
        failures += run_section(
            session, page, section, directory, counts, unchecked, shown
        )
        shutil.rmtree(directory, ignore_errors=True)
    shutil.rmtree(base, ignore_errors=True)
    return finish(failures)


def main():
    parser = argparse.ArgumentParser(
        description="Run and check the code blocks of documentation pages."
    )
    parser.add_argument("pages", nargs="+", type=Path, metavar="PAGE.md")
    parser.add_argument(
        "--root",
        type=Path,
        default=HERE,
        help="checkout whose pages and top-level directories are used "
        "(default: the checkout of this script)",
    )
    parser.add_argument(
        "--smoke", action="store_true", help="do not execute `long` pages and sections"
    )
    parser.add_argument(
        "--foam-root", type=Path, help="OpenFOAM runtime for `openfoam` pages"
    )
    parser.add_argument(
        "--runner", type=Path, help="optimization-run binary for `jobs` pages"
    )
    parser.add_argument(
        "--timeout", type=float, default=180.0, help="seconds per block (default 180)"
    )
    parser.add_argument(
        "--keep", action="store_true", help="keep the temporary directory and name it"
    )
    args = parser.parse_args()
    if not args.timeout > 0.0:
        sys.exit("CFD-R003 docs.arguments: --timeout must be positive")
    root = args.root.resolve()
    if not root.is_dir():
        sys.exit(f"CFD-R003 docs.arguments: --root {args.root} is not a directory")
    for name in ("foam_root", "runner"):
        if getattr(args, name) is not None:
            setattr(args, name, getattr(args, name).absolute())
    if shutil.which("bash") is None:
        sys.exit("CFD-R003 docs.arguments: bash is not on PATH")
    started = time.monotonic()
    temporary = Path(tempfile.mkdtemp(prefix="cfd-craft-docs-")).resolve()
    records = []
    session = Session(root, args, temporary)
    try:
        for index, page in enumerate(args.pages):
            # A relative page is looked up here first, then in the checkout.
            path = page if page.exists() else root / page
            page_started = time.monotonic()
            records.append(check_page(session, path.resolve(), index))
            print(
                f"{records[-1]['page']}: {time.monotonic() - page_started:.1f} s",
                file=sys.stderr,
            )
    finally:
        session.empty.close()
        if args.keep:
            print(f"kept: {temporary}", file=sys.stderr)
        else:
            shutil.rmtree(temporary, ignore_errors=True)
    totals = {key: sum(record[key] for record in records) for key in COUNTS}
    totals["unchecked"] = sum(len(record["unchecked"]) for record in records)
    totals["failures"] = sum(len(record["failures"]) for record in records)
    passed = all(record["passed"] for record in records)
    print(
        json.dumps(
            dict(
                schema_version=SCHEMA,
                mode="smoke" if args.smoke else "full",
                passed=passed,
                pages=records,
                totals=totals,
            ),
            indent=2,
        )
    )
    print(f"total: {time.monotonic() - started:.1f} s", file=sys.stderr)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
