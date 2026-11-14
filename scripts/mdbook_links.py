"""mdBook preprocessor: send links to pages that are not in the site to GitHub.

The site is built from `docs/` (see `book.toml` and `docs/SUMMARY.md`). A page
in `docs/` may link to a file that the site does not contain: a stub that is
not listed in `SUMMARY.md`, a source file or case outside `docs/`, or a
directory. In the built HTML such a link would be broken. This preprocessor
rewrites it to `https://github.com/dietmarwo/CFD-craft/blob/main/PATH`
(`tree/main/PATH` for a directory). Links between listed pages, links to
assets (images) inside `docs/`, anchors, absolute URLs and everything inside
code blocks and code spans stay as they are, except that a link to a
`README.md` becomes a link to `index.md`, because mdBook writes `index.html`.

mdBook protocol: `mdbook_links.py supports RENDERER` exits 0, and a run reads
`[context, book]` as JSON from standard input and writes the book as JSON to
standard output. A link whose target does not exist at all stops the build.
Failures are reported as `CFD-R004 site.<field>` (docs/diagnostics.md).
"""

import json
from pathlib import Path
import posixpath
import re
import sys

REPOSITORY = "https://github.com/dietmarwo/CFD-craft"
BRANCH = "main"
FENCE = re.compile(r"^\s*(```|~~~)")
CODE_SPAN = re.compile(r"(`+)(?:.+?)\1")
LINK = re.compile(r"(\]\(\s*<?)([^)\s>]+)(>?(?:\s+\"[^\"]*\")?\s*\))")
REFERENCE = re.compile(r"^(\s{0,3}\[[^\]]+\]:\s*<?)(\S+?)(>?\s*(?:\"[^\"]*\")?\s*)$")
HTML_ATTRIBUTE = re.compile(r"""(\b(?:href|src)\s*=\s*["'])([^"']+)(["'])""")


class SiteError(Exception):
    """A link that cannot be resolved; carries the `site.<field>` code."""

    def __init__(self, field, message):
        super().__init__(f"CFD-R004 site.{field}: {message}")


def is_external(target):
    return (
        not target
        or target.startswith(("#", "/", "//"))
        or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target) is not None
    )


def github_url(repo_path, is_directory):
    kind = "tree" if is_directory else "blob"
    return f"{REPOSITORY}/{kind}/{BRANCH}/{repo_path}"


def index_name(path):
    """mdBook serves README.md as index.html but links to README.html."""
    if posixpath.basename(path) == "README.md":
        return posixpath.join(posixpath.dirname(path), "index.md")
    return path


def rewrite_target(target, chapter, root, src, listed):
    """Return the replacement for `target`, or `target` when it stays."""
    if is_external(target):
        return target
    path, hash_mark, fragment = target.partition("#")
    path = path.partition("?")[0]
    if not path:
        return target
    here = posixpath.dirname(chapter)
    joined = posixpath.normpath(posixpath.join(src, here, path))
    if joined.startswith(".."):
        raise SiteError("link", f"{chapter}: {target} leaves the repository")
    local = root / joined
    if not local.exists():
        raise SiteError("link", f"{chapter}: {target} does not exist ({joined})")
    inside = joined == src or joined.startswith(src + "/")
    if inside:
        relative = posixpath.relpath(joined, src)
        if relative in listed:
            return index_name(path) + (hash_mark + fragment if fragment else "")
        if local.is_file() and local.suffix.lower() != ".md":
            return target  # an asset that mdBook copies, such as an image
        if local.is_dir() and posixpath.join(relative, "README.md") in listed:
            return target
    url = github_url(joined, local.is_dir())
    return url + (hash_mark + fragment if fragment else "")


def rewrite_line(line, chapter, root, src, listed):
    def replace(match):
        target = rewrite_target(match.group(2), chapter, root, src, listed)
        return match.group(1) + target + match.group(3)

    reference = REFERENCE.match(line)
    if reference:
        target = rewrite_target(reference.group(2), chapter, root, src, listed)
        return reference.group(1) + target + reference.group(3)
    # Split into code spans (kept) and text (rewritten).
    pieces = []
    last = 0
    for span in CODE_SPAN.finditer(line):
        pieces.append((line[last : span.start()], True))
        pieces.append((span.group(0), False))
        last = span.end()
    pieces.append((line[last:], True))
    result = []
    for text, is_text in pieces:
        if is_text:
            text = LINK.sub(replace, text)
            text = HTML_ATTRIBUTE.sub(replace, text)
        result.append(text)
    return "".join(result)


def rewrite_chapter(content, chapter, root, src, listed):
    lines = content.split("\n")
    in_fence = False
    fence_mark = ""
    for index, line in enumerate(lines):
        opening = FENCE.match(line)
        if opening:
            if not in_fence:
                in_fence, fence_mark = True, opening.group(1)
            elif opening.group(1) == fence_mark:
                in_fence = False
            continue
        if not in_fence:
            lines[index] = rewrite_line(line, chapter, root, src, listed)
    return "\n".join(lines)


def chapters(items):
    for item in items:
        if isinstance(item, dict) and "Chapter" in item:
            chapter = item["Chapter"]
            yield chapter
            yield from chapters(chapter.get("sub_items", []))


def process(context, book):
    root = Path(context["root"])
    src = context["config"].get("book", {}).get("src", "src").strip("/")
    items = book.get("items", book.get("sections"))
    if items is None:
        raise SiteError("book", "the book has neither items nor sections")
    listed = set()
    for chapter in chapters(items):
        # `path` names the output page (README.md becomes index.md);
        # `source_path` names the file that the author linked to.
        for key in ("path", "source_path"):
            if chapter.get(key):
                listed.add(chapter[key].replace("\\", "/"))
    for chapter in chapters(items):
        if chapter.get("path"):
            chapter["content"] = rewrite_chapter(
                chapter["content"],
                (chapter.get("source_path") or chapter["path"]).replace("\\", "/"),
                root,
                src,
                listed,
            )
    return book


def main(argv):
    if len(argv) >= 2 and argv[1] == "supports":
        return 0
    try:
        context, book = json.load(sys.stdin)
        book = process(context, book)
    except SiteError as error:
        print(error, file=sys.stderr)
        return 1
    except (ValueError, KeyError, TypeError) as error:
        print(f"CFD-R004 site.protocol: {error!r}", file=sys.stderr)
        return 1
    json.dump(book, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
