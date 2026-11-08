"""Fill suggestions (agent/extension/form_fill.py): answers must fit their fields."""

from __future__ import annotations

from agent.extension.form_fill import _schema, checked

FIELDS = [
    {"id": "f1", "label": "Full name", "type": "text"},
    {"id": "f2", "label": "Branch", "type": "radio", "options": ["CSE", "IT", "EXTC"]},
    {"id": "f3", "label": "Workshops attended", "type": "checkbox", "options": ["AI", "IoT", "Cloud"]},
]


def test_a_checkbox_question_takes_any_of_its_options() -> None:
    schema = _schema(FIELDS)["properties"]
    assert schema["f3"] == {"type": "array", "items": {"type": "string", "enum": ["AI", "IoT", "Cloud"]}, "uniqueItems": True}
    assert schema["f2"]["enum"] == ["CSE", "IT", "EXTC", ""]


def test_only_answers_that_fit_are_kept() -> None:
    answer = {"f1": "Pranav", "f2": "Mechanical", "f3": ["AI", "Blockchain", "Cloud", "AI"]}
    assert checked(FIELDS, answer) == {"f1": "Pranav", "f3": "AI\nCloud"}   # no made-up branch, no unknown workshop
