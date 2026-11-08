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

An upload field ("Upload your resume") gets no value: its candidates, found
by the same search as find_files in the allowed folders, are offered to the
model as the field's options, and the ones it picks become basket cards
(`basket.py`) the user drags onto the page. Still one model call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from agent.config import paths
from agent.config.settings import Settings
from agent.extension.basket import Basket, candidates, card, shown
from agent.model import server as llama

SYSTEM = (
    "You fill web forms from the user's details. For each field, give the value from the details that "
    "answers the field's label. Copy values exactly as written in the details, adjusted only to the "
    "field's format (a date field takes YYYY-MM-DD; a choice field takes one of its options; a "
    "checkbox field takes every option that applies, or none; an upload field lists files found on the "
    "user's computer: pick the ones that are what it asks for, judged by name and folder, or none). If the "
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
    kind = "file upload" if field.get("upload") else str(field.get("type") or "text")
    line = f'- {field["id"]}: "{field.get("label", "")}" ({kind}'
    if field.get("options"):
        line += (": any of " if kind in ("checkbox", "file upload") else ": ") + ", ".join(str(o) for o in field["options"][:40])
    if field.get("required"):
        line += ", required"
    return line + ")"


def _schema(fields: list[dict[str, Any]]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for f in fields:
        options = [str(o) for o in f.get("options") or []]
        if f.get("type") == "checkbox" and options:
            # "Select all that apply": any number of its options.
            props[f["id"]] = {"type": "array", "items": {"type": "string", "enum": options}, "uniqueItems": True}
        else:
            props[f["id"]] = {"type": "string", "enum": [*options, ""]} if options else {"type": "string", "maxLength": 300}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def suggest(settings: Settings, fields: list[dict[str, Any]], title: str = "",
            basket: Basket | None = None) -> dict[str, Any]:
    """`{"values": {field id: value}, "missing": [labels], "files": [basket cards]}`. Raises ValueError for the user."""
    profile = read_profile(settings).strip()
    fields = [f for f in fields if isinstance(f, dict) and f.get("id") and f.get("label")][:60]
    if not fields:
        raise ValueError("No fillable fields were found on this page.")
    uploads = [f for f in fields if f.get("type") == "file"]
    others = [f for f in fields if f.get("type") != "file"]
    if others and not profile and not uploads:
        raise ValueError("Add your details first: Atlas > Browser extension > Your details.")
    # Each upload field: the files that match it, offered as its options ("Resume.pdf (Documents/Career)").
    found: dict[str, dict[str, Path]] = {}
    for f in uploads:
        files = candidates(settings, str(f["label"]), str(f.get("accept") or ""))
        if files:
            found[f["id"]] = {f"{p.name} ({shown(settings, p)})": p for p in files}
    asked = ([f for f in others if profile]
             + [{**f, "type": "checkbox", "upload": True, "options": list(found[f["id"]])} for f in uploads if f["id"] in found])
    if not asked:
        return {"values": {}, "missing": [str(f["label"]) for f in fields], "files": []}
    prompt = (f"My details:\n{profile[:6000] or '(none given)'}\n\nThe form{f' on “{title}”' if title else ''} has these fields:\n"
              + "\n".join(_describe(f) for f in asked)
              + "\n\nGive the value for each field id.")
    body = {
        "model": settings.model.name,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 1500,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_schema", "json_schema": {"name": "form", "schema": _schema(asked)}},
    }
    try:
        response = httpx.post(f"http://127.0.0.1:{settings.ports.llama}/v1/chat/completions", json=body,
                              headers=llama.auth_headers(), timeout=180)
        response.raise_for_status()
        import json

        answer = json.loads(response.json()["choices"][0]["message"]["content"] or "{}")
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise ValueError(f"the model could not answer: {exc}") from exc

    values = checked(asked, answer)
    # Picked files become basket cards; an upload field is never given a typed value.
    cards: list[dict[str, Any]] = []
    basket = basket or Basket()
    for f in uploads:
        for choice in values.pop(f["id"], "").split("\n"):
            if (path := found.get(f["id"], {}).get(choice)) is not None:
                key = basket.offer(path, str(f["label"]))
                entry = basket.get(key)
                if entry:
                    cards.append(card(settings, key, entry))
    offered = {c["field"] for c in cards}
    missing = [str(f["label"]) for f in others if f["id"] not in values] + \
              [str(f["label"]) for f in uploads if str(f["label"]) not in offered]
    return {"values": values, "missing": missing, "files": cards}


def checked(fields: list[dict[str, Any]], answer: dict[str, Any]) -> dict[str, str]:
    """The answers that fit their fields: one of a choice's options; for checkboxes, the options
    that are real, one per line (the page splits them). Anything else is left out, never guessed."""
    values: dict[str, str] = {}
    for f in fields:
        raw = answer.get(f["id"])
        options = [str(o) for o in f.get("options") or []]
        if f.get("type") == "checkbox" and options:
            picked = [str(v) for v in (raw if isinstance(raw, list) else []) if str(v) in options]
            if picked:
                values[f["id"]] = "\n".join(dict.fromkeys(picked))
            continue
        value = str(raw or "").strip()
        if value and (not options or value in options):
            values[f["id"]] = value
    return values


__all__ = ["SYSTEM", "checked", "profile_path", "read_profile", "suggest", "write_profile"]
