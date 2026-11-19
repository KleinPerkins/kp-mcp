"""Tests for the Forms service.

Forms API quirk: forms.create uses a two-call sequence — forms().create() for
title/documentTitle, then forms().batchUpdate(updateFormInfo) for description.
This is replicated faithfully from gforms.py (cmd_create).

MockGoogleService is extended with a Forms-aware subclass (FormsMockGoogleService)
that adds forms(), batchUpdate(), nested responses() support, setPublishSettings(),
and watches() sub-proxy.
The subclass records all requests using the same RequestRecord format so
MockGoogleService's last_request_body() / requests_for() helpers work unchanged.

Coverage:
  forms_create         — mutation-request parity (two-call sequence: create + batchUpdate)
  forms_get            — mock-read parity (normalized-json; nondeterministic fields excluded)
  forms_list_responses — mock-read parity (normalized-json; + pagination §7)
  forms_add_item       — mutation-request parity (scale 1–5; multiple_choice with options)
  forms_update         — mutation-request parity (dynamic updateMask)
  forms_publish        — mutation-request parity (setPublishSettings body)
  forms_get_response   — mock-read parity (normalized-json; single response by id)
  forms_watches        — mutation-request parity (watches.create body + formId forwarding)

Parity status per op:
  forms_create         — mutation-request DONE; sandbox-e2e awaiting operator creds (P6 gate)
  forms_get            — semantic DONE (P6); sandbox-e2e awaiting operator creds (P6 gate)
  forms_list_responses — mock-read DONE (+ pagination §7); sandbox-e2e awaiting operator creds (P6 gate)
  forms_add_item       — mutation-request DONE; sandbox-e2e awaiting operator creds (P6 gate)
  forms_update         — mutation-request DONE; sandbox-e2e awaiting operator creds (P6 gate)
  forms_publish        — mutation-request DONE; sandbox-e2e awaiting operator creds (P6 gate)
  forms_get_response   — mock-read DONE; sandbox-e2e awaiting operator creds (P6 gate)
  forms_watches        — mutation-request DONE; sandbox-e2e awaiting operator creds (P6 gate)
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from kp_mcp_testkit.mock_google import MockGoogleService, RequestRecord
from kp_mcp_testkit.parity import compare


FIXTURES = Path(__file__).parent.parent / "fixtures" / "golden" / "forms"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# ─────────────────────────────────────────────────────────────────────────────
#  Forms-aware mock extension
# ─────────────────────────────────────────────────────────────────────────────

class _FormsExecutable:
    def __init__(self, response: Any) -> None:
        self._response = response

    def execute(self) -> Any:
        return self._response


class _ResponsesProxy:
    """Fake resource for service.forms().responses() chain."""

    def __init__(
        self,
        responses: dict[tuple[str, str], Any],
        requests: list[RequestRecord],
    ) -> None:
        self._responses = responses
        self._requests = requests

    def list(self, **kwargs: Any) -> _FormsExecutable:
        self._requests.append(
            RequestRecord(resource="responses", method="list", kwargs=dict(kwargs))
        )
        return _FormsExecutable(self._responses.get(("responses", "list")))

    def get(self, **kwargs: Any) -> _FormsExecutable:
        self._requests.append(
            RequestRecord(resource="responses", method="get", kwargs=dict(kwargs))
        )
        return _FormsExecutable(self._responses.get(("responses", "get")))


class _WatchesProxy:
    """Fake resource for service.forms().watches() chain."""

    def __init__(
        self,
        responses: dict[tuple[str, str], Any],
        requests: list[RequestRecord],
    ) -> None:
        self._responses = responses
        self._requests = requests

    def create(self, **kwargs: Any) -> _FormsExecutable:
        self._requests.append(
            RequestRecord(resource="watches", method="create", kwargs=dict(kwargs))
        )
        return _FormsExecutable(self._responses.get(("watches", "create")))


class _FormsProxy:
    """Fake resource for service.forms() chain; supports create/get/batchUpdate/responses/watches."""

    def __init__(
        self,
        responses: dict[tuple[str, str], Any],
        requests: list[RequestRecord],
    ) -> None:
        self._responses = responses
        self._requests = requests

    def create(self, **kwargs: Any) -> _FormsExecutable:
        self._requests.append(
            RequestRecord(resource="forms", method="create", kwargs=dict(kwargs))
        )
        return _FormsExecutable(self._responses.get(("forms", "create")))

    def get(self, **kwargs: Any) -> _FormsExecutable:
        self._requests.append(
            RequestRecord(resource="forms", method="get", kwargs=dict(kwargs))
        )
        return _FormsExecutable(self._responses.get(("forms", "get")))

    def batchUpdate(self, **kwargs: Any) -> _FormsExecutable:
        self._requests.append(
            RequestRecord(resource="forms", method="batchUpdate", kwargs=dict(kwargs))
        )
        return _FormsExecutable(self._responses.get(("forms", "batchUpdate")))

    def setPublishSettings(self, **kwargs: Any) -> _FormsExecutable:
        self._requests.append(
            RequestRecord(resource="forms", method="setPublishSettings", kwargs=dict(kwargs))
        )
        return _FormsExecutable(self._responses.get(("forms", "setPublishSettings")))

    def responses(self) -> _ResponsesProxy:
        return _ResponsesProxy(self._responses, self._requests)

    def watches(self) -> _WatchesProxy:
        return _WatchesProxy(self._responses, self._requests)


class FormsMockGoogleService(MockGoogleService):
    """MockGoogleService extended with Forms API resource support."""

    def forms(self) -> _FormsProxy:
        return _FormsProxy(self._responses, self._requests)


# ─────────────────────────────────────────────────────────────────────────────
#  Registry isolation fixture
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True, scope="module")
def _ensure_forms() -> None:
    """Re-register Forms ops if the registry was cleared by test_registry.py."""
    import google_kit.registry as reg
    import google_kit.services.forms as forms_mod

    required = {"forms.create", "forms.publish", "forms.get_response", "forms.watches"}
    if not required.issubset({s.name for s in reg.all_specs()}):
        importlib.reload(forms_mod)


# ─────────────────────────────────────────────────────────────────────────────
#  forms.create
# ─────────────────────────────────────────────────────────────────────────────

class TestFormsCreate:
    def test_mutation_request_parity_two_calls(self) -> None:
        """Assert both the create body and the description batchUpdate body match legacy."""
        from google_kit.services.forms.core import forms_create
        from google_kit.services.forms.models import FormsCreateInput

        expected_create_body = _load("create_expected_body.json")
        expected_desc_body = _load("create_description_expected_body.json")

        svc = FormsMockGoogleService(responses={
            ("forms", "create"): {
                "formId": "abc123",
                "info": {"title": "My Survey"},
                "responderUri": "https://docs.google.com/forms/d/abc123/viewform",
            },
            ("forms", "batchUpdate"): {"form": {}, "replies": []},
        })

        forms_create(
            FormsCreateInput(title="My Survey", description="Please fill out this survey."),
            service=svc,
        )

        create_reqs = svc.requests_for("forms", "create")
        assert len(create_reqs) == 1, "Expected exactly one forms.create call"
        parity1 = compare("mutation-request", expected_create_body, create_reqs[0].body)
        assert parity1.match, f"create body mismatch:\n{parity1.diff}"

        batch_reqs = svc.requests_for("forms", "batchUpdate")
        assert len(batch_reqs) == 1, "Expected exactly one batchUpdate call for description"
        parity2 = compare("mutation-request", expected_desc_body, batch_reqs[0].body)
        assert parity2.match, f"description batchUpdate body mismatch:\n{parity2.diff}"

    def test_no_description_skips_batchupdate(self) -> None:
        from google_kit.services.forms.core import forms_create
        from google_kit.services.forms.models import FormsCreateInput

        svc = FormsMockGoogleService(responses={
            ("forms", "create"): {
                "formId": "abc123",
                "info": {"title": "Simple Form"},
                "responderUri": "https://docs.google.com/forms/d/abc123/viewform",
            },
        })

        forms_create(FormsCreateInput(title="Simple Form"), service=svc)

        assert len(svc.requests_for("forms", "create")) == 1
        assert len(svc.requests_for("forms", "batchUpdate")) == 0

    def test_output_envelope(self) -> None:
        from google_kit.services.forms.core import forms_create
        from google_kit.services.forms.models import FormsCreateInput

        svc = FormsMockGoogleService(responses={
            ("forms", "create"): {
                "formId": "xyz",
                "info": {"title": "Titled"},
                "responderUri": "https://docs.google.com/forms/d/xyz/viewform",
            },
        })

        result = forms_create(FormsCreateInput(title="Titled"), service=svc)
        assert result.data.form_id == "xyz"
        assert result.data.title == "Titled"
        assert "xyz" in result.data.responder_uri

    def test_document_title_included_in_body(self) -> None:
        from google_kit.services.forms.core import forms_create
        from google_kit.services.forms.models import FormsCreateInput

        svc = FormsMockGoogleService(responses={
            ("forms", "create"): {
                "formId": "d1",
                "info": {"title": "T"},
                "responderUri": "https://docs.google.com/forms/d/d1/viewform",
            },
        })

        forms_create(FormsCreateInput(title="T", document_title="Doc Title"), service=svc)

        body = svc.requests_for("forms", "create")[0].body
        assert body["info"]["documentTitle"] == "Doc Title"


# ─────────────────────────────────────────────────────────────────────────────
#  forms.get
# ─────────────────────────────────────────────────────────────────────────────

class TestFormsGet:
    def test_mock_read_parity(self) -> None:
        """Semantic parity: handles nondeterministic fields (formId, responderUri etc.)."""
        from google_kit.services.forms.core import forms_get
        from google_kit.services.forms.models import FormsGetInput

        response = _load("get_response.json")
        expected = _load("get_expected.json")

        svc = FormsMockGoogleService(responses={("forms", "get"): response})
        result = forms_get(FormsGetInput(form_id="1FAIpQLSe_NONDETERMINISTIC"), service=svc)

        actual = result.data.model_dump()
        parity = compare("semantic", expected, actual)
        assert parity.match, f"semantic mismatch:\n{parity.diff}"

    def test_item_count(self) -> None:
        from google_kit.services.forms.core import forms_get
        from google_kit.services.forms.models import FormsGetInput

        response = _load("get_response.json")
        svc = FormsMockGoogleService(responses={("forms", "get"): response})
        result = forms_get(FormsGetInput(form_id="x"), service=svc)
        assert result.data.item_count == 3

    def test_empty_form(self) -> None:
        from google_kit.services.forms.core import forms_get
        from google_kit.services.forms.models import FormsGetInput

        svc = FormsMockGoogleService(responses={
            ("forms", "get"): {
                "formId": "empty",
                "info": {"title": "Empty Form"},
                "items": [],
            }
        })
        result = forms_get(FormsGetInput(form_id="empty"), service=svc)
        assert result.data.item_count == 0
        assert result.data.items == []
        assert result.data.title == "Empty Form"

    def test_nondeterministic_fields_excluded(self) -> None:
        """formId, responderUri, revisionId not present in FormsGetData."""
        from google_kit.services.forms.core import forms_get
        from google_kit.services.forms.models import FormsGetInput

        svc = FormsMockGoogleService(responses={
            ("forms", "get"): {
                "formId": "should-not-appear",
                "info": {"title": "T"},
                "revisionId": "rev999",
                "responderUri": "https://...",
                "items": [],
            }
        })
        result = forms_get(FormsGetInput(form_id="should-not-appear"), service=svc)
        dumped = result.data.model_dump()
        assert "form_id" not in dumped
        assert "responder_uri" not in dumped
        assert "revision_id" not in dumped


# ─────────────────────────────────────────────────────────────────────────────
#  forms.list_responses
# ─────────────────────────────────────────────────────────────────────────────

class TestFormsListResponses:
    def test_mock_read_parity(self) -> None:
        from google_kit.services.forms.core import forms_list_responses
        from google_kit.services.forms.models import FormsListResponsesInput

        response = _load("list_responses_response.json")
        expected = _load("list_responses_expected.json")

        svc = FormsMockGoogleService(responses={("responses", "list"): response})
        result = forms_list_responses(
            FormsListResponsesInput(form_id="1FAIpQLSe_NONDETERMINISTIC"), service=svc
        )

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_empty_responses(self) -> None:
        from google_kit.services.forms.core import forms_list_responses
        from google_kit.services.forms.models import FormsListResponsesInput

        svc = FormsMockGoogleService(responses={("responses", "list"): {"responses": []}})
        result = forms_list_responses(FormsListResponsesInput(form_id="x"), service=svc)
        assert result.data.count == 0
        assert result.data.responses == []

    def test_form_id_passed_in_request(self) -> None:
        from google_kit.services.forms.core import forms_list_responses
        from google_kit.services.forms.models import FormsListResponsesInput

        svc = FormsMockGoogleService(responses={("responses", "list"): {}})
        forms_list_responses(FormsListResponsesInput(form_id="form_abc"), service=svc)
        req = svc.requests_for("responses", "list")[0]
        assert req.kwargs.get("formId") == "form_abc"


# ─────────────────────────────────────────────────────────────────────────────
#  forms.add_item
# ─────────────────────────────────────────────────────────────────────────────

class TestFormsAddItem:
    def test_mutation_request_parity_scale(self) -> None:
        from google_kit.services.forms.core import forms_add_item
        from google_kit.services.forms.models import FormsAddItemInput

        expected_body = _load("add_item_scale_expected_body.json")

        svc = FormsMockGoogleService(responses={
            ("forms", "batchUpdate"): {"form": {}, "replies": [{"createItem": {}}]},
        })

        forms_add_item(
            FormsAddItemInput(
                form_id="form001",
                title="Rate your experience",
                item_type="scale",
            ),
            service=svc,
        )

        batch_reqs = svc.requests_for("forms", "batchUpdate")
        assert batch_reqs, "No batchUpdate call recorded"
        parity = compare("mutation-request", expected_body, batch_reqs[0].body)
        assert parity.match, f"scale add_item body mismatch:\n{parity.diff}"

    def test_mutation_request_parity_multiple_choice(self) -> None:
        from google_kit.services.forms.core import forms_add_item
        from google_kit.services.forms.models import FormsAddItemInput

        expected_body = _load("add_item_multiple_choice_expected_body.json")

        svc = FormsMockGoogleService(responses={
            ("forms", "batchUpdate"): {"form": {}, "replies": []},
        })

        forms_add_item(
            FormsAddItemInput(
                form_id="form001",
                title="What is your role?",
                item_type="multiple_choice",
                options="Engineer,Designer,Manager",
                required=True,
                index=1,
            ),
            service=svc,
        )

        batch_reqs = svc.requests_for("forms", "batchUpdate")
        assert batch_reqs
        parity = compare("mutation-request", expected_body, batch_reqs[0].body)
        assert parity.match, f"multiple_choice add_item body mismatch:\n{parity.diff}"

    def test_short_text_item(self) -> None:
        from google_kit.services.forms.core import forms_add_item
        from google_kit.services.forms.models import FormsAddItemInput

        svc = FormsMockGoogleService(responses={("forms", "batchUpdate"): {}})
        forms_add_item(
            FormsAddItemInput(form_id="f1", title="Your name", item_type="short_text"),
            service=svc,
        )
        body = svc.requests_for("forms", "batchUpdate")[0].body
        q = body["requests"][0]["createItem"]["item"]["questionItem"]["question"]
        assert "textQuestion" in q
        assert q["textQuestion"] == {}

    def test_paragraph_item(self) -> None:
        from google_kit.services.forms.core import forms_add_item
        from google_kit.services.forms.models import FormsAddItemInput

        svc = FormsMockGoogleService(responses={("forms", "batchUpdate"): {}})
        forms_add_item(
            FormsAddItemInput(form_id="f1", title="Tell us more", item_type="paragraph"),
            service=svc,
        )
        body = svc.requests_for("forms", "batchUpdate")[0].body
        q = body["requests"][0]["createItem"]["item"]["questionItem"]["question"]
        assert q["textQuestion"] == {"paragraph": True}

    def test_checkbox_item(self) -> None:
        from google_kit.services.forms.core import forms_add_item
        from google_kit.services.forms.models import FormsAddItemInput

        svc = FormsMockGoogleService(responses={("forms", "batchUpdate"): {}})
        forms_add_item(
            FormsAddItemInput(
                form_id="f1",
                title="Select all",
                item_type="checkbox",
                options="A,B,C",
            ),
            service=svc,
        )
        body = svc.requests_for("forms", "batchUpdate")[0].body
        q = body["requests"][0]["createItem"]["item"]["questionItem"]["question"]
        assert q["choiceQuestion"]["type"] == "CHECKBOX"

    def test_dropdown_item(self) -> None:
        from google_kit.services.forms.core import forms_add_item
        from google_kit.services.forms.models import FormsAddItemInput

        svc = FormsMockGoogleService(responses={("forms", "batchUpdate"): {}})
        forms_add_item(
            FormsAddItemInput(
                form_id="f1",
                title="Choose one",
                item_type="dropdown",
                options="X,Y,Z",
            ),
            service=svc,
        )
        body = svc.requests_for("forms", "batchUpdate")[0].body
        q = body["requests"][0]["createItem"]["item"]["questionItem"]["question"]
        assert q["choiceQuestion"]["type"] == "DROP_DOWN"

    def test_scale_hardcoded_1_5(self) -> None:
        from google_kit.services.forms.core import forms_add_item
        from google_kit.services.forms.models import FormsAddItemInput

        svc = FormsMockGoogleService(responses={("forms", "batchUpdate"): {}})
        forms_add_item(
            FormsAddItemInput(form_id="f1", title="Rate it", item_type="scale"),
            service=svc,
        )
        body = svc.requests_for("forms", "batchUpdate")[0].body
        q = body["requests"][0]["createItem"]["item"]["questionItem"]["question"]
        sq = q["scaleQuestion"]
        assert sq["low"] == 1
        assert sq["high"] == 5
        assert sq["lowLabel"] == "Low"
        assert sq["highLabel"] == "High"


# ─────────────────────────────────────────────────────────────────────────────
#  forms.update
# ─────────────────────────────────────────────────────────────────────────────

class TestFormsUpdate:
    def test_mutation_request_parity_title_and_description(self) -> None:
        from google_kit.services.forms.core import forms_update
        from google_kit.services.forms.models import FormsUpdateInput

        expected_body = _load("update_expected_body.json")

        svc = FormsMockGoogleService(responses={
            ("forms", "batchUpdate"): {"form": {}, "replies": []},
        })

        forms_update(
            FormsUpdateInput(
                form_id="form001",
                title="Updated Survey Title",
                description="Updated description.",
            ),
            service=svc,
        )

        batch_reqs = svc.requests_for("forms", "batchUpdate")
        assert batch_reqs
        parity = compare("mutation-request", expected_body, batch_reqs[0].body)
        assert parity.match, f"update body mismatch:\n{parity.diff}"

    def test_title_only_update_mask(self) -> None:
        from google_kit.services.forms.core import forms_update
        from google_kit.services.forms.models import FormsUpdateInput

        svc = FormsMockGoogleService(responses={("forms", "batchUpdate"): {}})
        forms_update(FormsUpdateInput(form_id="f1", title="New Title"), service=svc)

        body = svc.requests_for("forms", "batchUpdate")[0].body
        req = body["requests"][0]["updateFormInfo"]
        assert req["updateMask"] == "title"
        assert "title" in req["info"]
        assert "description" not in req["info"]

    def test_description_only_update_mask(self) -> None:
        from google_kit.services.forms.core import forms_update
        from google_kit.services.forms.models import FormsUpdateInput

        svc = FormsMockGoogleService(responses={("forms", "batchUpdate"): {}})
        forms_update(FormsUpdateInput(form_id="f1", description="New desc"), service=svc)

        body = svc.requests_for("forms", "batchUpdate")[0].body
        req = body["requests"][0]["updateFormInfo"]
        assert req["updateMask"] == "description"
        assert "description" in req["info"]
        assert "title" not in req["info"]

    def test_no_fields_raises(self) -> None:
        from google_kit.services.forms.core import forms_update
        from google_kit.services.forms.models import FormsUpdateInput

        svc = FormsMockGoogleService(responses={})
        with pytest.raises(ValueError, match="at least one"):
            forms_update(FormsUpdateInput(form_id="f1"), service=svc)

    def test_updated_fields_in_output(self) -> None:
        from google_kit.services.forms.core import forms_update
        from google_kit.services.forms.models import FormsUpdateInput

        svc = FormsMockGoogleService(responses={("forms", "batchUpdate"): {}})
        result = forms_update(
            FormsUpdateInput(form_id="f1", title="T", description="D"),
            service=svc,
        )
        assert set(result.data.updated_fields) == {"title", "description"}


# ─────────────────────────────────────────────────────────────────────────────
#  forms.publish
# ─────────────────────────────────────────────────────────────────────────────

class TestFormsPublish:
    def test_mutation_request_parity(self) -> None:
        """Assert the setPublishSettings request body matches the fixture."""
        from google_kit.services.forms.core import forms_publish
        from google_kit.services.forms.models import FormsPublishInput

        expected_body = _load("publish_expected_body.json")

        svc = FormsMockGoogleService(responses={
            ("forms", "setPublishSettings"): {"publishSettings": {}},
        })

        forms_publish(
            FormsPublishInput(
                form_id="form001",
                publish_settings={"publishState": "PUBLISHED", "isAcceptingResponses": True},
            ),
            service=svc,
        )

        reqs = svc.requests_for("forms", "setPublishSettings")
        assert len(reqs) == 1, "Expected exactly one setPublishSettings call"
        parity = compare("mutation-request", expected_body, reqs[0].body)
        assert parity.match, f"publish body mismatch:\n{parity.diff}"

    def test_form_id_in_request(self) -> None:
        from google_kit.services.forms.core import forms_publish
        from google_kit.services.forms.models import FormsPublishInput

        svc = FormsMockGoogleService(responses={("forms", "setPublishSettings"): {}})
        forms_publish(
            FormsPublishInput(form_id="formXYZ", publish_settings={"publishState": "UNPUBLISHED"}),
            service=svc,
        )
        req = svc.requests_for("forms", "setPublishSettings")[0]
        assert req.kwargs.get("formId") == "formXYZ"

    def test_update_mask_derived_from_keys(self) -> None:
        from google_kit.services.forms.core import forms_publish
        from google_kit.services.forms.models import FormsPublishInput

        svc = FormsMockGoogleService(responses={("forms", "setPublishSettings"): {}})
        forms_publish(
            FormsPublishInput(form_id="f1", publish_settings={"isAcceptingResponses": False}),
            service=svc,
        )
        body = svc.requests_for("forms", "setPublishSettings")[0].body
        assert body["updateMask"] == "isAcceptingResponses"
        assert body["publishSettings"] == {"isAcceptingResponses": False}

    def test_output_envelope(self) -> None:
        from google_kit.services.forms.core import forms_publish
        from google_kit.services.forms.models import FormsPublishInput

        svc = FormsMockGoogleService(responses={("forms", "setPublishSettings"): {}})
        result = forms_publish(
            FormsPublishInput(form_id="f1", publish_settings={"publishState": "PUBLISHED"}),
            service=svc,
        )
        assert result.data.form_id == "f1"
        assert result.data.publish_settings == {"publishState": "PUBLISHED"}


# ─────────────────────────────────────────────────────────────────────────────
#  forms.get_response
# ─────────────────────────────────────────────────────────────────────────────

class TestFormsGetResponse:
    def test_mock_read_parity(self) -> None:
        """Normalized-json parity: single response by id."""
        from google_kit.services.forms.core import forms_get_response
        from google_kit.services.forms.models import FormsGetResponseInput

        response = _load("get_response_response.json")
        expected = _load("get_response_expected.json")

        svc = FormsMockGoogleService(responses={("responses", "get"): response})
        result = forms_get_response(
            FormsGetResponseInput(form_id="form001", response_id="resp001"),
            service=svc,
        )

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"normalized-json mismatch:\n{parity.diff}"

    def test_form_id_and_response_id_passed(self) -> None:
        from google_kit.services.forms.core import forms_get_response
        from google_kit.services.forms.models import FormsGetResponseInput

        svc = FormsMockGoogleService(responses={("responses", "get"): {"responseId": "r1", "answers": {}}})
        forms_get_response(
            FormsGetResponseInput(form_id="formABC", response_id="respXYZ"),
            service=svc,
        )
        req = svc.requests_for("responses", "get")[0]
        assert req.kwargs.get("formId") == "formABC"
        assert req.kwargs.get("responseId") == "respXYZ"

    def test_answer_count(self) -> None:
        from google_kit.services.forms.core import forms_get_response
        from google_kit.services.forms.models import FormsGetResponseInput

        response = _load("get_response_response.json")
        svc = FormsMockGoogleService(responses={("responses", "get"): response})
        result = forms_get_response(
            FormsGetResponseInput(form_id="f", response_id="r"),
            service=svc,
        )
        assert result.data.answer_count == 2

    def test_empty_answers(self) -> None:
        from google_kit.services.forms.core import forms_get_response
        from google_kit.services.forms.models import FormsGetResponseInput

        svc = FormsMockGoogleService(responses={
            ("responses", "get"): {
                "responseId": "r1",
                "createTime": "2025-01-01T00:00:00Z",
                "answers": {},
            }
        })
        result = forms_get_response(
            FormsGetResponseInput(form_id="f", response_id="r1"),
            service=svc,
        )
        assert result.data.answer_count == 0
        assert result.data.answers == []


# ─────────────────────────────────────────────────────────────────────────────
#  forms.list_responses — pagination (§7)
# ─────────────────────────────────────────────────────────────────────────────

class TestFormsListResponsesPagination:
    def test_mock_read_parity_with_next_page_token(self) -> None:
        """Pagination: next_page_token surfaces in output when API returns one."""
        from google_kit.services.forms.core import forms_list_responses
        from google_kit.services.forms.models import FormsListResponsesInput

        response = _load("list_responses_paginated_response.json")
        expected = _load("list_responses_paginated_expected.json")

        svc = FormsMockGoogleService(responses={("responses", "list"): response})
        result = forms_list_responses(
            FormsListResponsesInput(form_id="form001", page_size=1, page_token=None),
            service=svc,
        )

        actual = result.data.model_dump()
        parity = compare("normalized-json", expected, actual)
        assert parity.match, f"paginated normalized-json mismatch:\n{parity.diff}"
        assert result.page is not None
        assert result.page.next_page_token == "token_page2"

    def test_page_size_forwarded(self) -> None:
        from google_kit.services.forms.core import forms_list_responses
        from google_kit.services.forms.models import FormsListResponsesInput

        svc = FormsMockGoogleService(responses={("responses", "list"): {"responses": []}})
        forms_list_responses(
            FormsListResponsesInput(form_id="f", page_size=10),
            service=svc,
        )
        req = svc.requests_for("responses", "list")[0]
        assert req.kwargs.get("pageSize") == 10

    def test_page_token_forwarded(self) -> None:
        from google_kit.services.forms.core import forms_list_responses
        from google_kit.services.forms.models import FormsListResponsesInput

        svc = FormsMockGoogleService(responses={("responses", "list"): {"responses": []}})
        forms_list_responses(
            FormsListResponsesInput(form_id="f", page_token="tok123"),
            service=svc,
        )
        req = svc.requests_for("responses", "list")[0]
        assert req.kwargs.get("pageToken") == "tok123"

    def test_no_next_page_token_when_absent(self) -> None:
        from google_kit.services.forms.core import forms_list_responses
        from google_kit.services.forms.models import FormsListResponsesInput

        svc = FormsMockGoogleService(responses={("responses", "list"): {"responses": []}})
        result = forms_list_responses(FormsListResponsesInput(form_id="f"), service=svc)
        assert result.page is not None
        assert result.page.next_page_token is None

    def test_no_pagination_params_not_forwarded(self) -> None:
        """pageSize and pageToken must NOT appear in kwargs when not supplied."""
        from google_kit.services.forms.core import forms_list_responses
        from google_kit.services.forms.models import FormsListResponsesInput

        svc = FormsMockGoogleService(responses={("responses", "list"): {"responses": []}})
        forms_list_responses(FormsListResponsesInput(form_id="f"), service=svc)
        req = svc.requests_for("responses", "list")[0]
        assert "pageSize" not in req.kwargs
        assert "pageToken" not in req.kwargs


# ─────────────────────────────────────────────────────────────────────────────
#  forms.watches
# ─────────────────────────────────────────────────────────────────────────────

class TestFormsWatches:
    def test_mutation_request_parity(self) -> None:
        """Assert the watches.create request body matches the fixture."""
        from google_kit.services.forms.core import forms_watches
        from google_kit.services.forms.models import FormsWatchesInput

        expected_body = _load("watches_expected_body.json")
        mock_response = _load("watches_response.json")

        svc = FormsMockGoogleService(responses={
            ("watches", "create"): mock_response,
        })

        forms_watches(
            FormsWatchesInput(
                form_id="form001",
                topic_name="projects/my-project/topics/my-forms-topic",
                event_type="RESPONSES",
            ),
            service=svc,
        )

        reqs = svc.requests_for("watches", "create")
        assert len(reqs) == 1, "Expected exactly one watches.create call"
        parity = compare("mutation-request", expected_body, reqs[0].body)
        assert parity.match, f"watches body mismatch:\n{parity.diff}"

    def test_form_id_forwarded(self) -> None:
        from google_kit.services.forms.core import forms_watches
        from google_kit.services.forms.models import FormsWatchesInput

        svc = FormsMockGoogleService(responses={("watches", "create"): {}})
        forms_watches(
            FormsWatchesInput(
                form_id="formXYZ",
                topic_name="projects/p/topics/t",
            ),
            service=svc,
        )
        req = svc.requests_for("watches", "create")[0]
        assert req.kwargs.get("formId") == "formXYZ"

    def test_event_type_default_responses(self) -> None:
        from google_kit.services.forms.core import forms_watches
        from google_kit.services.forms.models import FormsWatchesInput

        svc = FormsMockGoogleService(responses={("watches", "create"): {}})
        forms_watches(
            FormsWatchesInput(form_id="f1", topic_name="projects/p/topics/t"),
            service=svc,
        )
        body = svc.requests_for("watches", "create")[0].body
        assert body["watch"]["eventType"] == "RESPONSES"

    def test_event_type_override_schema(self) -> None:
        from google_kit.services.forms.core import forms_watches
        from google_kit.services.forms.models import FormsWatchesInput

        svc = FormsMockGoogleService(responses={("watches", "create"): {}})
        forms_watches(
            FormsWatchesInput(form_id="f1", topic_name="projects/p/topics/t", event_type="SCHEMA"),
            service=svc,
        )
        body = svc.requests_for("watches", "create")[0].body
        assert body["watch"]["eventType"] == "SCHEMA"

    def test_topic_name_in_body(self) -> None:
        from google_kit.services.forms.core import forms_watches
        from google_kit.services.forms.models import FormsWatchesInput

        svc = FormsMockGoogleService(responses={("watches", "create"): {}})
        forms_watches(
            FormsWatchesInput(
                form_id="f1",
                topic_name="projects/acme/topics/watch-topic",
            ),
            service=svc,
        )
        body = svc.requests_for("watches", "create")[0].body
        assert body["watch"]["target"]["topic"]["topicName"] == "projects/acme/topics/watch-topic"

    def test_output_normalization(self) -> None:
        from google_kit.services.forms.core import forms_watches
        from google_kit.services.forms.models import FormsWatchesInput

        mock_response = _load("watches_response.json")
        svc = FormsMockGoogleService(responses={("watches", "create"): mock_response})

        result = forms_watches(
            FormsWatchesInput(form_id="f1", topic_name="projects/p/topics/t"),
            service=svc,
        )
        assert result.data.watch_id == "watch-abc123"
        assert result.data.state == "ACTIVE"
        assert result.data.event_type == "RESPONSES"
        assert result.data.create_time == "2025-01-01T00:00:00Z"


# ─────────────────────────────────────────────────────────────────────────────
#  Item-type parsing helper
# ─────────────────────────────────────────────────────────────────────────────

class TestParseItemType:
    def test_short_text(self) -> None:
        from google_kit.services.forms.core import _parse_item_type

        item = {"questionItem": {"question": {"textQuestion": {}}}}
        assert _parse_item_type(item) == "short_text"

    def test_paragraph(self) -> None:
        from google_kit.services.forms.core import _parse_item_type

        item = {"questionItem": {"question": {"textQuestion": {"paragraph": True}}}}
        assert _parse_item_type(item) == "paragraph"

    def test_scale(self) -> None:
        from google_kit.services.forms.core import _parse_item_type

        item = {"questionItem": {"question": {"scaleQuestion": {"low": 1, "high": 5}}}}
        assert _parse_item_type(item) == "scale"

    def test_radio(self) -> None:
        from google_kit.services.forms.core import _parse_item_type

        item = {"questionItem": {"question": {"choiceQuestion": {"type": "RADIO"}}}}
        assert _parse_item_type(item) == "multiple_choice"

    def test_checkbox(self) -> None:
        from google_kit.services.forms.core import _parse_item_type

        item = {"questionItem": {"question": {"choiceQuestion": {"type": "CHECKBOX"}}}}
        assert _parse_item_type(item) == "checkbox"

    def test_dropdown(self) -> None:
        from google_kit.services.forms.core import _parse_item_type

        item = {"questionItem": {"question": {"choiceQuestion": {"type": "DROP_DOWN"}}}}
        assert _parse_item_type(item) == "dropdown"

    def test_date(self) -> None:
        from google_kit.services.forms.core import _parse_item_type

        assert _parse_item_type({"questionItem": {"question": {"dateQuestion": {}}}}) == "date"

    def test_time(self) -> None:
        from google_kit.services.forms.core import _parse_item_type

        assert _parse_item_type({"questionItem": {"question": {"timeQuestion": {}}}}) == "time"

    def test_grid(self) -> None:
        from google_kit.services.forms.core import _parse_item_type

        assert _parse_item_type({"questionGroupItem": {}}) == "grid"

    def test_unknown_falls_back_to_text(self) -> None:
        from google_kit.services.forms.core import _parse_item_type

        assert _parse_item_type({}) == "text"


# ─────────────────────────────────────────────────────────────────────────────
#  Registry integration
# ─────────────────────────────────────────────────────────────────────────────

class TestRegistryIntegration:
    def test_all_nine_ops_registered(self) -> None:
        import google_kit.registry as reg

        names = {s.name for s in reg.all_specs()}
        expected = {
            "forms.create",
            "forms.get",
            "forms.list_responses",
            "forms.add_item",
            "forms.update",
            "forms.publish",
            "forms.get_response",
            "forms.watches",
        }
        assert expected.issubset(names), f"Missing ops: {expected - names}"

    def test_postures(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        assert specs["forms.create"].posture == "write"
        assert specs["forms.get"].posture == "read"
        assert specs["forms.list_responses"].posture == "read"
        assert specs["forms.add_item"].posture == "write"
        assert specs["forms.update"].posture == "write"
        assert specs["forms.publish"].posture == "write"
        assert specs["forms.get_response"].posture == "read"
        assert specs["forms.watches"].posture == "write"

    def test_scopes(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        body_scope = "https://www.googleapis.com/auth/forms.body"
        body_readonly = "https://www.googleapis.com/auth/forms.body.readonly"
        responses_scope = "https://www.googleapis.com/auth/forms.responses.readonly"

        assert body_scope in specs["forms.create"].scopes
        # forms.get tightened to forms.body.readonly (gate c).
        assert body_readonly in specs["forms.get"].scopes
        assert responses_scope in specs["forms.list_responses"].scopes
        assert body_scope in specs["forms.add_item"].scopes
        assert body_scope in specs["forms.update"].scopes
        assert body_scope in specs["forms.publish"].scopes
        assert responses_scope in specs["forms.get_response"].scopes

    def test_watches_registry_fields(self) -> None:
        import google_kit.registry as reg

        specs = {s.name: s for s in reg.all_specs()}
        w = specs["forms.watches"]
        assert w.posture == "write"
        assert w.plane == "eventing"
        assert w.capability == "eventing.watch"
        assert w.flag == "GOOGLE_KIT_ENABLE_FORMS_WRITE"
        assert "https://www.googleapis.com/auth/forms.body.readonly" in w.scopes
        assert "https://www.googleapis.com/auth/forms.responses.readonly" in w.scopes
