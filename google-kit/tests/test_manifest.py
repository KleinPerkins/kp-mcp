"""Tests for google_kit.core.manifest (capability manifest accessors, §1/§2)."""

from pydantic import BaseModel

from google_kit.core.manifest import (
    Adapter,
    adapters_for,
    alias_index,
    capabilities,
    ops_by_plane,
)
from google_kit.registry import OpSpec


class _In(BaseModel):
    pass


class _Out(BaseModel):
    pass


def _fn(inp, *, service=None):  # noqa: ANN001
    return None


def _spec(name: str, **kw) -> OpSpec:
    return OpSpec(
        name=name,
        fn=_fn,
        input_model=_In,
        output_model=_Out,
        posture="read",
        scopes=[],
        **kw,
    )


class TestAdapter:
    def test_from_dict_defaults(self) -> None:
        a = Adapter.from_dict({"id": "x"})
        assert a.id == "x"
        assert a.api == "" and a.method == ""
        assert a.selector == {} and a.scopes == () and a.fallback_on == ()
        assert a.cost_hint is None

    def test_from_dict_full(self) -> None:
        a = Adapter.from_dict(
            {
                "id": "drive.export.html",
                "api": "drive.v3",
                "method": "files.export",
                "selector": {"intent": "ingest"},
                "scopes": ["s1"],
                "cost_hint": 1,
                "fallback_on": ["403_export"],
            }
        )
        assert a.api == "drive.v3" and a.method == "files.export"
        assert a.scopes == ("s1",) and a.fallback_on == ("403_export",)
        assert a.cost_hint == 1


class TestAccessors:
    def test_capabilities_groups_and_skips_none(self) -> None:
        specs = [
            _spec("doc.read1", capability="doc.read"),
            _spec("doc.read2", capability="doc.read"),
            _spec("plain.op"),
        ]
        caps = capabilities(specs)
        assert set(caps) == {"doc.read"}
        assert [s.name for s in caps["doc.read"]] == ["doc.read1", "doc.read2"]

    def test_adapters_for_preserves_order(self) -> None:
        specs = [
            _spec("doc.read1", capability="doc.read", adapters=[{"id": "a"}, {"id": "b"}]),
            _spec("doc.read2", capability="doc.read", adapters=[{"id": "c"}]),
        ]
        assert [a.id for a in adapters_for("doc.read", specs)] == ["a", "b", "c"]

    def test_ops_by_plane_sorted(self) -> None:
        specs = [
            _spec("z.op", plane="content"),
            _spec("a.op", plane="content"),
            _spec("d.op", plane="container"),
        ]
        obp = ops_by_plane(specs)
        assert obp["content"] == ["a.op", "z.op"]
        assert obp["container"] == ["d.op"]

    def test_alias_index_forms_and_first_wins(self) -> None:
        specs = [_spec("drive.fetch", aliases=["grab doc"], keywords=["download"])]
        idx = alias_index(specs)
        assert idx["drive.fetch"] == "drive.fetch"
        assert idx["drive fetch"] == "drive.fetch"
        assert idx["grab doc"] == "drive.fetch"
        assert idx["download"] == "drive.fetch"
