"""Secrets in an MCP server's config, kept out of everything the UI receives.

`mcp.json` can hold API keys: in `env`, in `headers`, as `--api-key VALUE` or
`--token=VALUE` in `args`, or as a query parameter in a remote server's `url`.
`redact` replaces each with a placeholder before a config leaves the backend;
`restore` puts the stored value back where an edit left the placeholder, so
editing a server's port in the UI does not wipe its key.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "••••••"

#: An argument or query parameter whose name says it holds a secret.
_SECRET_NAME = re.compile(r"(api[-_]?key|token|secret|password|passwd|auth|credential|bearer)", re.I)
_FLAG = re.compile(r"^(--?[\w-]+)=(.*)$")


def redact(config: dict[str, Any]) -> dict[str, Any]:
    """A copy of `config` with every secret replaced by `REDACTED`."""
    out = dict(config)
    for key in ("env", "headers"):
        if isinstance(config.get(key), dict):
            out[key] = {k: REDACTED for k in config[key]}
    if isinstance(config.get("args"), list):
        out["args"] = _redact_args(config["args"])
    if isinstance(config.get("url"), str):
        out["url"] = _redact_url(config["url"])
    return out


def restore(edited: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    """`edited` with each placeholder replaced by the stored value it stands for.

    A placeholder where nothing was stored (a new key typed as `••••••`) is an
    error: saving it would write the placeholder itself as the secret.
    """
    out = dict(edited)
    for key in ("env", "headers"):
        if isinstance(edited.get(key), dict):
            kept_value = stored.get(key)
            kept: dict[str, Any] = kept_value if isinstance(kept_value, dict) else {}
            out[key] = {k: (kept[k] if v == REDACTED and k in kept else v) for k, v in edited[key].items()}
    if isinstance(edited.get("args"), list):
        old_value = stored.get("args")
        old: list[Any] = old_value if isinstance(old_value, list) else []
        shown = _redact_args(old)
        out["args"] = [old[i] if i < len(old) and a == shown[i] and REDACTED in str(a) else a
                       for i, a in enumerate(edited["args"])]
    if isinstance(edited.get("url"), str) and isinstance(stored.get("url"), str) \
            and edited["url"] == _redact_url(stored["url"]):
        out["url"] = stored["url"]
    if REDACTED in repr(out):
        raise ValueError(f"a value is still {REDACTED}: type the secret itself, or leave the stored one unchanged")
    return out


def _redact_args(args: list[Any]) -> list[Any]:
    out, hide_next = [], False
    for arg in args:
        text = str(arg)
        if hide_next and not text.startswith("-"):
            out.append(REDACTED)
            hide_next = False
            continue
        hide_next = False
        if (m := _FLAG.match(text)) and _SECRET_NAME.search(m.group(1)):
            out.append(f"{m.group(1)}={REDACTED}")
        else:
            out.append(arg)
            hide_next = text.startswith("-") and bool(_SECRET_NAME.search(text))
    return out


def _redact_url(url: str) -> str:
    parts = urlsplit(url)
    if not parts.query:
        return url
    query = [(k, REDACTED if _SECRET_NAME.search(k) else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    return urlunsplit(parts._replace(query=urlencode(query, safe=REDACTED)))
