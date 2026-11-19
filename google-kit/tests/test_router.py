"""Tests for google_kit.core.router (deterministic capability resolver, §2)."""

from pydantic import BaseModel

from google_kit.core.router import resolve, selector_matches
from google_kit.registry import OpSpec


class _In(BaseModel):
    pass


class _Out(BaseModel):
    pass


def _fn(inp, *, service=None):  # noqa: ANN001
    return None


def _cap_spec(capability: str, adapters: list[dict]) -> OpSpec:
    return OpSpec(
        name=capability,
        fn=_fn,
        input_model=_In,
        output_model=_Out,
        posture="read",
        scopes=[],
        capability=capability,
        adapters=adapters,
    )


class TestSelectorMatches:
    def test_empty_and_any_always_match(self) -> None:
        assert selector_matches({}, {"intent": "x"})
        assert selector_matches({"any": True}, {})

    def test_and_semantics(self) -> None:
        sel = {"intent": "ingest", "will_edit": False}
        assert selector_matches(sel, {"intent": "ingest", "will_edit": False})
        assert not selector_matches(sel, {"intent": "ingest", "will_edit": True})
        assert not selector_matches(sel, {"intent": "ingest"})

    def test_any_of_or_semantics(self) -> None:
        sel = {"any_of": [{"needs_indices": True}, {"will_edit": True}]}
        assert selector_matches(sel, {"will_edit": True})
        assert selector_matches(sel, {"needs_indices": True})
        assert not selector_matches(sel, {"will_edit": False, "needs_indices": False})


class TestResolve:
    def test_single_adapter(self) -> None:
        specs = [_cap_spec("doc.read", [{"id": "only", "selector": {}}])]
        plan = resolve("doc.read", {}, specs=specs)
        assert plan.kind == "single"
        assert plan.chosen is not None and plan.chosen.id == "only"
        assert plan.fallback_chain == ()

    def test_fallback_chain_preserves_order(self) -> None:
        specs = [
            _cap_spec(
                "doc.read",
                [
                    {"id": "primary", "selector": {"intent": "ingest"}},
                    {"id": "secondary", "selector": {}},
                ],
            )
        ]
        plan = resolve("doc.read", {"intent": "ingest"}, specs=specs)
        assert plan.kind == "fallback"
        assert plan.chosen is not None and plan.chosen.id == "primary"
        assert [a.id for a in plan.fallback_chain] == ["secondary"]

    def test_scope_gating_filters_ineligible_adapters(self) -> None:
        specs = [
            _cap_spec(
                "doc.read",
                [
                    {"id": "needs_drive", "selector": {}, "scopes": ["drive"]},
                    {"id": "needs_readonly", "selector": {}, "scopes": ["drive.readonly"]},
                ],
            )
        ]
        plan = resolve("doc.read", {}, granted_scopes=["drive.readonly"], specs=specs)
        assert plan.chosen is not None and plan.chosen.id == "needs_readonly"
        assert plan.fallback_chain == ()

    def test_none_when_nothing_matches(self) -> None:
        specs = [_cap_spec("doc.read", [{"id": "x", "selector": {"intent": "edit"}}])]
        plan = resolve("doc.read", {"intent": "ingest"}, specs=specs)
        assert plan.kind == "none"
        assert plan.chosen is None

    def test_recipe_kind(self) -> None:
        specs = [_cap_spec("doc.create", [{"id": "step1", "selector": {}}])]
        plan = resolve("doc.create", {}, recipe_id="hydrate-then-refine", specs=specs)
        assert plan.kind == "recipe"
        assert plan.recipe_id == "hydrate-then-refine"
        assert plan.chosen is not None and plan.chosen.id == "step1"
