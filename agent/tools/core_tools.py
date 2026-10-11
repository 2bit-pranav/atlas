"""The core, always-on tools (spec section 11.2).

Eleven tools, deliberately small and flat. Every one returns the
``ok: ...`` / ``error[...]`` rendering from :mod:`agent.tools.contract`, takes
handles rather than paths, and reaches data only through ``ToolContext``.

Each tool reads its per-run context out of ``tool_context.invocation_state``,
which is how the agent gets one to it without any tool holding global state.
"""

from __future__ import annotations

import json
import re
from typing import Any

from strands import tool
from strands.types.tools import ToolContext as StrandsToolContext

from agent.core.errors import NotFound
from agent.ingest.contract import estimate_tokens
from agent.tools.contract import ToolError, ToolOutput
from agent.tools.guard import guarded
from agent.tools.offloader import ResultOffloader, _tidy_float, tsv
from agent.tools.validate import clamp_int, one_of, positive_int


def _ctx(tool_context: StrandsToolContext) -> Any:
    ctx = tool_context.invocation_state.get("atlas_ctx")
    if ctx is None:  # pragma: no cover - only if the runtime is miswired
        raise ToolError("failed", "tool context is missing; this is a harness bug")
    return ctx


def _offloader(ctx: Any) -> ResultOffloader:
    return ResultOffloader.from_settings(ctx.catalog, ctx.settings)


# ------------------------------------------------------------------ files ----


@tool(context=True)
@guarded
def list_files(tool_context: StrandsToolContext) -> dict[str, Any]:
    """List the documents and stored objects attached to this chat.

    Returns one line per attachment: its handle, name, and shape. Start here.
    """
    ctx = _ctx(tool_context)
    items = []
    for attachment in ctx.attachments.attachments_for_chat(ctx.chat_id):
        status = ctx.attachments.status(attachment["id"])
        outline = status.get("outline") or {}
        if outline.get("kind") == "tabular":
            shape = (f"{len(outline['sheets'])} sheets, {outline['total_rows']} rows, "
                     f"view {outline.get('unified_view')}")
        elif outline.get("sections"):
            shape = f"{len(outline['sections'])} sections"
        else:
            shape = f"{outline.get('lines', 0)} lines"
        items.append(
            f"{status['handle']}  {status['original_name']}  "
            f"[{status['status']}]  {shape}"
        )
        # Same bytes, uploaded again under another name. Without this the user
        # says "resume_new.pdf" and the agent cannot connect it to f1.
        aliases = status.get("aliases") or []
        if aliases:
            items.append(
                f"    {status['handle']} is also known as: " + ", ".join(aliases)
            )

    objects = ctx.catalog.list(ctx.chat_id)
    for obj in objects[-5:]:
        items.append(f"{obj.id}  {obj.name}  ({obj.kind}, {obj.row_count or '?'} rows)")

    summary = f"{len(items)} item(s)" if items else "nothing attached to this chat yet"
    return ToolOutput(summary="\n".join(items) if items else summary).to_result()


@tool(context=True)
@guarded
def outline(handle: str, tool_context: StrandsToolContext) -> dict[str, Any]:
    """Show the structure of a document: sheets, sections, row and token counts.

    Use this before reading a file, so you know what is in it without paying
    for the whole thing.
    """
    ctx = _ctx(tool_context)
    attachment = ctx.resolve_handle(handle)
    status = ctx.attachments.status(attachment["id"])
    if status["status"] != "ready":
        raise ToolError("not_ready", f"{handle} is {status['status']}")

    data = status["outline"] or {}
    lines: list[str] = []
    if data.get("kind") == "tabular":
        lines.append(f"{handle} - spreadsheet, {len(data['sheets'])} sheets, "
                     f"{data['total_rows']} rows total")
        for sheet in data["sheets"]:
            mark = " (in unified view)" if sheet.get("unified") else ""
            lines.append(
                f"  {sheet['sheet']}: table {sheet['table']}, {sheet['rows']} rows, "
                f"columns: {', '.join(sheet['columns'])}{mark}"
            )
        if data.get("unified_view"):
            lines.append(f"  unified view: {data['unified_view']} (adds a _sheet column)")
    else:
        lines.append(f"{handle} - {data.get('kind', 'text')}")
        for key in ("lines", "chars", "approx_tokens"):
            if key in data:
                lines.append(f"  {key}: {data[key]}")
        for section in (data.get("sections") or [])[:20]:
            lines.append(f"  section: {section}")

    if status.get("token_count"):
        lines.append(f"  indexed tokens: {status['token_count']}")
    for warning in status.get("warnings") or []:
        lines.append(f"  warn: {warning}")

    return ToolOutput(summary="\n".join(lines)).to_result()


# ------------------------------------------------------------------- read ----


@tool(context=True)
@guarded
def read(
    handle: str,
    chunk_id: str | None = None,
    section: str | None = None,
    max_chars: int = 4000,
    tool_context: StrandsToolContext | None = None,
) -> dict[str, Any]:
    """Read text from a document. Pass chunk_id to read around a search hit.

    Returns prose only. For a spreadsheet use describe() or query() instead --
    rows belong in SQL, not in the context window.
    """
    ctx = _ctx(tool_context)
    attachment = ctx.resolve_handle(handle)
    max_chars = clamp_int(max_chars, "max_chars", 500, 40_000, 4000)

    chunks = ctx.attachments.chunks(attachment["id"])
    if not chunks:
        raise ToolError("not_found", f"{handle} has no indexed text to read")

    if chunk_id:
        index = next((i for i, c in enumerate(chunks) if c["id"] == chunk_id), None)
        if index is None:
            valid = [c["id"] for c in chunks[:5]]
            raise ToolError("not_found", f"no chunk {chunk_id!r} in {handle}", valid)
        selected = chunks[max(0, index - 1) : index + 2]
    elif section:
        selected = [c for c in chunks if (c["section_path"] or "") == section]
        if not selected:
            valid = sorted({c["section_path"] for c in chunks if c["section_path"]})[:8]
            raise ToolError("not_found", f"no section {section!r} in {handle}", valid)
    else:
        selected = chunks

    body = "\n\n".join(
        f"[{c['section_path'] or handle}] {c['text']}" for c in selected
    )
    if len(body) > max_chars:
        body = body[:max_chars] + "\n...(clipped; raise max_chars or pick a section)"

    return _offloader(ctx).render(
        ctx, ToolOutput(summary=f"{handle}: {len(selected)} chunk(s)"),
        body=body, kind="text", name=f"{handle}_read", shape=f"{len(selected)} chunks",
    )


# ----------------------------------------------------------------- search ----


@tool(context=True)
@guarded
def search(
    target: str, query: str, limit: int = 5,
    tool_context: StrandsToolContext | None = None,
) -> dict[str, Any]:
    """Search for a phrase. target is a file handle like f1, or 'all'.

    Returns the best snippets with their location and a chunk id you can pass to
    read() for the surrounding text.
    """
    ctx = _ctx(tool_context)
    limit = clamp_int(limit, "limit", 1, 20, 5)

    # "all" is the common case; a handle narrows to one document. Resolving the
    # handle here means search never sees a path or an id it did not get handed.
    attachment_ids = None
    if target.strip().lower() not in ("all", "*", ""):
        attachment = ctx.resolve_handle(target)
        attachment_ids = [attachment["id"]]
    else:
        attachment_ids = [a["id"] for a in ctx.attachments.attachments_for_chat(ctx.chat_id)]

    hits = ctx.attachments.search_chunks(
        query, attachment_ids=attachment_ids, limit=limit
    )
    if not hits:
        known = ["all"] + [a["handle"] for a in ctx.attachments.attachments_for_chat(ctx.chat_id)]
        raise ToolError("not_found", f"nothing found for {query!r}", known)

    lines = []
    for hit in hits:
        where = hit.get("section_path") or hit.get("attachment_id", "")
        snippet = " ".join((hit.get("snippet") or "").split())
        lines.append(f"- {hit['id']} [{where}] {snippet}")

    return ToolOutput(
        summary=f"{len(hits)} hit(s) for {query!r}\n" + "\n".join(lines)
    ).to_result()


# --------------------------------------------------------------- describe ----


@tool(context=True)
@guarded
def describe(target: str, tool_context: StrandsToolContext | None = None) -> dict[str, Any]:
    """Describe a table or a file: schema, sample rows, and data-quality warnings.

    target is a table name (f1_January), a saved object id (r3), or a file
    handle (f2). For a table this is the cheapest way to learn its column names,
    which is usually what you need before writing SQL.
    """
    ctx = _ctx(tool_context)

    # Resolve what the model gave us to a table name, or decide it is a file.
    # Order matters: ids before raw names, so a saved result describes as the
    # table it came from rather than as a (missing) file.
    table_name: str | None = None
    obj = ctx.catalog.get(target)
    if obj is not None:
        if obj.node_id and obj.node_id not in ctx.visible_node_ids():
            raise ToolError("not_found", f"no object {target!r} in this chat")
        table_name = obj.name
    elif target not in ("f", "all"):
        try:
            table_name = ctx.table_name(target)
        except ToolError:
            table_name = None  # fall through to the file branch

    if table_name is not None:
        info = ctx.duck.describe(table_name, sample=5)
        body = tsv(info["samples"], info["columns"])
        lines = [
            f"{table_name}: {info['row_count']} rows",
            f"columns: {', '.join(info['columns'])}",
            f"sample:\n{body}",
        ]
        for warning in ctx.duck.quality_warnings(table_name):
            lines.append(f"warn: {warning}")
        text = "\n".join(lines)
        return _offloader(ctx).render(
            ctx, ToolOutput(summary=text),
            body=text, kind="table", store="duckdb",
            shape=f"{info['row_count']}x{len(info['columns'])}",
            name=table_name,
        )

    # Otherwise it has to be a file handle, or the model mistyped something.
    try:
        attachment = ctx.resolve_handle(target)
    except NotFound:
        valid = sorted(ctx.duck.table_names())
        valid += [a["handle"] for a in ctx.attachments.attachments_for_chat(ctx.chat_id)]
        raise ToolError("not_found", f"{target!r} is not a table, object or file", valid) from None

    status = ctx.attachments.status(attachment["id"])
    lines = [
        f"{status['handle']} = {status['original_name']} ({status['status']})",
        f"size: {status['size']} bytes, pages: {status.get('page_count')}, "
        f"tokens: {status.get('token_count')}",
    ]

    # A spreadsheet describes itself in terms of its tables, because the next
    # thing the model wants is to write SQL against them. Returning only file
    # metadata here left it with nowhere to go but ``outline`` -- and on the
    # real model it never got that far.
    outline = status.get("outline") or {}
    if outline.get("kind") == "tabular":
        lines.append(
            f"{len(outline['sheets'])} sheet(s), {outline['total_rows']} rows. "
            "Query these tables with query(sql):"
        )
        for sheet in outline["sheets"]:
            mark = " [in the unified view]" if sheet.get("unified") else ""
            lines.append(
                f"  {sheet['sheet']} -> {sheet['table']} "
                f"({sheet['rows']} rows){mark}"
            )
        if outline.get("unified_view"):
            lines.append(
                f"  all sheets at once: {outline['unified_view']} "
                "(has an extra _sheet column)"
            )
    else:
        lines.append(f"kind: {outline.get('kind', 'text')}, "
                     f"lines: {outline.get('lines', 0)}, "
                     f"sections: {len(outline.get('sections') or [])}")

    if status.get("warnings"):
        lines.append("warnings: " + "; ".join(status["warnings"]))
    return ToolOutput(summary="\n".join(lines)).to_result()


# ------------------------------------------------------------------ query ----


@tool(context=True)
@guarded
def query(sql: str, save_as: str | None = None, tool_context: StrandsToolContext | None = None) -> dict[str, Any]:
    """Run a read-only SQL query against this chat's tables.

    The result is ALWAYS saved as an object; it is only shown inline when it is
    small. Use show() or another query() on the saved id for the full thing.
    """
    ctx = _ctx(tool_context)

    try:
        rows, columns = _run_readonly(ctx, sql)
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001
        tables = ctx.duck.table_names()
        raise ToolError("failed", f"SQL failed: {exc}", tables) from exc

    if not columns:
        columns = list(rows[0].keys()) if rows else []

    # The *stored* body is every row, not a display excerpt. "Always saved" is
    # the guarantee that makes it safe for the model not to ask twice, so
    # truncating here would quietly break it. Clipping for display is the
    # offloader's job, and it has its own token budget.
    body = tsv(rows, columns, limit=max(len(rows), 1))
    summary = _result_summary(rows, columns)
    return _offloader(ctx).render(
        ctx,
        # The shape alone is not an answer. "1 rows x 1 cols" tells the model
        # nothing, and it fills the gap by inventing a number -- measured: the
        # same query reported 29623.19, 29517.98 and 33196.28 across three runs
        # against a true 425184.67, because the value was never in the result.
        # An aggregate's entire content is its one value, so keep_summary stops
        # the offloader from replacing it with a shape.
        ToolOutput(summary=summary,
                   data={"rows": len(rows), "columns": columns}),
        body=body, kind="table", store="duckdb",
        shape=f"{len(rows)}x{len(columns)}", name=save_as,
        keep_summary=summary if len(rows) == 1 and len(columns) == 1 else None,
    )


def _result_summary(rows: list[dict[str, Any]], columns: list[str]) -> str:
    """One line that names the value when there is one worth naming.

    Small results get their values inline -- cheap, and it is what makes the
    answer answerable. Aggregates (one row, one column) are named even when
    small, because a single number is the whole point of the query.
    """
    shape = f"{len(rows)} rows x {len(columns)} cols"
    if not rows or not columns:
        return shape
    if len(rows) == 1 and len(columns) == 1:
        return f"{shape}: {columns[0]} = {_show(next(iter(rows[0].values())))}"
    if len(rows) <= 5:
        return f"{shape}\n{tsv(_clean(rows), columns, clean=True)}"
    return shape


def _show(value: Any) -> str:
    """A float in the form a reader would recognise.

    ``425184.6699999999`` is the same number as ``425184.67``, and the model
    repeats whatever it is given verbatim, so float noise in the summary becomes
    float noise in the answer. The stored body keeps full precision, so ``show``
    on the object can still return the exact value.
    """
    if isinstance(value, float):
        value = _tidy_float(value)
        # ``str``, not ``%g``: %g means six *significant* digits, so it turned
        # 425184.67 back into 425185 and undid the rounding one line above.
        return str(value)
    return str(value)


def _clean(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows with floats tidied, for the small-result preview only."""
    return [
        {k: _tidy_float(v) if isinstance(v, float) else v for k, v in row.items()}
        for row in rows
    ]


# ------------------------------------------------------------------- show ----


@tool(context=True)
@guarded
def show(
    target: str,
    rows: int = 20,
    offset: int = 0,
    cols: str | None = None,
    tool_context: StrandsToolContext | None = None,
) -> dict[str, Any]:
    """Page through a stored object. target is an object id such as r3.

    Use this instead of re-running a query when you only need more of a result
    you already have.
    """
    ctx = _ctx(tool_context)
    rows = clamp_int(rows, "rows", 1, 200, 20)
    offset = clamp_int(offset, "offset", 0, 10_000_000, 0)
    obj = ctx.resolve(target)

    # A saved object has one of two shapes, and both must page correctly:
    # a real DuckDB table (from ``describe``/ingest), or the stored TSV of a
    # query result, whose ``name`` is a label the model chose and not a table.
    if obj.kind == "table":
        try:
            table = ctx.table_name(obj.name)
        except ToolError:
            table = None
    else:
        table = None

    if table is not None:
        wanted = [c.strip() for c in cols.split(",")] if cols else None
        if wanted:
            available = ctx.duck.columns(table)
            unknown = [c for c in wanted if c not in available]
            if unknown:
                raise ToolError("bad_arg", f"unknown column(s) {unknown}", available)
        data = ctx.duck.conn.execute(
            f'SELECT * FROM "{table}" LIMIT {rows} OFFSET {offset}'
        )
        result_rows = [dict(zip([d[0] for d in data.description], r)) for r in data.fetchall()]
        columns = wanted or [d[0] for d in data.description]
        body = tsv(result_rows, columns)
        return ToolOutput(
            summary=f"{obj.id} ({obj.name}) rows {offset}-{offset + len(result_rows)}"
                    f"\n{body}"
        ).to_result()

    # Stored text: page by line, so ``offset``/``rows`` mean the same thing as
    # they do for a table's rows.
    body = ctx.catalog.get_text(obj.id)
    if body is None:
        raise ToolError(
            "not_ready", f"{obj.id} has no stored body yet; re-run the tool that made it"
        )
    lines = body.splitlines()
    if cols:
        raise ToolError(
            "bad_arg",
            "cols only applies to table objects; this one is stored as text",
        )
    window = lines[offset : offset + rows]
    if not window:
        raise ToolError(
            "bad_arg",
            f"offset {offset} is past the end ({len(lines)} lines)",
            [f"offset 0..{max(0, len(lines) - 1)}"],
        )
    text = "\n".join(window)
    more = len(lines) - (offset + len(window))
    tail = f"\n... {more} more line(s); show({obj.id}, offset={offset + rows})" if more > 0 else ""
    return ToolOutput(
        summary=f"{obj.id} ({obj.name}) lines {offset}-{offset + len(window)}"
                f" of {len(lines)}\n{text}{tail}"
    ).to_result()


# ---------------------------------------------------------------- collect ----


@tool(context=True)
@guarded
def collect(table: str, rows: list[dict[str, Any]], tool_context: StrandsToolContext) -> dict[str, Any]:
    """Append a few rows you extracted from prose to a named collector table.

    The first call fixes the schema; later calls must match it. Use this to turn
    facts scattered across many documents into one queryable table.
    """
    ctx = _ctx(tool_context)
    if not rows:
        raise ToolError("bad_arg", "rows must contain at least one row")
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ToolError("bad_arg", "rows must be a list of objects, e.g. [{\"a\": 1}]")

    from agent.ingest.contract import sanitize_identifier

    name = f"collect_{sanitize_identifier(table)}"
    duck = ctx.duck_write()
    existing = duck.columns(name) if name in duck.table_names() else []

    if existing:
        # The first call fixed the schema. Reject rather than silently drop a
        # column the model invented -- a dropped key is a fact it believes it
        # saved.
        for row in rows:
            unknown = [k for k in row if k not in existing]
            if unknown:
                raise ToolError(
                    "bad_arg",
                    f"unknown column(s) {unknown} for {name}",
                    existing,
                )
        payload = [{k: r.get(k) for k in existing} for r in rows]
        written = duck.append_rows(name, payload)
    else:
        # Union of keys in first-seen order, so a row that omits an optional
        # column still lands with NULL there rather than being dropped.
        columns: list[str] = []
        for row in rows:
            for key in row:
                if key not in columns:
                    columns.append(str(key))
        payload = [{k: r.get(k) for k in columns} for r in rows]
        written = duck.add_table(name, payload)
        existing = duck.columns(name)

    return ToolOutput(
        summary=f"collected {written} row(s) into {name} "
                f"(now {duck.row_count(name)} rows; columns: {', '.join(existing)})"
    ).to_result()


# --------------------------------------------------------------- notepad ----


@tool(context=True)
@guarded
def plan(items: list[str], tool_context: StrandsToolContext) -> dict[str, Any]:
    """Set or replace your working plan. Call this early on multi-step tasks.

    Each item is a short string; mark progress by calling plan() again with
    the full updated list.
    """
    ctx = _ctx(tool_context)
    return _notepad_set(ctx, "plan", items, limit=12,
                        label="plan", item_key="text")


@tool(context=True)
@guarded
def note(text: str, ref: str | None = None, tool_context: StrandsToolContext | None = None) -> dict[str, Any]:
    """Record a fact or decision you want to keep. Short text, optional ref.

    Put facts and decisions here and data in tables. ref can point at an
    object or a location, e.g. r3 or f1 s2.
    """
    ctx = _ctx(tool_context)
    entry = {"text": text, "ref": ref}
    return _notepad_push(ctx, "notes", entry, limit=20, label="note")


# ---------------------------------------------------------------- helpers ----


def _notepad_set(ctx: Any, key: str, items: list[str], *, limit: int, label: str,
                 item_key: str) -> dict[str, Any]:
    if len(items) > limit:
        raise ToolError(
            "too_large", f"{label} holds at most {limit} items, got {len(items)}"
        )
    from agent.tools.notepad import write_plan

    count = write_plan(ctx, items)
    return ToolOutput(summary=f"plan saved ({count} items)").to_result()


def _notepad_push(ctx: Any, key: str, entry: dict[str, Any], *, limit: int,
                  label: str) -> dict[str, Any]:
    from agent.tools.notepad import push_note

    items = push_note(ctx, entry)
    if len(items) > limit:
        # Hard cap returns an error rather than silently dropping (section 10).
        raise ToolError(
            "too_large",
            f"notepad full {len(items)}/{limit}; merge or remove a note",
        )
    return ToolOutput(summary=f"{label} saved ({len(items)}/{limit})").to_result()


#: Keywords that touch the filesystem, attach another database, change session
#: state, or load code. None of these are plausible column names, so a plain
#: token scan is safe for them -- unlike ``set``/``create``/``replace``, which
#: are checked by statement position instead.
UNSAFE_TOKENS = frozenset({
    # attach / detach / load / export
    "attach", "detach", "copy", "export", "import", "install", "load",
    "pragma", "checkpoint", "call", "vacuum", "force",
    # Table functions that read arbitrary paths. This set is the one that
    # matters most: a DuckDB ``read_only`` connection still evaluates
    # ``sniff_csv('C:/Users/me/...')`` and ``glob('C:/**')``, so without this
    # the model could read any file the Atlas process can (spike: confirmed).
    "glob", "read_csv", "read_csv_auto", "csv_scan", "sniff_csv",
    "read_parquet", "parquet_scan", "read_json", "read_json_auto",
    "read_json_objects", "json_scan", "read_text", "read_blob",
    "iceberg_scan", "delta_scan", "sqlite_scan", "postgres_scan",
    "mysql_scan", "getenv", "shell",
})

#: What a statement is allowed to start with. Read-only SQL is exactly this.
READ_ONLY_STARTS = frozenset({"select", "with", "table", "values", "describe", "summarize"})

_WORD = re.compile(r"[A-Za-z_]+")

#: String literals and comments are removed before scanning, so prose that
#: happens to contain the word ``copy`` is not mistaken for a COPY statement.
#: Double-quoted identifiers are preserved -- that is how table names arrive.
_LITERAL = re.compile(r"'(?:[^']|'')*'|--[^\n]*|/\*.*?\*/", re.S)


def _scan_text(sql: str) -> str:
    """SQL with string literals and comments blanked out."""
    return _LITERAL.sub(lambda m: " " * len(m.group(0)), sql)


def _statement_starts(sql: str) -> list[str]:
    """First keyword of each ``;``-separated statement."""
    return [
        match.group(0).lower()
        for match in re.finditer(r"(?:^|;)\s*([A-Za-z_]+)", _scan_text(sql))
    ]


def _run_readonly(ctx: Any, sql: str, timeout_ms: int = 5000) -> tuple[list[dict], list[str]]:
    """Run SQL, refusing anything that could write or reach the filesystem.

    This guard is the read-only boundary, not a convenience layer. A DuckDB
    ``read_only`` connection blocks INSERT/UPDATE/DELETE/DROP/CREATE, but it
    still allows ``COPY ... TO`` (writes anywhere on disk) and still evaluates
    ``sniff_csv``/``glob``/``read_csv`` against any path. Both were confirmed by
    spike, so the token scan is load-bearing.

    The scan also makes refusals *teachable*: it names the offending keyword
    instead of returning a DuckDB parser error.
    """
    starts = _statement_starts(sql)
    for start in starts:
        if start not in READ_ONLY_STARTS:
            raise ToolError(
                "bad_arg",
                f"read-only SQL only; {start.upper()} is not allowed",
                sorted(READ_ONLY_STARTS),
            )

    # ``set``/``create``/``replace``/``insert`` are ordinary words in column
    # names (``created_at``, ``offset``, ``setpoint``), so only reject them
    # where they would actually begin a statement -- caught above.
    unsafe = sorted({t.lower() for t in _WORD.findall(_scan_text(sql))} & UNSAFE_TOKENS)
    if unsafe:
        raise ToolError(
            "bad_arg",
            f"read-only SQL only; {', '.join(unsafe)} is not allowed",
            sorted(READ_ONLY_STARTS),
        )

    ctx.check_cancelled()

    # A 2B model reads "Mar: table f1_mar" in an outline and then writes
    # f1_Mar, or f1_March because that is the word the user used. DuckDB's own
    # error for that is unhelpful ("Did you mean f1_apr?" -- an alphabetical
    # neighbour). So: fix the names ourselves and retry once, and only fall back
    # to the raw error if that does not resolve.
    try:
        return ctx.duck.run_readonly(sql, timeout_ms=timeout_ms, cancel=ctx.cancel)
    except TimeoutError:
        raise ToolError(
            "failed",
            f"query exceeded {timeout_ms / 1000:.0f}s and was cancelled; "
            "narrow it with a WHERE or LIMIT",
        ) from None
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        if "does not exist" not in message:
            raise
        fixed = _fix_table_names(ctx, sql, message)
        if fixed is None:
            raise ToolError("not_found", f"unknown table in SQL: {_first_missing(message)}",
                            sorted(ctx.duck.table_names())) from None
        return ctx.duck.run_readonly(fixed, timeout_ms=timeout_ms, cancel=ctx.cancel)


_MISSING = re.compile(r"Table with name (\S+) does not exist")


def _first_missing(message: str) -> str:
    match = _MISSING.search(message)
    return match.group(1).strip('"') if match else "?"


def _fix_table_names(ctx: Any, sql: str, message: str) -> str | None:
    """Rewrite table names the model got slightly wrong, or give up."""
    fixed = sql
    changed = False
    for name in {m.group(1).strip('"') for m in _MISSING.finditer(message)}:
        try:
            resolved = ctx.table_name(name)
        except ToolError:
            return None
        if resolved != name:
            fixed = re.sub(rf"\b{re.escape(name)}\b", resolved, fixed)
            changed = True
    return fixed if changed else None


__all__ = [
    "collect", "describe", "list_files", "note", "outline", "plan", "query",
    "read", "search", "show",
]
