"""QA workstream #3 — alias / adjacent-sibling intent-resolution matrix (E6).

Each major intent cluster (drive read/write, gmail, sheets, docs, slides,
calendar, forms) supplies >=3 natural-language phrasings that MUST resolve to
the intended op as the top match — and specifically NOT to an adjacent sibling
op in the same service (e.g. "reschedule a meeting" -> calendar.update, not
calendar.create; "add a row to a sheet" -> sheets.append, not sheets.add_sheet).

The expected op for every phrase is asserted as ``matches[0].op``. This is the
behavioral counterpart to ``test_intents.py`` (which pins the operator-curated
phrases): this matrix pins the wider alias/keyword surface so future edits to
``OpSpec.aliases`` / ``OpSpec.keywords`` / ``_SERVICE_TRIGGERS`` cannot silently
regress sibling disambiguation.
"""
from __future__ import annotations

import pytest

import google_kit  # noqa: F401 — triggers service auto-registration
from google_kit.core.manifest import resolve_intent

#: phrase -> expected top op. Grouped by cluster; >=3 phrasings per intent.
INTENT_MATRIX: dict[str, str] = {
    # ── drive (read) ─────────────────────────────────────────────────────────
    "find a file": "drive.search",
    "search drive": "drive.search",
    "locate a document": "drive.search",
    "where is my file": "drive.search",
    "look for a spreadsheet in drive": "drive.search",
    "download a file": "drive.fetch",
    "get file contents": "drive.fetch",
    "read a document": "drive.fetch",
    "open a doc": "drive.fetch",
    "fetch a file from drive": "drive.fetch",
    # ── drive (write) ────────────────────────────────────────────────────────
    "make a new file": "drive.create",
    "create a document in drive": "drive.create",
    "make a blank doc in drive": "drive.create",
    "duplicate a file": "drive.copy",
    "make a copy": "drive.copy",
    "clone a document": "drive.copy",
    "delete a file": "drive.trash",
    "move to trash": "drive.trash",
    "remove a file from drive": "drive.trash",
    "share a file": "drive.permissions",
    "grant access": "drive.permissions",
    "add a collaborator": "drive.permissions",
    "share a document with a user": "drive.permissions",
    "rename a file": "drive.update",
    "change a file name": "drive.update",
    "update file metadata": "drive.update",
    # ── gmail ────────────────────────────────────────────────────────────────
    "send an email": "gmail.send",
    "compose and send mail": "gmail.send",
    "email someone": "gmail.send",
    "send a message to bob": "gmail.send",
    "draft an email": "gmail.draft",
    "save a draft": "gmail.draft",
    "compose a draft": "gmail.draft",
    "check my inbox": "gmail.list",
    "list emails": "gmail.list",
    "recent mail": "gmail.list",
    "what's in my inbox": "gmail.list",
    "find an email": "gmail.search",
    "search mail": "gmail.search",
    "look for an email from alice": "gmail.search",
    "find messages from bob": "gmail.search",
    "label an email": "gmail.modify",
    "mark as read": "gmail.modify",
    "archive a message": "gmail.modify",
    # ── sheets ───────────────────────────────────────────────────────────────
    "make a spreadsheet": "sheets.create",
    "new sheet": "sheets.create",
    "create a spreadsheet": "sheets.create",
    "read spreadsheet data": "sheets.read",
    "get cell values": "sheets.read",
    "read data from a spreadsheet": "sheets.read",
    "update cells": "sheets.write",
    "write to a sheet": "sheets.write",
    "set cell values": "sheets.write",
    "put data in a sheet": "sheets.write",
    "append a row": "sheets.append",
    "add a row to a sheet": "sheets.append",
    "append data to a spreadsheet": "sheets.append",
    # ── docs ─────────────────────────────────────────────────────────────────
    "create a doc from markdown": "docs.from_markdown",
    "publish markdown as a google doc": "docs.from_markdown",
    "turn markdown into a google doc": "docs.from_markdown",
    "edit a doc": "docs.batch_update",
    "modify a google doc": "docs.batch_update",
    "apply changes to a document": "docs.batch_update",
    # ── slides ───────────────────────────────────────────────────────────────
    "make a presentation": "slides.create",
    "new slide deck": "slides.create",
    "create a presentation": "slides.create",
    "make a slide deck": "slides.create",
    "add a slide": "slides.add_slide",
    "add a new slide to a deck": "slides.add_slide",
    "insert a slide": "slides.add_slide",
    "add an image to a slide": "slides.add_image",
    "insert a picture into a slide": "slides.add_image",
    "put an image on a slide": "slides.add_image",
    # ── calendar ─────────────────────────────────────────────────────────────
    "schedule a meeting": "calendar.create",
    "create an event": "calendar.create",
    "book time": "calendar.create",
    "what's on my calendar": "calendar.list",
    "list events": "calendar.list",
    "my schedule": "calendar.list",
    "show my calendar": "calendar.list",
    "check availability": "calendar.freebusy",
    "when am i free": "calendar.freebusy",
    "find free time": "calendar.freebusy",
    "update an event": "calendar.update",
    "reschedule a meeting": "calendar.update",
    "change an event time": "calendar.update",
    "delete an event": "calendar.delete",
    "cancel a meeting": "calendar.delete",
    "remove an event": "calendar.delete",
    # ── forms ────────────────────────────────────────────────────────────────
    "create a form": "forms.create",
    "make a survey": "forms.create",
    "create a new survey": "forms.create",
    "add a question to a form": "forms.add_item",
    "add an item to a survey": "forms.add_item",
    "add a question": "forms.add_item",
    "list form responses": "forms.list_responses",
    "get survey responses": "forms.list_responses",
    "see all responses to a form": "forms.list_responses",
}


@pytest.mark.parametrize("phrase,expected_op", sorted(INTENT_MATRIX.items()))
def test_phrase_resolves_to_expected_op(phrase: str, expected_op: str) -> None:
    matches = resolve_intent(phrase, limit=5)
    assert matches, f"no match for {phrase!r}"
    top = matches[0].op
    assert top == expected_op, (
        f"{phrase!r} -> {top} (expected {expected_op}); top5="
        f"{[(m.op, m.score) for m in matches]}"
    )


def test_every_cluster_has_at_least_three_phrasings() -> None:
    """Each expected op in the matrix must be exercised by >=3 phrasings."""
    from collections import Counter

    counts = Counter(INTENT_MATRIX.values())
    thin = {op: n for op, n in counts.items() if n < 3}
    assert thin == {}, f"intents with <3 phrasings: {thin}"


def test_matrix_resolution_is_deterministic() -> None:
    for phrase in INTENT_MATRIX:
        a = resolve_intent(phrase, limit=5)
        b = resolve_intent(phrase, limit=5)
        assert [(m.op, m.score, m.matched) for m in a] == [
            (m.op, m.score, m.matched) for m in b
        ]
