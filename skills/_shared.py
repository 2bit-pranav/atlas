"""Shared output helpers for the Atlas skill scripts (skills/AGENTS.md).

Every script here is a ready-made command-line tool that the model runs through
`shell`. It never writes library code: asking a 2B model to write correct
`python-docx` code is a bad bet, and asking it to run a script that already
exists is not.

**The token budget is the important part.** A tool result goes straight into
the context window. One careless `read` of a 400-page PDF would fill 32k tokens
and there would be no room left to answer the question. So every script:

* prints at most ~1500 tokens by default;
* says plainly that it truncated, and which flag shows more;
* never silently returns partial data as if it were complete.

The last one matters more than the limit. A model that cannot tell "here is
everything" from "here is the first page" will confidently answer from a
fragment, and the user has no way to notice.

Libraries are chosen for speed and availability, not sophistication. There is
no Docling and no VLM here: a scanned PDF has no text layer to read, and
pretending otherwise would produce an empty document described as a failure.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

#: Roughly four characters per token for English prose and tables.
CHARS_PER_TOKEN = 4

#: Default output budget: about 1,500 tokens.
DEFAULT_BUDGET_TOKENS = 1500


def budget_to_chars(tokens: int) -> int:
    return max(200, tokens * CHARS_PER_TOKEN)


def truncate(text: str, limit: int, *, more_hint: str) -> tuple[str, bool]:
    """Cut to `limit` characters and say so, with the flag that shows more.

    Returns (text, was_truncated). The marker is appended *inside* the limit so
    the script never overruns its own budget by adding an explanation.
    """
    if len(text) <= limit:
        return text, False
    marker = f"\n\n[truncated at {limit} chars; {more_hint}]"
    return text[: max(0, limit - len(marker))] + marker, True


def header(**fields: Any) -> str:
    """A short, greppable header. Models read these better than prose."""
    return "\n".join(f"{k}: {v}" for k, v in fields.items() if v not in (None, ""))


def fail(message: str, *, hint: str = "") -> int:
    """Report a failure in a form the model can act on, and exit non-zero.

    Never a traceback. A stack trace in a tool result is noise the model has to
    read past, and it hides the one sentence that says what to do instead.

    `ModuleNotFoundError` gets special handling, because it is the one failure a
    model reliably "fixes" the wrong way: it responds by running `pip install`,
    which writes to a user site-packages directory, changes nothing about the
    interpreter the skill actually runs under, and leaves the environment
    quietly diverged from the project. The message says what is wrong instead.
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

    Windows `cmd.exe` does not process quotes the way a POSIX shell does, so an
    argument the model carefully wrapped in `"..."` or `'...'` can arrive here
    with the quote characters still attached. `cmd /c script.py "C:\\data\\a.xlsx"`
    has been observed reaching argparse as `"C:\\data\\a.xlsx"`, which fails with
    `no such file: "C:\\data\\a.xlsx"` -- an error that points at the filesystem
    when the real problem is a character of punctuation.

    Stripped repeatedly rather than once, so an argument that was quoted *and*
    left with a stray pair survives. Paired quotes only: an unbalanced one is
    more likely to be a legitimate character in the value than bad quoting.
    """
    value = value.strip()
    while len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def join_sql(parts: list[str]) -> str:
    """Rebuild a SQL statement that the shell split into pieces.

    A statement has spaces in it, so any quoting that survives `cmd.exe` is
    tokenised on those spaces before argparse ever sees it:

        'SELECT SUM("revenue") FROM "Mar"'
        -> ['SELECT, SUM(revenue), FROM, Mar']

    Every one of those fragments still carries the right characters, so joining
    them back with single spaces reconstructs the statement exactly. This is
    why the fix is here rather than in a quoting instruction in `SKILL.md`: a
    2B model will get the quoting wrong again, and a script that tolerates
    mangled quoting cannot be broken by it.
    """
    return " ".join(parts).replace("\n", " ").strip()


def require(*names: str) -> tuple[Any, ...]:
    """Import third-party libraries, failing with a message the model can use.

    A bare `import duckdb` at module scope raises before `main_wrapper` can catch
    anything, so the model received a four-line traceback and responded by
    running `pip install duckdb` -- which writes to a user site-packages
    directory, fixes nothing, and leaves the environment quietly diverged from
    the project.

    So every script imports its heavy dependencies through here. The one failure
    this skill must never produce is a model patching its own environment, and a
    traceback is what provokes it.
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
    """Accept an absolute path, or resolve relative to the chat directory."""
    path = unquote(path)
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    here = Path.cwd() / "data" / "chats"
    if here.is_dir():
        for chat in here.iterdir():
            target = chat / path
            if target.exists():
                return target
    return candidate


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


def created(names: Path | str, **details: Any) -> str:
    """The lines every writing script ends with, so the model tells the user."""
    names = names.name if isinstance(names, Path) else names
    return header(created=names, **details) + "\nThe user sees it as a download in the chat."
