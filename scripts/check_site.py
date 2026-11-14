"""Check the built documentation site: every internal reference resolves.

Usage: `python scripts/check_site.py book` (builds nothing; run `mdbook build`
first). Reads every `.html` file under the given directory and verifies that
each internal `href` and `src` points to a file in the directory and, where the
reference has a fragment, to an `id` or `name` of that page. A URL that starts
with the site path (`/CFD-craft/`) is resolved from the directory root. Absolute
URLs (`https:`, `mailto:` and so on) are not checked. Prints one JSON line with
the counts; on failure prints each broken reference and exits 1 with
`CFD-R004 site.<field>` (docs/diagnostics.md): `site.directory` for a missing
or empty directory, `site.reference` for a broken file reference and
`site.anchor` for a missing fragment.
"""

from html.parser import HTMLParser
import json
from pathlib import Path
import posixpath
import re
import sys
from urllib.parse import unquote, urlsplit

SITE_PATH = "/CFD-craft/"
URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
# Pages that mdBook generates for the browser only; their ids are not checked.
UNCHECKED_ANCHORS = {"print.html"}


class Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.references = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        for name in ("id", "name"):
            if attributes.get(name):
                self.ids.add(attributes[name])
        for name in ("href", "src"):
            if attributes.get(name) is not None:
                self.references.append((tag, name, attributes[name], self.getpos()[0]))


def parse(path):
    collector = Collector()
    collector.feed(path.read_text(encoding="utf-8"))
    return collector


def resolve(root, page, value):
    """Return (target file or None, fragment) for an internal reference."""
    parts = urlsplit(value)
    path = unquote(parts.path)
    if not path:
        return page, unquote(parts.fragment)
    if path.startswith(SITE_PATH):
        target = root / path[len(SITE_PATH) :]
    elif path.startswith("/"):
        target = root / path.lstrip("/")
    else:
        relative = posixpath.normpath(
            posixpath.join(page.parent.relative_to(root).as_posix(), path)
        )
        target = root / relative
    if target.is_dir():
        target = target / "index.html"
    return target, unquote(parts.fragment)


def check(root):
    pages = sorted(root.rglob("*.html"))
    if not pages:
        raise SystemExit(f"CFD-R004 site.directory: no HTML pages under {root}")
    parsed = {page: parse(page) for page in pages}
    failures = []
    checked = 0
    for page, collector in parsed.items():
        name = page.relative_to(root).as_posix()
        for tag, attribute, value, line in collector.references:
            if URL_SCHEME.match(value) or value.startswith("//") or not value.strip():
                continue
            checked += 1
            target, fragment = resolve(root, page, value)
            where = f"{name}:{line}: <{tag} {attribute}={value!r}>"
            try:
                target.relative_to(root)
            except ValueError:
                failures.append(("reference", f"{where} leaves the site"))
                continue
            if not target.is_file():
                failures.append(("reference", f"{where} no such file"))
                continue
            if (
                fragment
                and target.suffix == ".html"
                and target.name not in UNCHECKED_ANCHORS
            ):
                ids = parsed.get(target)
                if ids is None:
                    ids = parse(target)
                if fragment not in ids.ids:
                    failures.append(
                        (
                            "anchor",
                            f"{where} no id {fragment!r} in {target.relative_to(root).as_posix()}",
                        )
                    )
    return len(pages), checked, failures


def main(argv):
    if len(argv) != 2:
        print("CFD-R004 site.directory: usage: check_site.py BOOK_DIRECTORY")
        return 2
    root = Path(argv[1]).resolve()
    if not root.is_dir():
        print(f"CFD-R004 site.directory: {argv[1]} is not a directory")
        return 2
    pages, checked, failures = check(root)
    print(json.dumps({"pages": pages, "references": checked, "broken": len(failures)}))
    for field, message in failures:
        print(f"CFD-R004 site.{field}: {message}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
