"""Whether a turn thinks first, chosen by code (agent/runtime/thinking.py, plan 3.8)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "live"))
import harder  # noqa: E402

from agent.runtime.thinking import wants_thinking  # noqa: E402


@pytest.mark.parametrize("task", harder.TASKS, ids=lambda t: t[0])
def test_the_hard_document_tasks_think(task) -> None:
    _name, _tags, text, _grader, uploads = task
    assert wants_thinking(text, list(uploads[:1])), text


@pytest.mark.parametrize("text", [
    "whats on my resume? just the skills part",
    "who won the physics nobel last year and what was it for",
    "how many working days do i have from today till the end of december",
    "Summarise this page in a few points.",
    "is report.pdf in my folder?",
    "what does the summary in review.pdf say about the budget?",
])
def test_questions_and_single_reads_do_not(text) -> None:
    assert not wants_thinking(text, ["review.pdf"] if "review" in text else [])


@pytest.mark.parametrize("text", [
    "compare the two versions of the supplier contract and tell me what changed, make it a word doc",
    "put them all in an excel sheet with who its from, the amount and the date",
    "merge the lab reports into one pdf",
])
def test_a_document_to_make_thinks(text) -> None:
    assert wants_thinking(text)


def test_several_files_think() -> None:
    assert wants_thinking("what are these?", ["a.pdf", "b.pdf"])
