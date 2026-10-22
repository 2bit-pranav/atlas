"""Shared output helpers for the Atlas skill scripts (skills/AGENTS.md).

Each script is a ready-made command the model runs through `shell`: a 2B model
runs an existing script reliably and writes library code badly.

**The token budget is the important part.** Output goes straight into a 32k
context window, so every script:

* prints at most ~1500 tokens by default;
* says plainly that it truncated, and which flag shows more;
* never returns partial data as if it were complete.

The last matters most: a model that cannot tell "everything" from "the first
page" answers confidently from a fragment.

Failures are one line (`fail`, `require`), never a traceback: a traceback is
noise to read past, and a missing-module one provokes `pip install`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

#: Roughly four characters per token for English prose and tables.
CHARS_PER_TOKEN = 4

DEFAULT_BUDGET_TOKENS = 1500


def budget_to_chars(tokens: int) -> int:
    return max(200, tokens * CHARS_PER_TOKEN)


def truncate(text: str, limit: int, *, more_hint: str) -> tuple[str, bool]:
    """Cut to `limit` characters and say so, with the flag that shows more.

    Returns (text, was_truncated). The marker fits *inside* the limit, so the
    explanation never overruns the budget.
    """
    if len(text) <= limit:
        return text, False
    marker = f"\n\n[truncated at {limit} chars; {more_hint}]"
    return text[: max(0, limit - len(marker))] + marker, True


def header(**fields: Any) -> str:
    """A short, greppable header. Models read these better than prose."""
    return "\n".join(f"{k}: {v}" for k, v in fields.items() if v not in (None, ""))


def fail(message: str, *, hint: str = "") -> int:
    """Print `ERROR: message` (and an optional hint) to stderr; return exit code 2.

    A missing module is reworded, because a model "fixes" it with `pip install`,
    which lands in a different interpreter and changes nothing.
    """
    if isinstance(message, str) and "ModuleNotFoundError" in message:
        package = message.rsplit("No module named", 1)[-1].strip().strip("'\"").split("'")[0]
        return fail(
            f"a required library is missing: {package}",
            hint=f"this is an Atlas setup problem, not something to install. "
                 f"Do NOT run pip install -- the interpreter that runs these "
                 f"scripts already has the library; a bare `pip` installs "
                 f"somewhere else. Report this to the user.",
        )
    body = f"ERROR: {message}"
    if hint:
        body += f"\nhint: {hint}"
    print(body, file=sys.stderr)
    return 2


def unquote(value: str) -> str:
    """Strip quoting a shell left behind.

    Under Windows `cmd.exe` an argument wrapped in `"..."` or `'...'` can reach
    argparse with the quotes attached, which then fails as `no such file`.

    Stripped repeatedly, so a doubly quoted value survives. Paired quotes only:
    an unbalanced one is more likely part of the value than bad quoting.
    """
    value = value.strip()
    while len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def join_sql(parts: list[str]) -> str:
    """Rebuild a SQL statement that the shell split into pieces.

    Quoting that survives `cmd.exe` is still split on spaces before argparse:

        'SELECT SUM("revenue") FROM "Mar"'
        -> ['SELECT, SUM(revenue), FROM, Mar']

    The fragments keep the right characters, so joining them with single spaces
    rebuilds the statement. Tolerated here rather than documented in SKILL.md
    because a 2B model will get the quoting wrong again.
    """
    return " ".join(parts).replace("\n", " ").strip()


def require(*names: str) -> tuple[Any, ...]:
    """Import third-party libraries, failing with a message the model can use.

    A bare module-level import fails before `main_wrapper` can catch it, and
    the traceback provokes `pip install`, which lands in a different
    interpreter and fixes nothing. So scripts import third-party libraries here.
    """
    import importlib

    try:
        return tuple(importlib.import_module(name) for name in names)
    except ModuleNotFoundError as exc:
        missing = (exc.name or names[0]).strip("'")
        raise SystemExit(
            f"ERROR: a required library is missing: {missing}\n"
            f"hint: this is an Atlas setup problem, not something to install. "
            f"Do NOT run pip install -- the interpreter running these scripts "
            f"already has the library; a bare `pip` installs somewhere else. "
            f"Report this to the user."
        ) from None


def resolve(path: str) -> Path:
    """An input file's path. An absolute path as is. A relative one is looked
    for where the command runs (the chat's workspace), then in each allowed
    folder (`$ATLAS_FOLDERS`, the same rule as Atlas's file tools), then in
    each chat folder under ./data/chats. A bare name found nowhere is looked
    up by name in the allowed folders (`find_by_name`); else returned
    unchanged."""
    import os

    path = unquote(path)
    candidate = Path(path)
    if candidate.is_absolute() or candidate.exists():
        return candidate
    folders = [Path(f) for f in os.environ.get("ATLAS_FOLDERS", "").split(os.pathsep) if f]
    for folder in folders:
        if (folder / path).exists():
            return folder / path
    here = Path.cwd() / "data" / "chats"
    if here.is_dir():
        for chat in here.iterdir():
            target = chat / path
            if target.exists():
                return target
    if candidate.parent == Path(".") and (found := find_by_name(candidate.name, folders)) is not None:
        return found
    return candidate


#: Folders `find_by_name` never walks: tools' and programs' own trees.
_SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", "site-packages", "AppData"}


def find_by_name(name: str, folders: list[Path], depth: int = 4, budget: int = 20000) -> Path | None:
    """The one file called `name` within `depth` levels of the allowed folders.

    After listing `Demo/Invoices`, a small model often names a file by its bare
    name (`invoice-x.pdf`), which exists nowhere relative to anything. Only a
    *unique* match is returned, so two files of the same name are never
    guessed between; the walk is bounded, and for inputs only (never where to
    write).
    """
    import os

    matches: list[Path] = []
    seen = 0
    for root in folders:
        base = len(Path(root).parts)
        for dirpath, dirnames, filenames in os.walk(root):
            seen += len(filenames) + len(dirnames)
            if seen > budget:
                return None
            if len(Path(dirpath).parts) - base >= depth:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
            if name in filenames:
                matches.append(Path(dirpath) / name)
                if len(matches) > 1:
                    return None
    return matches[0] if matches else None


def is_link(value: str) -> bool:
    return unquote(value).lower().startswith(("http://", "https://", "file://"))


#: A document larger than this is refused, local or downloaded.
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024

#: The one place a document link is opened. The skill scripts (`fetch`) and
#: the backend (the extension's PDF import and PDF viewer) all come through
#: here, so `file://` and `http(s)://` are checked the same way everywhere.


class LinkError(ValueError):
    """A document link that cannot be opened; the message is one line."""


def open_link(link: str, magic: bytes, kind: str) -> tuple[str, Path | None, bytes | None]:
    """A document link, checked: (file name, local path or None, downloaded bytes or None).

    `file://` is read where it is; `http(s)://` is downloaded. Either way the
    document must start with `magic` (`b"%PDF"`) and be at most 100 MB, so a
    link can never be used to read some other file off the disk. A link that
    returns a web page instead (a login page, an error) is refused rather than
    read as a broken document.
    """
    import re
    import urllib.parse
    import urllib.request

    parsed = urllib.parse.urlparse(link)
    if parsed.scheme == "file":
        source = Path(urllib.request.url2pathname(parsed.netloc + parsed.path))
        if not source.is_file():
            raise LinkError(f"no such file: {source}")
        if source.stat().st_size > MAX_DOWNLOAD_BYTES:
            raise LinkError(f"{source.name} is larger than {MAX_DOWNLOAD_BYTES >> 20} MB")
        with source.open("rb") as fh:
            if not fh.read(len(magic)).startswith(magic):
                raise LinkError(f"{source.name} is not a {kind}")
        return source.name, source, None
    if parsed.scheme not in ("http", "https"):
        raise LinkError(f"cannot open a {parsed.scheme or 'plain'} link")

    request = urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0 (Atlas)", "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(MAX_DOWNLOAD_BYTES + 1)
            final = response.geturl()
            disposition = response.headers.get("Content-Disposition", "")
    except Exception as exc:  # noqa: BLE001 - one line, not a traceback
        raise LinkError(f"could not download {link}: {exc}") from None
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise LinkError(f"{link} is larger than {MAX_DOWNLOAD_BYTES >> 20} MB")
    if not data.startswith(magic):
        raise LinkError(f"{link} returned a web page, not a {kind} (it may need a login)")
    m = re.search(r"""filename\*?=(?:UTF-8'')?"?([^";]+)""", disposition)
    name = urllib.parse.unquote(m.group(1) if m else Path(urllib.parse.urlparse(final).path).name)
    return name or "download", None, data


def save_link(link: str, suffix: str, magic: bytes, kind: str, folder: Path,
              copy_local: bool = False) -> tuple[Path, str]:
    """A document link as a file: (path, what happened).

    A web document is saved in `folder` under its own name, so later steps
    (merge, convert, a second read) can name it; the same link again reuses
    the copy. A local one is used where it is, or copied into `folder` with
    `copy_local` (an attachment, which the agent's workspace should hold).
    """
    import json
    import re
    import shutil

    index = folder / ".atlas-downloads.json"
    try:
        known = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        known = {}
    if (name := known.get(link)) and (folder / name).is_file():
        return folder / name, f"downloaded earlier as {name}"

    name, source, data = open_link(link, magic, kind)
    if source is not None and not copy_local:
        return source, "local file"
    stem = re.sub(r"[^\w.-]+", "-", Path(name).stem).strip("-.")[:80] or "download"
    target, n = folder / f"{stem}{suffix}", 2
    while target.exists():
        target, n = folder / f"{stem}-{n}{suffix}", n + 1
    if source is not None:
        shutil.copyfile(source, target)
        return target, f"copied to {target.name}"
    target.write_bytes(data or b"")
    known[link] = target.name
    index.write_text(json.dumps(known, indent=1), encoding="utf-8")
    return target, f"downloaded to {target.name}"


def fetch(link: str, suffix: str, magic: bytes) -> tuple[Path, str]:
    """`save_link` for the scripts: into the workspace (the current folder), failing in one line."""
    kind = f"{suffix.lstrip('.').upper()} file"
    try:
        return save_link(unquote(link), suffix, magic, kind, Path.cwd())
    except LinkError as exc:
        hint = ("\nhint: ask the user to open it in the browser and ask from the Atlas side panel, "
                "or to download it and attach it") if "web page" in str(exc) else ""
        raise SystemExit(f"ERROR: {exc}{hint}") from None


def add_common_arguments(parser: Any) -> Any:
    """`--max-tokens` on every script, so "show me more" is always possible."""
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_BUDGET_TOKENS,
        help="output budget in tokens (default %(default)s)",
    )
    parser.add_argument(
        "--no-truncate",
        action="store_true",
        help="print everything, ignoring the budget",
    )
    return parser


def limit_for(args: Any) -> tuple[int, str]:
    if getattr(args, "no_truncate", False):
        return 10**9, "--no-truncate"
    return budget_to_chars(args.max_tokens), f"--max-tokens {args.max_tokens * 2}"


def main_wrapper(fn: Any) -> int:
    """Run a script's main(), turning any escape into a one-line ERROR."""
    try:
        return fn()
    except SystemExit:
        raise
    except FileNotFoundError as exc:
        return fail(f"file not found: {exc.filename}",
                    hint="check the path you were given in the message")
    except Exception as exc:  # noqa: BLE001
        return fail(f"{type(exc).__name__}: {exc}")


__all__ = [
    "CHARS_PER_TOKEN",
    "DEFAULT_BUDGET_TOKENS",
    "add_common_arguments",
    "budget_to_chars",
    "fail",
    "header",
    "join_sql",
    "limit_for",
    "main_wrapper",
    "require",
    "resolve",
    "truncate",
    "unquote",
]

# ------------------------------------------------------------------ images --

#: Images smaller than this on both sides are rules, bullets and logos, not
#: content worth carrying into a rewrite.
MIN_IMAGE_PX = 64
#: Per document. A brochure with 200 thumbnails would otherwise flood the reply.
MAX_IMAGES = 30


def images_dir(source: Path) -> Path:
    """Where a document's extracted images go: a hidden folder beside it.

    Hidden (dot-prefixed) so the chat's file list and download chips are not
    filled with figure-1.png, figure-2.png ... every time a document is read.
    """
    folder = source.parent / ".atlas-images" / source.stem
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def image_line(path: Path, caption: str) -> str:
    """How an image is printed: Markdown that create_document accepts as is."""
    return f"![{caption}]({path.resolve().as_posix()})"


# ------------------------------------------------------------------ pages --


def page_list(spec: str, total: int) -> list[int]:
    """`1-3,7`, `5-`, `all` -> 0-based indices, **in the order given**.

    Unlike `read_pdf.parse_pages` this keeps order and repeats, because
    merging `3,1-2` means page 3 first. Raises ValueError on anything that
    is not a page, so a typo fails instead of silently dropping pages.
    """
    spec = (spec or "all").strip().lower()
    if spec in ("all", "*", ""):
        return list(range(total))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        a, dash, b = part.partition("-")
        start = int(a) if a.strip() else 1
        end = (int(b) if b.strip() else total) if dash else start
        if not (1 <= start <= total and 1 <= end <= total):
            raise ValueError(f"page {part!r} is outside 1-{total}")
        step = 1 if end >= start else -1
        out.extend(i - 1 for i in range(start, end + step, step))
    return out


def output_path(name: str) -> Path:
    """Where a script writes: a bare name lands in the chat workspace (cwd)."""
    path = Path(unquote(name))
    path = path if path.is_absolute() else Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def default_output(src: Path, suffix: str) -> Path:
    """Where a conversion goes when no output is named: beside the input when
    that is in the workspace (where the model then looks for it), else in the
    workspace, so the user gets it as a download."""
    target = src.with_suffix(suffix)
    try:
        target.resolve().relative_to(Path.cwd().resolve())
        return target
    except ValueError:
        return Path.cwd() / target.name


def shown(path: Path) -> str:
    """A path as the model should repeat it: relative to the workspace when it
    is in it (`Demo/x.docx`, not a bare `x.docx` that reads as "beside the
    input"), else in full; forward slashes either way."""
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def created(names: Path | str, **details: Any) -> str:
    """The lines every writing script ends with, so the model tells the user."""
    names = shown(names) if isinstance(names, Path) else names
    return header(created=names, **details) + "\nThe user sees it as a download in the chat."
