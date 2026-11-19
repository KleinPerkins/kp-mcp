"""Tests for the Slides service (cutover-minimum: 5 ops).

Parity status per op:
  slides_create      — mutation-request DONE; sandbox-e2e awaiting operator creds (P6 gate)
  slides_get         — semantic DONE (P6); sandbox-e2e awaiting operator creds (P6 gate)
  slides_add_slide   — mutation-request DONE; sandbox-e2e awaiting operator creds (P6 gate)
  slides_update_text — mutation-request DONE; sandbox-e2e awaiting operator creds (P6 gate)
  slides_add_image   — mutation-request DONE; sandbox-e2e awaiting operator creds (P6 gate)

Mock infrastructure: MockSlidesService extends MockGoogleService with
``presentations()`` (supporting create/get/batchUpdate) and ``files()``
(supporting update for folder moves). Defined here to isolate slides-specific
proxy methods without modifying mock_google.py.

GET parity for slides_get: uses compare("semantic", ...) which applies
RULE_IGNORE_GENERATED_IDS, RULE_NORMALIZE_REVISION_ETAG, and
RULE_ADDITIVE_OPTIONAL_FIELDS — handles revision_id, object_id, layout_object_id
nondeterminism transparently.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from kp_mcp_testkit.mock_google import MockGoogleService, _MockResourceProxy
from kp_mcp_testkit.parity import compare


class _PagesProxy(_MockResourceProxy):
    """Proxy for the ``pages`` sub-resource of the Slides presentations resource."""

    def getThumbnail(self, **kwargs: Any) -> Any:
        return self._call("getThumbnail", **kwargs)


class _SlidesProxy(_MockResourceProxy):
    """Proxy that adds ``create``, ``batchUpdate``, and ``pages`` for the Slides API."""

    def create(self, **kwargs: Any) -> Any:
        return self._call("create", **kwargs)

    def batchUpdate(self, **kwargs: Any) -> Any:
        return self._call("batchUpdate", **kwargs)

    def pages(self) -> _PagesProxy:
        return _PagesProxy("pages", self._responses, self._requests)


class MockSlidesService(MockGoogleService):
    """Fake service supporting both presentations and drive.files operations."""

    def presentations(self) -> _SlidesProxy:
        return _SlidesProxy("presentations", self._responses, self._requests)

    def files(self) -> _SlidesProxy:
        return _SlidesProxy("files", self._responses, self._requests)


FIXTURES = Path(__file__).parent.parent / "fixtures" / "golden" / "slides"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True, scope="module")
def _ensure_slides(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Re-register Slides ops if the registry was cleared by test_registry.py."""
    import google_kit.registry as reg
    import google_kit.services.slides as slides_mod

    if not {"slides.create", "slides.thumbnail"}.issubset({s.name for s in reg.all_specs()}):
        importlib.reload(slides_mod)


class TestSlidesCreate:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.slides.core import slides_create
        from google_kit.services.slides.models import SlidesCreateInput

        expected_body = _load("create_expected_body.json")
        canned = {
            "presentationId": "pres001",
            "title": "My Presentation",
            "slides": [],
        }
        svc = MockSlidesService(responses={("presentations", "create"): canned})
        slides_create(SlidesCreateInput(title="My Presentation"), service=svc)

        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_create_returns_envelope(self) -> None:
        from google_kit.services.slides.core import slides_create
        from google_kit.services.slides.models import SlidesCreateInput

        canned = {
            "presentationId": "pres001",
            "title": "My Presentation",
            "slides": [{}],
        }
        svc = MockSlidesService(responses={("presentations", "create"): canned})
        result = slides_create(SlidesCreateInput(title="My Presentation"), service=svc)
        assert result.data.presentation_id == "pres001"
        assert result.data.slide_count == 1
        assert "pres001" in result.data.url

    def test_folder_move_calls_drive_update(self) -> None:
        from google_kit.services.slides.core import slides_create
        from google_kit.services.slides.models import SlidesCreateInput

        canned = {"presentationId": "pres001", "title": "t", "slides": []}
        svc = MockSlidesService(responses={
            ("presentations", "create"): canned,
            ("files", "update"): {"id": "pres001", "parents": ["folder001"]},
        })
        slides_create(
            SlidesCreateInput(title="t", folder_id="folder001"),
            service=svc,
            drive_service=svc,
        )
        file_reqs = svc.requests_for("files", "update")
        assert len(file_reqs) == 1
        assert file_reqs[0].kwargs.get("fileId") == "pres001"
        assert file_reqs[0].kwargs.get("addParents") == "folder001"
        assert file_reqs[0].kwargs.get("removeParents") == "root"

    def test_no_folder_move_when_no_folder_id(self) -> None:
        from google_kit.services.slides.core import slides_create
        from google_kit.services.slides.models import SlidesCreateInput

        canned = {"presentationId": "pres001", "title": "t", "slides": []}
        svc = MockSlidesService(responses={("presentations", "create"): canned})
        slides_create(SlidesCreateInput(title="t"), service=svc, drive_service=svc)
        assert svc.requests_for("files", "update") == []


class TestSlidesGet:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.slides.core import slides_get
        from google_kit.services.slides.models import SlidesGetInput

        response = _load("get_response.json")
        expected = _load("get_expected.json")

        svc = MockSlidesService(responses={("presentations", "get"): response})
        result = slides_get(SlidesGetInput(presentation_id="pres001"), service=svc)

        actual = result.data.model_dump()
        parity = compare("semantic", expected, actual)
        assert parity.match, f"semantic mismatch:\n{parity.diff}"

    def test_slide_count(self) -> None:
        from google_kit.services.slides.core import slides_get
        from google_kit.services.slides.models import SlidesGetInput

        response = _load("get_response.json")
        svc = MockSlidesService(responses={("presentations", "get"): response})
        result = slides_get(SlidesGetInput(presentation_id="pres001"), service=svc)
        assert result.data.slide_count == 2

    def test_element_count_per_slide(self) -> None:
        from google_kit.services.slides.core import slides_get
        from google_kit.services.slides.models import SlidesGetInput

        response = _load("get_response.json")
        svc = MockSlidesService(responses={("presentations", "get"): response})
        result = slides_get(SlidesGetInput(presentation_id="pres001"), service=svc)
        assert result.data.slides[0].element_count == 2
        assert result.data.slides[1].element_count == 0

    def test_url_format(self) -> None:
        from google_kit.services.slides.core import slides_get
        from google_kit.services.slides.models import SlidesGetInput

        canned = {"presentationId": "abc123", "title": "t", "revisionId": "r1", "slides": []}
        svc = MockSlidesService(responses={("presentations", "get"): canned})
        result = slides_get(SlidesGetInput(presentation_id="abc123"), service=svc)
        assert result.data.url == "https://docs.google.com/presentation/d/abc123/edit"


class TestSlidesAddSlide:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.slides.core import slides_add_slide
        from google_kit.services.slides.models import SlidesAddSlideInput

        expected_body = _load("add_slide_expected_body.json")
        canned = {
            "presentationId": "pres001",
            "replies": [{"createSlide": {"objectId": "slide_new_001"}}],
        }
        svc = MockSlidesService(responses={("presentations", "batchUpdate"): canned})
        slides_add_slide(
            SlidesAddSlideInput(presentation_id="pres001", layout="BLANK"),
            service=svc,
        )
        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_returns_slide_id(self) -> None:
        from google_kit.services.slides.core import slides_add_slide
        from google_kit.services.slides.models import SlidesAddSlideInput

        canned = {
            "presentationId": "pres001",
            "replies": [{"createSlide": {"objectId": "slide_new_001"}}],
        }
        svc = MockSlidesService(responses={("presentations", "batchUpdate"): canned})
        result = slides_add_slide(
            SlidesAddSlideInput(presentation_id="pres001", layout="BLANK"),
            service=svc,
        )
        assert result.data.slide_id == "slide_new_001"

    def test_insert_at_included_in_body(self) -> None:
        from google_kit.services.slides.core import slides_add_slide
        from google_kit.services.slides.models import SlidesAddSlideInput

        canned = {
            "presentationId": "pres001",
            "replies": [{"createSlide": {"objectId": "s1"}}],
        }
        svc = MockSlidesService(responses={("presentations", "batchUpdate"): canned})
        slides_add_slide(
            SlidesAddSlideInput(presentation_id="pres001", layout="TITLE", insert_at=2),
            service=svc,
        )
        req = svc.requests_for("presentations", "batchUpdate")[0]
        body = req.body
        assert body is not None
        create_slide = body["requests"][0]["createSlide"]
        assert create_slide["insertionIndex"] == 2
        assert create_slide["slideLayoutReference"]["predefinedLayout"] == "TITLE"

    def test_title_text_triggers_get_and_insert(self) -> None:
        from google_kit.services.slides.core import slides_add_slide
        from google_kit.services.slides.models import SlidesAddSlideInput

        batch_reply = {
            "presentationId": "pres001",
            "replies": [{"createSlide": {"objectId": "slide_new_001"}}],
        }
        get_response = {
            "presentationId": "pres001",
            "slides": [
                {
                    "objectId": "slide_new_001",
                    "pageElements": [
                        {
                            "objectId": "title_elem_001",
                            "shape": {"placeholder": {"type": "TITLE"}},
                        }
                    ],
                }
            ],
        }
        svc = MockSlidesService(responses={
            ("presentations", "batchUpdate"): batch_reply,
            ("presentations", "get"): get_response,
        })
        slides_add_slide(
            SlidesAddSlideInput(
                presentation_id="pres001",
                layout="TITLE",
                title_text="Hello World",
            ),
            service=svc,
        )
        batch_reqs = svc.requests_for("presentations", "batchUpdate")
        assert len(batch_reqs) == 2, "Expected createSlide + insertText batchUpdate"
        insert_body = batch_reqs[1].body
        assert insert_body is not None
        insert_req = insert_body["requests"][0]["insertText"]
        assert insert_req["objectId"] == "title_elem_001"
        assert insert_req["text"] == "Hello World"
        assert insert_req["insertionIndex"] == 0


class TestSlidesUpdateText:
    def test_mutation_request_parity_replace_all(self) -> None:
        from google_kit.services.slides.core import slides_update_text
        from google_kit.services.slides.models import SlidesUpdateTextInput

        expected_body = _load("update_text_expected_body.json")
        canned = {
            "presentationId": "pres001",
            "replies": [{"replaceAllText": {"occurrencesChanged": 2}}],
        }
        svc = MockSlidesService(responses={("presentations", "batchUpdate"): canned})
        slides_update_text(
            SlidesUpdateTextInput(
                presentation_id="pres001",
                find="{{TITLE}}",
                replace="My Title",
            ),
            service=svc,
        )
        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_occurrences_changed_extracted(self) -> None:
        from google_kit.services.slides.core import slides_update_text
        from google_kit.services.slides.models import SlidesUpdateTextInput

        canned = {
            "presentationId": "pres001",
            "replies": [{"replaceAllText": {"occurrencesChanged": 3}}],
        }
        svc = MockSlidesService(responses={("presentations", "batchUpdate"): canned})
        result = slides_update_text(
            SlidesUpdateTextInput(
                presentation_id="pres001",
                find="{{NAME}}",
                replace="Alice",
            ),
            service=svc,
        )
        assert result.data.occurrences_changed == 3

    def test_match_case_true(self) -> None:
        from google_kit.services.slides.core import slides_update_text
        from google_kit.services.slides.models import SlidesUpdateTextInput

        canned = {"presentationId": "pres001", "replies": [{"replaceAllText": {"occurrencesChanged": 1}}]}
        svc = MockSlidesService(responses={("presentations", "batchUpdate"): canned})
        slides_update_text(
            SlidesUpdateTextInput(presentation_id="pres001", find="foo", replace="bar"),
            service=svc,
        )
        body = svc.last_request_body()
        assert body is not None
        assert body["requests"][0]["replaceAllText"]["containsText"]["matchCase"] is True

    def test_direct_mode_sends_delete_then_insert(self) -> None:
        from google_kit.services.slides.core import slides_update_text
        from google_kit.services.slides.models import SlidesUpdateTextInput

        canned = {"presentationId": "pres001", "replies": [{}, {}]}
        svc = MockSlidesService(responses={("presentations", "batchUpdate"): canned})
        slides_update_text(
            SlidesUpdateTextInput(
                presentation_id="pres001",
                object_id="shape001",
                text="New content",
            ),
            service=svc,
        )
        body = svc.last_request_body()
        assert body is not None
        req_types = [list(r.keys())[0] for r in body["requests"]]
        assert "deleteText" in req_types
        assert "insertText" in req_types

    def test_raises_when_no_mode_specified(self) -> None:
        from google_kit.services.slides.core import slides_update_text
        from google_kit.services.slides.models import SlidesUpdateTextInput

        svc = MockSlidesService(responses={})
        with pytest.raises(ValueError, match="find.*replace.*object_id.*text"):
            slides_update_text(
                SlidesUpdateTextInput(presentation_id="pres001"),
                service=svc,
            )


class TestSlidesAddImage:
    def test_mutation_request_parity(self) -> None:
        from google_kit.services.slides.core import slides_add_image
        from google_kit.services.slides.models import SlidesAddImageInput

        expected_body = _load("add_image_expected_body.json")
        canned = {
            "presentationId": "pres001",
            "replies": [{"createImage": {"objectId": "image_test001"}}],
        }
        svc = MockSlidesService(responses={("presentations", "batchUpdate"): canned})
        slides_add_image(
            SlidesAddImageInput(
                presentation_id="pres001",
                slide_id="slide001",
                url="https://example.com/img.jpg",
                x=1.0,
                y=1.0,
                width=4.0,
                height=3.0,
                object_id="image_test001",
            ),
            service=svc,
        )
        actual_body = svc.last_request_body()
        parity = compare("mutation-request", expected_body, actual_body)
        assert parity.match, f"mutation-request body mismatch:\n{parity.diff}"

    def test_emu_conversion(self) -> None:
        from google_kit.services.slides.core import slides_add_image
        from google_kit.services.slides.models import SlidesAddImageInput

        canned = {"presentationId": "p1", "replies": [{"createImage": {"objectId": "img_x"}}]}
        svc = MockSlidesService(responses={("presentations", "batchUpdate"): canned})
        slides_add_image(
            SlidesAddImageInput(
                presentation_id="p1",
                slide_id="s1",
                url="https://example.com/a.jpg",
                x=2.0,
                y=0.5,
                width=6.0,
                height=4.5,
                object_id="img_x",
            ),
            service=svc,
        )
        body = svc.last_request_body()
        props = body["requests"][0]["createImage"]["elementProperties"]
        assert props["transform"]["translateX"] == 2 * 914400
        assert props["transform"]["translateY"] == int(0.5 * 914400)
        assert props["size"]["width"]["magnitude"] == 6 * 914400
        assert props["size"]["height"]["magnitude"] == int(4.5 * 914400)

    def test_auto_generated_object_id_when_not_provided(self) -> None:
        from google_kit.services.slides.core import slides_add_image
        from google_kit.services.slides.models import SlidesAddImageInput

        canned = {"presentationId": "p1", "replies": [{"createImage": {"objectId": "auto"}}]}
        svc = MockSlidesService(responses={("presentations", "batchUpdate"): canned})
        result = slides_add_image(
            SlidesAddImageInput(presentation_id="p1", slide_id="s1", url="https://x.com/i.jpg"),
            service=svc,
        )
        assert result.data.object_id.startswith("image_")
        body = svc.last_request_body()
        assert body["requests"][0]["createImage"]["objectId"].startswith("image_")

    def test_injectable_object_id_is_deterministic(self) -> None:
        from google_kit.services.slides.core import slides_add_image
        from google_kit.services.slides.models import SlidesAddImageInput

        canned = {"presentationId": "p1", "replies": [{"createImage": {"objectId": "fixed_id"}}]}
        svc = MockSlidesService(responses={("presentations", "batchUpdate"): canned})
        result = slides_add_image(
            SlidesAddImageInput(
                presentation_id="p1",
                slide_id="s1",
                url="https://x.com/i.jpg",
                object_id="fixed_id",
            ),
            service=svc,
        )
        assert result.data.object_id == "fixed_id"
        body = svc.last_request_body()
        assert body["requests"][0]["createImage"]["objectId"] == "fixed_id"


class TestSlidesThumbnail:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.slides.core import slides_thumbnail
        from google_kit.services.slides.models import SlidesThumbnailInput

        response = _load("thumbnail_response.json")
        expected = _load("thumbnail_expected.json")

        svc = MockSlidesService(responses={("pages", "getThumbnail"): response})
        result = slides_thumbnail(
            SlidesThumbnailInput(presentation_id="pres001", page_object_id="slide001"),
            service=svc,
        )

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_returns_content_url_width_height(self) -> None:
        from google_kit.services.slides.core import slides_thumbnail
        from google_kit.services.slides.models import SlidesThumbnailInput

        response = _load("thumbnail_response.json")
        svc = MockSlidesService(responses={("pages", "getThumbnail"): response})
        result = slides_thumbnail(
            SlidesThumbnailInput(presentation_id="pres001", page_object_id="slide001"),
            service=svc,
        )
        assert result.data.content_url.startswith("https://")
        assert result.data.width == 1600
        assert result.data.height == 900

    def test_thumbnail_properties_passed_when_provided(self) -> None:
        from google_kit.services.slides.core import slides_thumbnail
        from google_kit.services.slides.models import SlidesThumbnailInput

        canned = {"contentUrl": "https://example.com/thumb.png", "width": 800, "height": 450}
        svc = MockSlidesService(responses={("pages", "getThumbnail"): canned})
        slides_thumbnail(
            SlidesThumbnailInput(
                presentation_id="pres001",
                page_object_id="slide001",
                mime_type="PNG",
                thumbnail_size="LARGE",
            ),
            service=svc,
        )
        reqs = svc.requests_for("pages", "getThumbnail")
        assert len(reqs) == 1
        kwargs = reqs[0].kwargs
        assert kwargs.get("thumbnailProperties_mimeType") == "PNG"
        assert kwargs.get("thumbnailProperties_thumbnailSize") == "LARGE"

    def test_thumbnail_properties_omitted_when_not_provided(self) -> None:
        from google_kit.services.slides.core import slides_thumbnail
        from google_kit.services.slides.models import SlidesThumbnailInput

        canned = {"contentUrl": "https://example.com/thumb.png", "width": 800, "height": 450}
        svc = MockSlidesService(responses={("pages", "getThumbnail"): canned})
        slides_thumbnail(
            SlidesThumbnailInput(presentation_id="pres001", page_object_id="slide001"),
            service=svc,
        )
        kwargs = svc.requests_for("pages", "getThumbnail")[0].kwargs
        assert "thumbnailProperties_mimeType" not in kwargs
        assert "thumbnailProperties_thumbnailSize" not in kwargs

    def test_passes_presentation_id_and_page_object_id(self) -> None:
        from google_kit.services.slides.core import slides_thumbnail
        from google_kit.services.slides.models import SlidesThumbnailInput

        canned = {"contentUrl": "https://example.com/t.png", "width": 400, "height": 225}
        svc = MockSlidesService(responses={("pages", "getThumbnail"): canned})
        slides_thumbnail(
            SlidesThumbnailInput(presentation_id="abc123", page_object_id="p_xyz"),
            service=svc,
        )
        kwargs = svc.requests_for("pages", "getThumbnail")[0].kwargs
        assert kwargs["presentationId"] == "abc123"
        assert kwargs["pageObjectId"] == "p_xyz"


class TestRegistryIntegration:
    def test_all_six_ops_registered(self) -> None:
        import google_kit.registry as reg

        names = {s.name for s in reg.all_specs()}
        expected = {
            "slides.create",
            "slides.get",
            "slides.add_slide",
            "slides.update_text",
            "slides.add_image",
            "slides.thumbnail",
        }
        assert expected.issubset(names), f"Missing ops: {expected - names}"

    def test_slides_postures(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        assert specs["slides.create"].posture == "write"
        assert specs["slides.get"].posture == "read"
        assert specs["slides.add_slide"].posture == "write"
        assert specs["slides.update_text"].posture == "write"
        assert specs["slides.add_image"].posture == "write"
        assert specs["slides.thumbnail"].posture == "read"

    def test_slides_scopes(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        pres_scope = "https://www.googleapis.com/auth/presentations"
        pres_readonly = "https://www.googleapis.com/auth/presentations.readonly"
        # Writes hold the read-write scope; reads tightened to .readonly (gate c).
        assert pres_scope in specs["slides.create"].scopes
        assert pres_scope in specs["slides.add_slide"].scopes
        assert pres_readonly in specs["slides.get"].scopes
        assert pres_readonly in specs["slides.thumbnail"].scopes
