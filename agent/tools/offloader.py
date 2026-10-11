"""ResultOffloader (spec section 10, "pruning by construction").

The model works on the control plane -- short commands, schemas, previews and
notes. Bulk data stays in the data plane, where deterministic code operates on
it. This is the boundary.

    <= passthrough_tokens (~400)   passes through unchanged
    larger                        stored as an object; the model gets a compact
                                  reply with the preview, shape, id and the
                                  next action
    > max_inline_tokens (~1.5k)   hard-capped even if it would have been shown

Two properties make this safe rather than merely tidy:

* **Saving is unconditional, display is conditional.** A query result is stored
  whether or not it fits, so the model never has to decide to save.
* **Objects are immutable.** Re-reading one returns the same bytes, so a retry
  or a later turn cannot drift from what the model already saw.

Spike S14's question -- does Strands' own context-offloading overlap this? --
does not affect the design: even if upstream adds something, this boundary is
where Atlas decides what leaves the data plane, and the tool contract is built
on top of it.
"""

from __future__ import annotations

import json
from typing import Any

from agent.ingest.contract import estimate_tokens
from agent.tools.catalog import Catalog
from agent.tools.context import ToolContext
from agent.tools.contract import ToolError, ToolOutput

DEFAULT_PASSTHROUGH = 400
DEFAULT_MAX_INLINE = 1500
DEFAULT_DISPLAY_BUDGET = 400


class ResultOffloader:
    """Applies the display rules to a tool result before the model sees it."""

    def __init__(
        self,
        catalog: Catalog,
        *,
        passthrough_tokens: int = DEFAULT_PASSTHROUGH,
        max_inline_tokens: int = DEFAULT_MAX_INLINE,
        display_budget_tokens: int = DEFAULT_DISPLAY_BUDGET,
    ) -> None:
        self.catalog = catalog
        self.passthrough = passthrough_tokens
        self.max_inline = max_inline_tokens
        self.display_budget = display_budget_tokens

    @classmethod
    def from_settings(cls, catalog: Catalog, settings: dict[str, Any]) -> "ResultOffloader":
        limits = (settings or {}).get("results", {}) or {}
        return cls(
            catalog,
            passthrough_tokens=int(limits.get("passthrough_tokens", DEFAULT_PASSTHROUGH)),
            max_inline_tokens=int(limits.get("max_inline_tokens", DEFAULT_MAX_INLINE)),
            display_budget_tokens=int(
                limits.get("display_budget_tokens", DEFAULT_DISPLAY_BUDGET)
            ),
        )

    # ------------------------------------------------------------------ api --

    def render(
        self,
        ctx: ToolContext,
        output: ToolOutput,
        *,
        body: str | None = None,
        kind: str = "text",
        store: str = "sqlite",
        shape: str | None = None,
        name: str | None = None,
        # Set when the summary already carries the answer and must survive even
        # though the body is large -- an aggregate's single value, say.
        keep_summary: str | None = None,
    ) -> dict[str, Any]:
        """Decide what the model sees for a tool's result.

        ``body`` is the full text. It is always stored. The model only receives
        it when it is small enough to be worth the context.
        """
        text = body if body is not None else output.summary
        tokens = estimate_tokens(text)

        if tokens <= self.passthrough:
            return output.to_result()

        obj = self.catalog.add(
            chat_id=ctx.chat_id,
            name=name or _auto_name(ctx),
            kind=kind,
            store=store,
            run_id=ctx.run.id,
            node_id=ctx.node_id,
            schema=output.data if kind == "table" else None,
            row_count=output.data.get("rows") if isinstance(output.data, dict) else None,
            tokens=tokens,
            provenance={"tool": output.summary},
        )

        # Always persist the body. ``store`` records where the data *came from*
        # (duckdb vs the filesystem), not where the offloaded copy lives: a
        # query result is derived from DuckDB but is only recoverable through
        # ``show`` if the bytes were written down. Skipping this for
        # ``store="duckdb"`` produced objects that existed in the catalog and
        # had no body at all.
        self.catalog.put_text(obj.id, text)
        output.objects.append(obj.id)

        shown = text
        truncated = False
        if tokens > self.max_inline:
            shown = _clip(text, self.max_inline)
            truncated = True

        lines = [
            f"[{obj.id}] {tokens} tokens{(' - ' + shape) if shape else ''}."
            f" Preview:\n{shown}"
        ]
        if truncated:
            lines.append(
                f"(clipped to ~{self.max_inline} tokens; the rest is in {obj.id})"
            )
        lines.append(
            f"Full result stored as {obj.id}. Use show({obj.id}) to page through it"
            " or query() on it."
        )

        summary = output.summary
        if tokens > self.display_budget and not keep_summary:
            summary = f"{summary} (full result in {obj.id})"
        return ToolOutput(
            summary=f"{summary}\n" + "\n".join(lines),
            objects=[obj.id],
            warnings=output.warnings,
        ).to_result()

    def store_only(
        self, ctx: ToolContext, text: str, *, kind: str = "text",
        store: str = "sqlite", name: str | None = None, shape: str | None = None,
    ) -> str:
        """Store text and return its id, without showing anything."""
        obj = self.catalog.add(
            chat_id=ctx.chat_id, name=name or _auto_name(ctx), kind=kind,
            store=store, run_id=ctx.run.id, node_id=ctx.node_id,
            tokens=estimate_tokens(text),
            provenance={"stored": True},
        )
        self.catalog.put_text(obj.id, text)
        return obj.id


def _clip(text: str, max_tokens: int) -> str:
    """Cut on a line boundary where possible, so snippets stay readable."""
    budget = max_tokens * 4
    if len(text) <= budget:
        return text
    head = text[:budget]
    cut = head.rfind("\n")
    if cut > budget * 0.6:
        head = head[:cut]
    return head.rstrip() + "\n..."


def _auto_name(ctx: ToolContext) -> str:
    """``r1``, ``r2`` ... per run, matching the spec's naming."""
    row = ctx.repo.db.connection.execute(
        "SELECT COUNT(*) AS n FROM catalog_objects WHERE run_id=?", (ctx.run.id,)
    ).fetchone()
    return f"r{int(row['n']) + 1}"


def tsv(
    rows: list[dict[str, Any]],
    columns: list[str] | None = None,
    limit: int = 50,
    *,
    clean: bool = False,
) -> str:
    """Compact TSV for display (section 11.1: compact formats).

    ``clean`` rounds floats for display. Sums of decimals come back from DuckDB
    as ``425184.6699999999``, and the model repeats whatever it is given
    verbatim -- float noise in the table becomes float noise in the answer. The
    stored body is produced with ``clean=False`` so precision is preserved for
    anything that reads it back.
    """
    if not rows:
        return "(no rows)"
    columns = columns or list(rows[0].keys())

    def cell(value: Any) -> str:
        if value is None:
            return ""
        if clean and isinstance(value, float):
            value = _tidy_float(value)
        return str(value)

    lines = ["\t".join(columns)]
    for row in rows[:limit]:
        lines.append("\t".join(cell(row.get(c)) for c in columns))
    if len(rows) > limit:
        lines.append(f"... {len(rows) - limit} more rows")
    return "\n".join(lines)


#: Decimal places kept when displaying a float. Two is what money and totals
#: are quoted in, and it is enough to erase the representation noise that makes
#: ``425184.6699999999`` out of a column of two-decimal values.
#:
#: The earlier version rounded to 6 *significant* digits, which turned
#: 425184.67 into 425185. Significant digits are the wrong unit here: a
#: spreadsheet's precision is a count of decimal places, not of leading
#: figures.
FLOAT_DISPLAY_PLACES = 2


def _tidy_float(value: float) -> float | int:
    """``425184.6699999999`` -> ``425184.67``.

    Money and totals are why this exists: the model repeats whatever figure it
    is shown, so a spurious 15th decimal is a spurious decimal in the answer.
    Applied only to what the model sees -- stored bodies keep full precision, so
    nothing is lost.
    """
    if value != value or value in (float("inf"), float("-inf")):
        return value
    rounded = round(value, FLOAT_DISPLAY_PLACES)
    # A value that was integral stays an int, so a count does not read as 1248.0.
    if abs(rounded - round(rounded)) < 1e-9:
        return int(round(rounded))
    return rounded


def json_preview(value: Any, limit: int = 2000) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return text if len(text) <= limit else text[:limit] + "\n..."


__all__ = ["DEFAULT_MAX_INLINE", "DEFAULT_PASSTHROUGH", "ResultOffloader", "json_preview", "tsv"]
