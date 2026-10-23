"""Fill suggestions: values for a web form, from the user's own details.

The browser extension sends the form's fields (labels, types, options, never
their current contents); this asks the model once to map the user's details
onto them, and returns a value per field. The extension shows them on the
page and fills only what the user applies. Nothing is ever submitted.

The model's job is small on purpose: matching "Roll number" to the line
"Roll no: 21CS045". The answer is constrained by a JSON schema built from
the form itself, so it can only name fields that exist and, for a select,
only one of its options. A field the details do not cover comes back empty
rather than guessed.

The details are a plain text file, `<data>/profile.md`, edited in Settings >
Browser extension. They stay in the backend: the extension never reads them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from agent.core import llama, paths
from agent.core.settings import Settings

SYSTEM = (
    "You fill web forms from the user's details. For each field, give the value from the details that "
    "answers the field's label. Copy values exactly as written in the details, adjusted only to the "
    "field's format (a date field takes YYYY-MM-DD; a choice field takes one of its options). If the "
    'details do not say, give "". Never invent a value.'
)


def profile_path(settings: Settings) -> Path:
    return paths.data_dir(settings) / "profile.md"


def read_profile(settings: Settings) -> str:
    try:
        return profile_path(settings).read_text(encoding="utf-8")
    except OSError:
        return ""


def write_profile(settings: Settings, text: str) -> None:
    path = profile_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _describe(field: dict[str, Any]) -> str:
    kind = str(field.get("type") or "text")
    line = f'- {field["id"]}: "{field.get("label", "")}" ({kind}'
    if field.get("options"):
        line += ": " + ", ".join(str(o) for o in field["options"][:40])
    if field.get("required"):
        line += ", required"
    return line + ")"


def _schema(fields: list[dict[str, Any]]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for f in fields:
        options = [str(o) for o in f.get("options") or []]
        props[f["id"]] = {"type": "string", "enum": [*options, ""]} if options else {"type": "string", "maxLength": 300}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def suggest(settings: Settings, fields: list[dict[str, Any]], title: str = "") -> dict[str, Any]:
    """`{"values": {field id: value}, "missing": [labels]}`. Raises ValueError for the user."""
    profile = read_profile(settings).strip()
    if not profile:
        raise ValueError("Add your details first: Atlas > Browser extension > Your details.")
    fields = [f for f in fields if isinstance(f, dict) and f.get("id") and f.get("label")][:60]
    if not fields:
        raise ValueError("No fillable fields were found on this page.")
    prompt = (f"My details:\n{profile[:6000]}\n\nThe form{f' on “{title}”' if title else ''} has these fields:\n"
              + "\n".join(_describe(f) for f in fields)
              + "\n\nGive the value for each field id.")
    body = {
        "model": settings.model.name,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 1500,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_schema", "json_schema": {"name": "form", "schema": _schema(fields)}},
    }
    try:
        response = httpx.post(f"http://127.0.0.1:{settings.ports.llama}/v1/chat/completions", json=body,
                              headers=llama.auth_headers(), timeout=180)
        response.raise_for_status()
        import json

        answer = json.loads(response.json()["choices"][0]["message"]["content"] or "{}")
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise ValueError(f"the model could not answer: {exc}") from exc

    values: dict[str, str] = {}
    for f in fields:
        value = str(answer.get(f["id"], "") or "").strip()
        options = [str(o) for o in f.get("options") or []]
        if value and (not options or value in options):
            values[f["id"]] = value
    missing = [str(f["label"]) for f in fields if f["id"] not in values]
    return {"values": values, "missing": missing}


__all__ = ["profile_path", "read_profile", "suggest", "write_profile"]
