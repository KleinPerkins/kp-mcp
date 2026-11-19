"""Core functions for the Slides service (cutover-minimum: 5 ops + slides_thumbnail).

Parity coverage per op:

  slides_create      — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  slides_get         — mock-read DONE; semantic refine DEFERRED(P6)
  slides_add_slide   — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  slides_update_text — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  slides_add_image   — mutation-request DONE; sandbox-e2e DEFERRED(P6)
  slides_thumbnail   — mock-read DONE; sandbox-e2e DEFERRED(P6)

Legacy quirks preserved:
  - slides_create: folder move is a separate drive.files().update() call with
    addParents/removeParents="root" (matching legacy cmd_create).
  - slides_add_slide: GET-then-batchUpdate for title/body placeholder text insertion;
    placeholder lookup by type ("TITLE" / "BODY") per legacy _insert_text_on_slide.
  - slides_update_text: replaceAllText uses matchCase=True always (per legacy).
    Direct mode sends deleteText then insertText on the same objectId.
  - slides_add_image: inches → EMU via int(inches * 914400); objectId is a
    client-side UUID override-injectable via SlidesAddImageInput.object_id.
  - slides_get: revisionId and all objectId values are nondeterministic;
    normalized-json compare strips them (semantic refine DEFERRED(P6)).
"""
from __future__ import annotations

import uuid
from typing import Any

from google_kit.core.client import execute_api_call
from google_kit.core.errors import Validation
from google_kit.core.normalize import Meta, OutputEnvelope

from .models import (
    SlidesAddImageData,
    SlidesAddImageInput,
    SlidesAddImageOutput,
    SlidesAddSlideData,
    SlidesAddSlideInput,
    SlidesAddSlideOutput,
    SlidesCreateData,
    SlidesCreateInput,
    SlidesCreateOutput,
    SlidesGetData,
    SlidesGetInput,
    SlidesGetOutput,
    SlidesThumbnailData,
    SlidesThumbnailInput,
    SlidesThumbnailOutput,
    SlidesUpdateTextData,
    SlidesUpdateTextInput,
    SlidesUpdateTextOutput,
    SlideSummary,
)

_EMU_PER_INCH: int = 914400

_PREDEFINED_LAYOUTS: frozenset[str] = frozenset({
    "BLANK", "CAPTION_ONLY", "TITLE", "TITLE_AND_BODY",
    "TITLE_AND_TWO_COLUMNS", "TITLE_ONLY", "SECTION_HEADER",
    "SECTION_TITLE_AND_DESCRIPTION", "ONE_COLUMN_TEXT",
    "MAIN_POINT", "BIG_NUMBER",
})


def _wrap(data: Any, op: str) -> OutputEnvelope[Any]:
    return OutputEnvelope(data=data, meta=Meta(op=op))


def _find_placeholder(pres: dict[str, Any], slide_id: str, placeholder_type: str) -> str | None:
    """Return the objectId of the first placeholder of the given type on slide_id, or None."""
    for slide in pres.get("slides", []):
        if slide.get("objectId") != slide_id:
            continue
        for elem in slide.get("pageElements", []):
            shape = elem.get("shape", {})
            ph = shape.get("placeholder", {})
            if ph.get("type") == placeholder_type:
                return elem.get("objectId")
    return None


def _insert_text_on_slide(
    service: Any,
    pres_id: str,
    slide_id: str,
    text: str,
    placeholder_type: str,
) -> None:
    """GET the presentation to find the placeholder objectId, then insertText.

    Matches legacy _insert_text_on_slide: silently no-ops if placeholder not found.
    """
    pres = execute_api_call(
        lambda: service.presentations().get(presentationId=pres_id).execute(),
        op="slides.add_slide.get",
        posture="read",
    )
    target_id = _find_placeholder(pres or {}, slide_id, placeholder_type)
    if not target_id:
        return
    execute_api_call(
        lambda: service.presentations().batchUpdate(
            presentationId=pres_id,
            body={"requests": [{"insertText": {
                "objectId": target_id,
                "text": text,
                "insertionIndex": 0,
            }}]},
        ).execute(),
        op="slides.add_slide.insert_text",
        posture="write",
        normalized_request={
            "presentation_id": pres_id,
            "slide_id": slide_id,
            "placeholder_type": placeholder_type,
        },
        target_ids=[pres_id],
    )


def slides_create(
    inp: SlidesCreateInput,
    *,
    service: Any = None,
    drive_service: Any = None,
) -> SlidesCreateOutput:
    """Create a new Google Slides presentation; optionally move it to a Drive folder.

    Folder move is a separate drive.files().update() call (matching legacy behaviour).

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    body: dict[str, Any] = {"title": inp.title}
    created = execute_api_call(
        lambda: service.presentations().create(body=body).execute(),
        op="slides.create",
        posture="write",
        normalized_request=inp.model_dump(),
    )
    created = created or {}
    pres_id: str = created.get("presentationId", "")

    if inp.folder_id and drive_service is not None and pres_id:
        execute_api_call(
            lambda: drive_service.files().update(
                fileId=pres_id,
                addParents=inp.folder_id,
                removeParents="root",
                fields="id,parents",
            ).execute(),
            op="slides.create.folder_move",
            posture="write",
            normalized_request={"presentation_id": pres_id, "folder_id": inp.folder_id},
            target_ids=[pres_id],
        )

    url = f"https://docs.google.com/presentation/d/{pres_id}/edit"
    return _wrap(
        SlidesCreateData(
            presentation_id=pres_id,
            url=url,
            title=created.get("title", inp.title),
            slide_count=len(created.get("slides", [])),
        ),
        "slides.create",
    )


def slides_get(
    inp: SlidesGetInput,
    *,
    service: Any = None,
) -> SlidesGetOutput:
    """Retrieve presentation metadata and a slide summary list.

    Note: revisionId and all objectId values are nondeterministic across API calls.
    Normalized-json compare strips them. Semantic refine DEFERRED(P6).

    Parity: mock-read DONE; semantic refine DEFERRED(P6)
    """
    raw = execute_api_call(
        lambda: service.presentations().get(presentationId=inp.presentation_id).execute(),
        op="slides.get",
        posture="read",
    )
    raw = raw or {}
    pres_id: str = raw.get("presentationId", inp.presentation_id)
    slides_raw = raw.get("slides", [])
    slides = [
        SlideSummary(
            object_id=s.get("objectId", ""),
            element_count=len(s.get("pageElements", [])),
            layout_object_id=s.get("slideProperties", {}).get("layoutObjectId", ""),
        )
        for s in slides_raw
    ]
    return _wrap(
        SlidesGetData(
            presentation_id=pres_id,
            title=raw.get("title", ""),
            revision_id=raw.get("revisionId", ""),
            url=f"https://docs.google.com/presentation/d/{pres_id}/edit",
            slide_count=len(slides),
            slides=slides,
        ),
        "slides.get",
    )


def slides_add_slide(
    inp: SlidesAddSlideInput,
    *,
    service: Any = None,
) -> SlidesAddSlideOutput:
    """Add a new slide to an existing presentation.

    Layout defaults to BLANK. Optional title_text / body_text trigger a
    GET-then-insertText call to populate placeholder shapes per legacy behaviour.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    slide_request: dict[str, Any] = {}
    layout_upper = inp.layout.upper() if inp.layout else "BLANK"
    if layout_upper in _PREDEFINED_LAYOUTS:
        slide_request["slideLayoutReference"] = {"predefinedLayout": layout_upper}
    if inp.insert_at is not None:
        slide_request["insertionIndex"] = inp.insert_at

    result = execute_api_call(
        lambda: service.presentations().batchUpdate(
            presentationId=inp.presentation_id,
            body={"requests": [{"createSlide": slide_request}]},
        ).execute(),
        op="slides.add_slide",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.presentation_id],
    )
    replies = (result or {}).get("replies", [{}])
    new_slide_id: str = (replies[0] if replies else {}).get("createSlide", {}).get("objectId", "")

    if inp.title_text and new_slide_id:
        _insert_text_on_slide(service, inp.presentation_id, new_slide_id, inp.title_text, "TITLE")
    if inp.body_text and new_slide_id:
        _insert_text_on_slide(service, inp.presentation_id, new_slide_id, inp.body_text, "BODY")

    return _wrap(
        SlidesAddSlideData(slide_id=new_slide_id, presentation_id=inp.presentation_id),
        "slides.add_slide",
    )


def slides_update_text(
    inp: SlidesUpdateTextInput,
    *,
    service: Any = None,
) -> SlidesUpdateTextOutput:
    """Replace or insert text in a presentation.

    Two modes (matching legacy cmd_update_text):
      - Global replace: find + replace → replaceAllText with matchCase=True.
      - Direct insert: object_id + text → deleteText then insertText.

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    requests_list: list[dict[str, Any]] = []
    use_replace_all = inp.find is not None and inp.replace is not None
    use_direct = inp.object_id is not None and inp.text is not None

    if not use_replace_all and not use_direct:
        raise Validation(
            "slides.update_text requires either (find + replace) or (object_id + text)",
            op="slides.update_text",
        )

    occurrences_changed: int | None = None

    if use_replace_all:
        requests_list.append({
            "replaceAllText": {
                "containsText": {"text": inp.find, "matchCase": True},
                "replaceText": inp.replace,
            }
        })
    else:
        requests_list.append({"deleteText": {
            "objectId": inp.object_id,
            "textRange": {"type": "ALL"},
        }})
        requests_list.append({"insertText": {
            "objectId": inp.object_id,
            "text": inp.text,
            "insertionIndex": 0,
        }})

    result = execute_api_call(
        lambda: service.presentations().batchUpdate(
            presentationId=inp.presentation_id,
            body={"requests": requests_list},
        ).execute(),
        op="slides.update_text",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.presentation_id],
    )

    if use_replace_all:
        replies = (result or {}).get("replies", [])
        occurrences_changed = (replies[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
                               if replies else 0)

    return _wrap(
        SlidesUpdateTextData(
            presentation_id=inp.presentation_id,
            occurrences_changed=occurrences_changed,
        ),
        "slides.update_text",
    )


def slides_add_image(
    inp: SlidesAddImageInput,
    *,
    service: Any = None,
) -> SlidesAddImageOutput:
    """Add an image to a slide from a publicly accessible URL.

    Position and size use inches → EMU conversion (1 inch = 914400 EMU), matching legacy.
    The objectId is client-side generated (injectable via inp.object_id for deterministic tests).

    Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
    """
    obj_id = inp.object_id or f"image_{uuid.uuid4().hex[:8]}"

    emu_x = int(inp.x * _EMU_PER_INCH)
    emu_y = int(inp.y * _EMU_PER_INCH)
    emu_w = int(inp.width * _EMU_PER_INCH)
    emu_h = int(inp.height * _EMU_PER_INCH)

    request: dict[str, Any] = {
        "createImage": {
            "objectId": obj_id,
            "url": inp.url,
            "elementProperties": {
                "pageObjectId": inp.slide_id,
                "size": {
                    "width": {"magnitude": emu_w, "unit": "EMU"},
                    "height": {"magnitude": emu_h, "unit": "EMU"},
                },
                "transform": {
                    "scaleX": 1,
                    "scaleY": 1,
                    "translateX": emu_x,
                    "translateY": emu_y,
                    "unit": "EMU",
                },
            },
        }
    }

    execute_api_call(
        lambda: service.presentations().batchUpdate(
            presentationId=inp.presentation_id,
            body={"requests": [request]},
        ).execute(),
        op="slides.add_image",
        posture="write",
        normalized_request=inp.model_dump(),
        target_ids=[inp.presentation_id],
    )

    return _wrap(
        SlidesAddImageData(object_id=obj_id, presentation_id=inp.presentation_id),
        "slides.add_image",
    )


def slides_thumbnail(
    inp: SlidesThumbnailInput,
    *,
    service: Any = None,
) -> SlidesThumbnailOutput:
    """Get a thumbnail image URL for a single slide page.

    Passes thumbnailProperties_mimeType / thumbnailProperties_thumbnailSize only
    when the caller supplies them (matching google-api-python-client kwarg style).

    Parity: mock-read DONE; sandbox-e2e live-PASS 2026-06-17
    """
    call_kwargs: dict[str, Any] = {
        "presentationId": inp.presentation_id,
        "pageObjectId": inp.page_object_id,
    }
    if inp.mime_type is not None:
        call_kwargs["thumbnailProperties_mimeType"] = inp.mime_type
    if inp.thumbnail_size is not None:
        call_kwargs["thumbnailProperties_thumbnailSize"] = inp.thumbnail_size

    raw = execute_api_call(
        lambda: service.presentations().pages().getThumbnail(**call_kwargs).execute(),
        op="slides.thumbnail",
        posture="read",
    )
    raw = raw or {}
    return _wrap(
        SlidesThumbnailData(
            content_url=raw.get("contentUrl", ""),
            width=raw.get("width", 0),
            height=raw.get("height", 0),
        ),
        "slides.thumbnail",
    )
