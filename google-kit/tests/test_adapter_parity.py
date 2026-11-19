"""MCP↔CLI adapter parity for the service-injection seam (E4 review sweep).

Guarantees, for EVERY registered op, that:
  1. the CLI and MCP adapters inject the same set of service parameters, and
  2. those injected kwargs are accepted by the core fn signature — so no op can
     TypeError on invocation. This closes the pre-E4 gap where multi-service ops
     (docs.from_markdown takes drive_service + docs_service, no plain `service`)
     were unreachable through the generic `spec.fn(inp, service=...)` path.

Plus a functional check that docs.from_markdown is now reachable end-to-end
through the generic CLI path.
"""
from __future__ import annotations

import inspect
import json
from typing import Any

import pytest

import google_kit  # noqa: F401 — triggers registration
from google_kit.cli import _service_kwargs as cli_service_kwargs
from google_kit.mcp import _service_kwargs as mcp_service_kwargs
from google_kit.registry import all_specs

_ALL_SPECS = sorted(all_specs(), key=lambda s: s.name)


def _fake_factory(op_name: str, *, profile: str | None = None) -> str:
    return f"svc::{op_name}"


@pytest.mark.parametrize("spec", _ALL_SPECS, ids=lambda s: s.name)
class TestServiceInjectionParity:
    def test_cli_and_mcp_inject_same_service_params(self, spec: Any) -> None:
        cli = cli_service_kwargs(spec, _fake_factory, spec.name, None)
        mcp = mcp_service_kwargs(spec, _fake_factory)
        assert set(cli) == set(mcp), f"{spec.name}: CLI/MCP service-param mismatch"

    def test_injected_kwargs_accepted_by_core_fn(self, spec: Any) -> None:
        kwargs = cli_service_kwargs(spec, _fake_factory, spec.name, None)
        # binding inp positionally + the injected service kwargs must not raise
        inspect.signature(spec.fn).bind_partial(object(), **kwargs)

    def test_all_service_params_are_injected(self, spec: Any) -> None:
        if spec.name.startswith("recipes."):
            # recipe service= is a resolver, not the fn's literal params
            assert set(cli_service_kwargs(spec, _fake_factory, spec.name, None)) == {"service"}
            return
        sig = inspect.signature(spec.fn)
        expected = {n for n in sig.parameters if n == "service" or n.endswith("_service")}
        injected = set(cli_service_kwargs(spec, _fake_factory, spec.name, None))
        assert expected == injected, f"{spec.name}: missing/extra {expected ^ injected}"


# ─── functional: multi-service op reachable via the generic CLI path ──────────


class _Exec:
    def __init__(self, resp: Any) -> None:
        self._resp = resp

    def execute(self) -> Any:
        return self._resp


class _DriveFiles:
    def __init__(self, log: list) -> None:
        self._log = log

    def create(self, **kwargs: Any) -> _Exec:
        self._log.append(("files", "create", kwargs))
        return _Exec({"id": "doc001", "webViewLink": "https://docs.google.com/document/d/doc001/edit"})


class _DriveMock:
    def __init__(self) -> None:
        self.log: list = []

    def files(self) -> _DriveFiles:
        return _DriveFiles(self.log)


class _Documents:
    def __init__(self, log: list) -> None:
        self._log = log

    def get(self, **kwargs: Any) -> _Exec:
        self._log.append(("documents", "get", kwargs))
        return _Exec({"body": {"content": []}})

    def batchUpdate(self, **kwargs: Any) -> _Exec:
        self._log.append(("documents", "batchUpdate", kwargs))
        return _Exec({"replies": []})


class _DocsMock:
    def __init__(self) -> None:
        self.log: list = []

    def documents(self) -> _Documents:
        return _Documents(self.log)


class TestMultiServiceReachability:
    def test_docs_from_markdown_reachable_via_cli(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from google_kit.cli import main

        monkeypatch.setenv("GOOGLE_KIT_ENABLE_WRITES", "1")
        drive, docs = _DriveMock(), _DocsMock()

        def _factory(op_name: str, *, profile: str | None = None) -> Any:
            return {"drive": drive, "docs": docs}[op_name.split(".")[0]]

        main(
            ["docs", "from-markdown", "--markdown-content", "# Hello\n\nWorld.", "--title", "My Doc"],
            _service_factory=_factory,
        )
        out = json.loads(capsys.readouterr().out)
        assert out["data"]["doc_id"] == "doc001"
        assert out["data"]["title"] == "My Doc"
        # both APIs were exercised: drive files.create + docs documents.batchUpdate
        assert any(r[1] == "create" for r in drive.log)
        assert any(r[1] == "batchUpdate" for r in docs.log)

    def test_docs_from_markdown_was_unreachable_via_single_service(self) -> None:
        # Regression guard: docs_from_markdown has NO plain `service` param, so the
        # old `spec.fn(inp, service=...)` path would have raised TypeError. The new
        # signature-driven injection passes drive_service + docs_service instead.
        from google_kit.registry import get
        from google_kit.services.docs.models import DocsFromMarkdownInput

        spec = get("docs.from_markdown")
        params = inspect.signature(spec.fn).parameters
        assert "service" not in params
        assert {"drive_service", "docs_service"} <= set(params)
        with pytest.raises(TypeError):
            spec.fn(DocsFromMarkdownInput(markdown_content="x", title="y"), service=object())
