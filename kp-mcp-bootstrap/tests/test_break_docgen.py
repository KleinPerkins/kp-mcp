"""Adversarial tests for Docgen robustness + determinism.

Seeded bugs:
  - emit_mcp_schema crashes (IndexError) when the op function has no docstring.
  - emit_markdown crashes (ValueError unpack) for a non-dotted op name with examples.
"""

from typing import Any, Callable

from pydantic import BaseModel

from kp_mcp_bootstrap.docgen import Docgen, mcp_tool_name


class _In(BaseModel):
    query: str
    limit: int = 10


class _Out(BaseModel):
    ok: bool


class FakeSpec:
    def __init__(self, name: str, fn: Callable[..., Any], examples: list | None = None) -> None:
        self.name = name
        self.posture = "read"
        self.scopes = ["scope.a", "scope.b"]
        self.perf = {"latency": "low"}
        self.batching = {}
        self.formatting = {}
        self.examples = examples or []
        self.fn = fn
        self.input_model = _In
        self.output_model = _Out


def _no_doc_fn():
    pass


def _whitespace_doc_fn():
    """   """
    pass


def _doc_fn():
    """First line summary.

    More detail.
    """
    pass


class TestEmptyDocstring:
    def test_mcp_schema_no_docstring_does_not_crash(self) -> None:
        schema = Docgen().emit_mcp_schema(FakeSpec("svc.op", _no_doc_fn))
        assert schema["description"] == ""
        assert schema["name"] == "svc_op"

    def test_mcp_schema_whitespace_docstring(self) -> None:
        schema = Docgen().emit_mcp_schema(FakeSpec("svc.op", _whitespace_doc_fn))
        assert schema["description"] == ""

    def test_emit_card_no_docstring_does_not_crash(self) -> None:
        card = Docgen().emit_card(FakeSpec("svc.op", _no_doc_fn))
        assert card.mcp_schema["description"] == ""

    def test_mcp_schema_uses_first_doc_line(self) -> None:
        schema = Docgen().emit_mcp_schema(FakeSpec("svc.op", _doc_fn))
        assert schema["description"] == "First line summary."


class TestNonDottedName:
    def test_markdown_non_dotted_name_with_examples(self) -> None:
        spec = FakeSpec("ping", _doc_fn, examples=[{"cli": "google-kit ping", "input": {"x": 1}}])
        md = Docgen().emit_markdown(spec)  # must not raise ValueError
        assert "# ping" in md
        assert "## Example" in md


class TestDeterminism:
    def test_emit_markdown_is_deterministic(self) -> None:
        spec = FakeSpec("svc.op", _doc_fn, examples=[{"cli": "x", "input": {"a": 1}}])
        d = Docgen()
        assert d.emit_markdown(spec) == d.emit_markdown(spec)

    def test_tool_name_sanitization(self) -> None:
        assert mcp_tool_name("gmail.manage_labels") == "gmail_manage_labels"

    def test_markdown_accepts_kit_specific_error_contract(self) -> None:
        spec = FakeSpec("svc.op", _doc_fn)
        spec.errors = [
            {
                "class": "Unavailable",
                "when": "Pinned local source cannot be read",
                "retry": "Repair source; never interpret as empty",
            }
        ]

        markdown = Docgen().emit_markdown(spec)

        assert "| `Unavailable` |" in markdown
        assert "never interpret as empty" in markdown
        assert "QuotaRateLimit" not in markdown

    def test_default_error_contract_preserves_legacy_generated_markdown(self) -> None:
        markdown = Docgen().emit_markdown(FakeSpec("svc.op", _doc_fn))

        assert "| Class | When |" in markdown
        assert "| Class | When | Retry |" not in markdown
        assert "| `QuotaRateLimit` | Quota exceeded; retried automatically |" in markdown
