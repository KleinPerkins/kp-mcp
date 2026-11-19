"""Tests for the first-class composition recipes (architecture brief §4).

These exercise the recipe layer specifically — the composition (right ops in the
right order with ids threaded through), the saga (LIFO compensation on a
mid-recipe failure), the surfaced partial outcome, and the multi-API service
resolver seam. The request bodies of the composed 1:1 ops are already parity-
tested in test_docs.py / test_drive.py; here we assert the recipe-specific glue.

Coverage per recipe:
  recipes.build_then_share     — success + rollback (share fails → doc trashed LIFO)
  recipes.template_merge       — success (replaceAllText built) + rollback (merge fails → copy trashed)
  recipes.hydrate_then_refine  — success + rollback (refine fails; read-only hydrate → nothing to compensate)
"""
from __future__ import annotations

import importlib
from typing import Any

import pytest


# ─── Test-local mock infrastructure ──────────────────────────────────────────


class _Exec:
    def __init__(self, response: Any, error: Exception | None = None) -> None:
        self._response = response
        self._error = error

    def execute(self) -> Any:
        if self._error is not None:
            raise self._error
        return self._response


class _Proxy:
    def __init__(self, resource: str, svc: "FakeService") -> None:
        self._resource = resource
        self._svc = svc

    def __getattr__(self, method: str):
        def _call(**kwargs: Any) -> _Exec:
            self._svc.log.append((self._resource, method, dict(kwargs)))
            key = (self._resource, method)
            if key in self._svc.errors:
                return _Exec(None, error=self._svc.errors[key])
            return _Exec(self._svc.responses.get(key))

        return _call


class FakeService:
    """Configurable fake googleapiclient resource recording every call.

    ``responses`` maps ``(resource, method) -> canned dict``; ``errors`` maps
    ``(resource, method) -> Exception`` to inject a failure at ``.execute()``.
    """

    def __init__(
        self,
        responses: dict[tuple[str, str], Any] | None = None,
        errors: dict[tuple[str, str], Exception] | None = None,
    ) -> None:
        self.responses = responses or {}
        self.errors = errors or {}
        self.log: list[tuple[str, str, dict[str, Any]]] = []

    def files(self) -> _Proxy:
        return _Proxy("files", self)

    def permissions(self) -> _Proxy:
        return _Proxy("permissions", self)

    def documents(self) -> _Proxy:
        return _Proxy("documents", self)

    def calls_for(self, resource: str, method: str) -> list[dict[str, Any]]:
        return [kw for (r, m, kw) in self.log if r == resource and m == method]

    def methods(self) -> list[tuple[str, str]]:
        return [(r, m) for (r, m, _kw) in self.log]


@pytest.fixture(autouse=True, scope="module")
def _ensure_recipes() -> None:
    """Re-register recipe ops if the registry was cleared by test_registry.py."""
    import google_kit.registry as reg
    import google_kit.services.recipes as recipes_mod

    if "recipes.build_then_share" not in {s.name for s in reg.all_specs()}:
        importlib.reload(recipes_mod)


def _drive_with_doc(doc_id: str = "doc001", **extra: Any) -> FakeService:
    responses = {
        ("files", "create"): {
            "id": doc_id,
            "webViewLink": f"https://docs.google.com/document/d/{doc_id}/edit",
        },
        ("files", "copy"): {
            "id": doc_id,
            "name": "Copy",
            "webViewLink": f"https://docs.google.com/document/d/{doc_id}/edit",
        },
        ("files", "update"): {"id": doc_id, "trashed": True},
        ("files", "get"): {
            "id": doc_id,
            "name": "My Doc",
            "mimeType": "application/vnd.google-apps.document",
            "webViewLink": f"https://docs.google.com/document/d/{doc_id}/edit",
        },
        ("permissions", "create"): {"id": "perm1", "type": "user", "role": "writer"},
    }
    return FakeService(responses=responses, **extra)


def _docs_service(**extra: Any) -> FakeService:
    responses = {
        ("documents", "get"): {"body": {"content": []}},
        ("documents", "batchUpdate"): {"replies": [{"ok": True}]},
    }
    return FakeService(responses=responses, **extra)


# ─── recipes.build_then_share ─────────────────────────────────────────────────


class TestBuildThenShare:
    def test_success_threads_doc_id_and_shares(self) -> None:
        from google_kit.services.recipes.core import recipe_build_then_share
        from google_kit.services.recipes.models import BuildThenShareInput

        drive, docs = _drive_with_doc("doc001"), _docs_service()
        result = recipe_build_then_share(
            BuildThenShareInput(
                markdown_content="# Hi",
                title="Plan",
                share_with="t@example.com",
                role="writer",
            ),
            service={"drive": drive, "docs": docs},
        )

        assert result.data.status == "completed"
        assert result.data.doc_id == "doc001"
        assert result.data.shared_with == "t@example.com"
        assert result.meta.recipe_id == "build-then-share"
        assert result.meta.saga_compensated is False
        # shared the just-created doc id, with the requested role
        share_calls = drive.calls_for("permissions", "create")
        assert share_calls and share_calls[0]["fileId"] == "doc001"
        assert share_calls[0]["body"]["role"] == "writer"
        # success → no compensation (no trash)
        assert drive.calls_for("files", "update") == []

    def test_rollback_trashes_doc_when_share_fails(self) -> None:
        from google_kit.services.recipes.core import recipe_build_then_share
        from google_kit.services.recipes.models import BuildThenShareInput

        drive = _drive_with_doc("doc001", errors={("permissions", "create"): RuntimeError("403 sharing denied")})
        docs = _docs_service()
        result = recipe_build_then_share(
            BuildThenShareInput(markdown_content="# Hi", title="Plan", share_with="t@example.com"),
            service={"drive": drive, "docs": docs},
        )

        assert result.data.status == "rolled_back"
        assert result.data.doc_id == "doc001"  # partial id surfaced
        assert result.meta.saga_compensated is True
        assert result.warnings and "rolled back" in result.warnings[0]
        # LIFO compensation: the created doc was trashed (files.update trashed=true)
        trash_calls = drive.calls_for("files", "update")
        assert trash_calls and trash_calls[0]["fileId"] == "doc001"
        assert trash_calls[0]["body"]["trashed"] is True


# ─── recipes.template_merge ───────────────────────────────────────────────────


class TestTemplateMerge:
    def test_success_builds_replace_all_text(self) -> None:
        from google_kit.services.recipes.core import recipe_template_merge
        from google_kit.services.recipes.models import TemplateMergeInput

        drive, docs = _drive_with_doc("copy001"), _docs_service()
        result = recipe_template_merge(
            TemplateMergeInput(
                template_id="tmpl123",
                replacements={"{{name}}": "Jordan", "{{role}}": "Engineer"},
                new_name="Offer",
            ),
            service={"drive": drive, "docs": docs},
        )

        assert result.data.status == "completed"
        assert result.data.doc_id == "copy001"
        assert result.data.replacements_applied == 2
        assert result.meta.recipe_id == "template-merge"
        # copy targeted the template; merge targeted the copy
        copy_calls = drive.calls_for("files", "copy")
        assert copy_calls and copy_calls[0]["fileId"] == "tmpl123"
        merge_calls = docs.calls_for("documents", "batchUpdate")
        assert merge_calls and merge_calls[0]["documentId"] == "copy001"
        reqs = merge_calls[0]["body"]["requests"]
        assert all("replaceAllText" in r for r in reqs)
        texts = {r["replaceAllText"]["containsText"]["text"] for r in reqs}
        assert texts == {"{{name}}", "{{role}}"}
        assert reqs[0]["replaceAllText"]["containsText"]["matchCase"] is True

    def test_rollback_trashes_copy_when_merge_fails(self) -> None:
        from google_kit.services.recipes.core import recipe_template_merge
        from google_kit.services.recipes.models import TemplateMergeInput

        drive = _drive_with_doc("copy001")
        docs = _docs_service(errors={("documents", "batchUpdate"): RuntimeError("invalid request")})
        result = recipe_template_merge(
            TemplateMergeInput(template_id="tmpl123", replacements={"{{x}}": "y"}),
            service={"drive": drive, "docs": docs},
        )

        assert result.data.status == "rolled_back"
        assert result.data.doc_id == "copy001"
        assert result.meta.saga_compensated is True
        trash_calls = drive.calls_for("files", "update")
        assert trash_calls and trash_calls[0]["fileId"] == "copy001"


# ─── recipes.hydrate_then_refine ──────────────────────────────────────────────


class TestHydrateThenRefine:
    def test_success_reads_then_refines(self) -> None:
        from google_kit.services.recipes.core import recipe_hydrate_then_refine
        from google_kit.services.recipes.models import HydrateThenRefineInput

        drive, docs = _drive_with_doc("doc777"), _docs_service()
        result = recipe_hydrate_then_refine(
            HydrateThenRefineInput(
                document_id="doc777",
                requests=[{"insertText": {"location": {"index": 1}, "text": "S\n"}}],
            ),
            service={"drive": drive, "docs": docs},
        )

        assert result.data.status == "completed"
        assert result.data.doc_id == "doc777"
        assert result.data.title == "My Doc"
        assert result.data.requests_applied == 1
        assert result.data.refine_replies == [{"ok": True}]
        assert result.meta.recipe_id == "hydrate-then-refine"
        # read happened before write
        assert drive.methods() == [("files", "get")]
        assert docs.methods() == [("documents", "batchUpdate")]

    def test_rollback_when_refine_fails_has_nothing_to_compensate(self) -> None:
        from google_kit.services.recipes.core import recipe_hydrate_then_refine
        from google_kit.services.recipes.models import HydrateThenRefineInput

        drive = _drive_with_doc("doc777")
        docs = _docs_service(errors={("documents", "batchUpdate"): RuntimeError("boom")})
        result = recipe_hydrate_then_refine(
            HydrateThenRefineInput(document_id="doc777", requests=[{"x": 1}]),
            service={"drive": drive, "docs": docs},
        )

        assert result.data.status == "rolled_back"
        # hydrate is read-only → no compensator → saga_compensated stays False
        assert result.meta.saga_compensated is False
        assert result.warnings and "refine" in result.warnings[0]
        assert drive.calls_for("files", "update") == []  # no trash, nothing to undo


# ─── service resolver seam ────────────────────────────────────────────────────


class TestServiceResolver:
    def test_callable_resolver_is_accepted(self) -> None:
        from google_kit.services.recipes.core import recipe_build_then_share
        from google_kit.services.recipes.models import BuildThenShareInput

        drive, docs = _drive_with_doc("doc001"), _docs_service()
        resolver = lambda prefix: {"drive": drive, "docs": docs}[prefix]  # noqa: E731

        result = recipe_build_then_share(
            BuildThenShareInput(markdown_content="# Hi", title="T", share_with="t@example.com"),
            service=resolver,
        )
        assert result.data.status == "completed"

    def test_missing_resolver_raises(self) -> None:
        from google_kit.services.recipes.core import recipe_template_merge
        from google_kit.services.recipes.models import TemplateMergeInput

        with pytest.raises(ValueError, match="service resolver"):
            recipe_template_merge(
                TemplateMergeInput(template_id="x", replacements={}),
                service=None,
            )


# ─── CLI / MCP reachability (recipe resolver wiring) ──────────────────────────


class TestRecipeAdapterWiring:
    def test_cli_invokes_recipe_with_multi_api_resolver(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        from google_kit.cli import main

        monkeypatch.setenv("GOOGLE_KIT_ENABLE_WRITES", "1")
        drive, docs = _drive_with_doc("doc001"), _docs_service()

        def _factory(op_name: str, *, profile: str | None = None) -> Any:
            prefix = op_name.split(".")[0]
            return {"drive": drive, "docs": docs}[prefix]

        main(
            [
                "recipes", "build-then-share",
                "--markdown-content", "# Hi",
                "--title", "Plan",
                "--share-with", "t@example.com",
            ],
            _service_factory=_factory,
        )
        out = json.loads(capsys.readouterr().out)
        assert out["data"]["status"] == "completed"
        assert out["meta"]["recipe_id"] == "build-then-share"

    def test_cli_service_kwargs_returns_resolver_for_recipes(self) -> None:
        from google_kit.cli import _service_kwargs
        from google_kit.registry import get

        def _factory(op_name: str, *, profile: str | None = None) -> str:
            return f"svc::{op_name}"

        kwargs = _service_kwargs(get("recipes.template_merge"), _factory, "recipes.template_merge", None)
        assert set(kwargs) == {"service"}
        resolver = kwargs["service"]
        assert callable(resolver)
        assert resolver("drive") == "svc::drive._recipe"
        assert resolver("docs") == "svc::docs._recipe"

    def test_mcp_service_kwargs_returns_resolver_for_recipes(self) -> None:
        from google_kit.mcp import _service_kwargs
        from google_kit.registry import get

        def _factory(op_name: str, *, profile: str | None = None) -> str:
            return f"svc::{op_name}"

        kwargs = _service_kwargs(get("recipes.build_then_share"), _factory)
        resolver = kwargs["service"]
        assert callable(resolver)
        assert resolver("drive") == "svc::drive._recipe"

    def test_non_recipe_op_gets_single_service_unchanged(self) -> None:
        from google_kit.cli import _service_kwargs
        from google_kit.registry import get

        def _factory(op_name: str, *, profile: str | None = None) -> str:
            return f"svc::{op_name}"

        kwargs = _service_kwargs(get("drive.create"), _factory, "drive.create", None)
        assert kwargs == {"service": "svc::drive.create"}
