"""Tests for google_kit.core.scopes (least-privilege per-mode manifest, §8)."""

import pytest

from google_kit.core.scopes import DEFAULT_MODE, SCOPE_MODES, all_modes, scopes_for_modes


def test_default_mode_is_read_ingest() -> None:
    assert DEFAULT_MODE == "read_ingest"
    assert DEFAULT_MODE in SCOPE_MODES


def test_all_modes() -> None:
    assert set(all_modes()) == {
        "read_ingest",
        "create_edit",
        "broad_authoring",
        "gmail_write",
        "events",
        "advanced",
    }


def test_scopes_for_modes_union_dedup_sorted() -> None:
    out = scopes_for_modes(["read_ingest", "create_edit"])
    assert out == sorted(out)
    assert len(out) == len(set(out))
    assert "https://www.googleapis.com/auth/drive.file" in out
    assert "https://www.googleapis.com/auth/drive.readonly" in out


def test_gmail_write_scopes() -> None:
    out = scopes_for_modes(["gmail_write"])
    assert out == [
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.modify",
    ]


def test_unknown_mode_raises() -> None:
    with pytest.raises(KeyError, match="Unknown scope mode"):
        scopes_for_modes(["nope"])


def test_read_ingest_includes_calendar_tasks_readonly() -> None:
    # gate (c): read mode kept consistent with the tightened calendar/tasks reads.
    union = set(scopes_for_modes(["read_ingest"]))
    assert "https://www.googleapis.com/auth/calendar.readonly" in union
    assert "https://www.googleapis.com/auth/tasks.readonly" in union


# Gate (c) least-privilege tightening (2026-06-17): pure-read ops declare the
# .readonly scope variant. drive.* (thick-read cascade) and events.list (no
# readonly variant) are intentionally excluded. script.metrics is excluded too —
# projects.getMetrics authorizes ONLY via the dedicated script.metrics scope
# (it has no .readonly variant); guarded by test_script_metrics_declares_metrics_scope.
_GATE_C_READONLY = {
    "sheets.read": "https://www.googleapis.com/auth/spreadsheets.readonly",
    "sheets.info": "https://www.googleapis.com/auth/spreadsheets.readonly",
    "slides.get": "https://www.googleapis.com/auth/presentations.readonly",
    "slides.thumbnail": "https://www.googleapis.com/auth/presentations.readonly",
    "forms.get": "https://www.googleapis.com/auth/forms.body.readonly",
    "tasks.list": "https://www.googleapis.com/auth/tasks.readonly",
    "tasks.list_lists": "https://www.googleapis.com/auth/tasks.readonly",
    "keep.get": "https://www.googleapis.com/auth/keep.readonly",
    "keep.list": "https://www.googleapis.com/auth/keep.readonly",
    "calendar.list": "https://www.googleapis.com/auth/calendar.readonly",
    "calendar.freebusy": "https://www.googleapis.com/auth/calendar.readonly",
    "script.get_content": "https://www.googleapis.com/auth/script.projects.readonly",
    "script.versions": "https://www.googleapis.com/auth/script.projects.readonly",
    "script.deployments": "https://www.googleapis.com/auth/script.deployments.readonly",
}


@pytest.mark.parametrize(("op_name", "readonly_scope"), sorted(_GATE_C_READONLY.items()))
def test_gate_c_read_ops_declare_readonly_scope(op_name: str, readonly_scope: str) -> None:
    from google_kit.registry import get

    spec = get(op_name)
    assert spec.posture == "read", f"{op_name} should be a read op"
    assert readonly_scope in spec.scopes, f"{op_name} missing {readonly_scope}"
    # No read-write variant should linger on a tightened read op.
    rw = readonly_scope.replace(".readonly", "")
    assert rw not in spec.scopes, f"{op_name} still carries read-write {rw}"


def test_script_metrics_declares_metrics_scope() -> None:
    # projects.getMetrics authorizes ONLY via the dedicated script.metrics scope —
    # script.projects[.readonly] do NOT cover it (live 403
    # ACCESS_TOKEN_SCOPE_INSUFFICIENT). Regression guard for that scope-mapping fix.
    from google_kit.registry import get

    spec = get("script.metrics")
    assert spec.posture == "read"
    assert spec.scopes == ["https://www.googleapis.com/auth/script.metrics"]
    assert "https://www.googleapis.com/auth/script.projects.readonly" not in spec.scopes


def test_gate_c_consent_union_unchanged_no_reconsent() -> None:
    # The single-consent grant keeps the read-write scopes (write ops need them;
    # rw subsumes .readonly), so per-op read tightening requires NO re-consent.
    from google_kit.core.auth import GOOGLE_KIT_SCOPES

    grant = set(GOOGLE_KIT_SCOPES)
    assert len(GOOGLE_KIT_SCOPES) == 10
    for rw in (
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/presentations",
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/tasks",
        "https://www.googleapis.com/auth/forms.body",
    ):
        assert rw in grant, f"{rw} must stay in the consent union (write ops need it)"
    # The grant was NOT expanded with redundant .readonly variants.
    assert "https://www.googleapis.com/auth/spreadsheets.readonly" not in grant
    assert "https://www.googleapis.com/auth/calendar.readonly" not in grant
