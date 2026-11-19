"""Slides service — registers 6 ops (5 cutover-minimum + slides.thumbnail)."""
from __future__ import annotations

from google_kit.registry import OpSpec, register

from .core import (
    slides_add_image,
    slides_add_slide,
    slides_create,
    slides_get,
    slides_thumbnail,
    slides_update_text,
)
from .models import (
    SlidesAddImageInput,
    SlidesAddImageOutput,
    SlidesAddSlideInput,
    SlidesAddSlideOutput,
    SlidesCreateInput,
    SlidesCreateOutput,
    SlidesGetInput,
    SlidesGetOutput,
    SlidesThumbnailInput,
    SlidesThumbnailOutput,
    SlidesUpdateTextInput,
    SlidesUpdateTextOutput,
)

_SLIDES_SCOPES = [
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive.file",
]

#: Per-service F5 write gate (off by default). Satisfied by the
#: ``GOOGLE_KIT_ENABLE_WRITES`` umbrella. See core/flags.py.
_SLIDES_WRITE_FLAG = "GOOGLE_KIT_ENABLE_SLIDES_WRITE"

register(OpSpec(
    name="slides.create",
    fn=slides_create,
    input_model=SlidesCreateInput,
    output_model=SlidesCreateOutput,
    posture="write",
    scopes=_SLIDES_SCOPES,
    perf={"api": "Slides v1", "method": "presentations.create (+ drive.files.update for folder)", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Create a presentation and move it to a Drive folder",
        "input": {"title": "My Presentation", "folder_id": "<folder-id>"},
        "cli": "google-kit slides create 'My Presentation' --folder-id <folder-id>",
    }],
    aliases=["make a slide deck"],
    flag=_SLIDES_WRITE_FLAG,
))

register(OpSpec(
    name="slides.get",
    fn=slides_get,
    input_model=SlidesGetInput,
    output_model=SlidesGetOutput,
    posture="read",
    scopes=["https://www.googleapis.com/auth/presentations.readonly"],
    perf={"api": "Slides v1", "method": "presentations.get", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Get presentation metadata and slide list",
        "input": {"presentation_id": "<presentation-id>"},
        "cli": "google-kit slides get <presentation-id>",
    }],
))

register(OpSpec(
    name="slides.add_slide",
    fn=slides_add_slide,
    input_model=SlidesAddSlideInput,
    output_model=SlidesAddSlideOutput,
    posture="write",
    scopes=["https://www.googleapis.com/auth/presentations"],
    perf={"api": "Slides v1", "method": "presentations.batchUpdate (createSlide)", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Add a blank slide at the end",
        "input": {"presentation_id": "<presentation-id>", "layout": "BLANK"},
        "cli": "google-kit slides add-slide <presentation-id>",
    }],
    flag=_SLIDES_WRITE_FLAG,
))

register(OpSpec(
    name="slides.update_text",
    fn=slides_update_text,
    input_model=SlidesUpdateTextInput,
    output_model=SlidesUpdateTextOutput,
    posture="write",
    scopes=["https://www.googleapis.com/auth/presentations"],
    perf={"api": "Slides v1", "method": "presentations.batchUpdate (replaceAllText)", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Replace all occurrences of a placeholder string",
        "input": {"presentation_id": "<presentation-id>", "find": "{{TITLE}}", "replace": "My Title"},
        "cli": "google-kit slides update-text <presentation-id> --find '{{TITLE}}' --replace 'My Title'",
    }],
    flag=_SLIDES_WRITE_FLAG,
))

register(OpSpec(
    name="slides.add_image",
    fn=slides_add_image,
    input_model=SlidesAddImageInput,
    output_model=SlidesAddImageOutput,
    posture="write",
    scopes=["https://www.googleapis.com/auth/presentations"],
    perf={"api": "Slides v1", "method": "presentations.batchUpdate (createImage)", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Add an image to a slide at position (1, 1) with size 4x3 inches",
        "input": {
            "presentation_id": "<presentation-id>",
            "slide_id": "<slide-id>",
            "url": "https://example.com/image.jpg",
            "x": 1.0,
            "y": 1.0,
            "width": 4.0,
            "height": 3.0,
        },
        "cli": "google-kit slides add-image <presentation-id> <slide-id> --url https://example.com/image.jpg",
    }],
    aliases=["insert a picture into a slide"],
    keywords=["picture", "photo", "insert"],
    flag=_SLIDES_WRITE_FLAG,
))

register(OpSpec(
    name="slides.thumbnail",
    fn=slides_thumbnail,
    input_model=SlidesThumbnailInput,
    output_model=SlidesThumbnailOutput,
    posture="read",
    scopes=["https://www.googleapis.com/auth/presentations.readonly"],
    capability="slides.pages.getThumbnail",
    perf={"api": "Slides v1", "method": "presentations.pages.getThumbnail", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Get the thumbnail image for a single slide page",
        "input": {
            "presentation_id": "<presentation-id>",
            "page_object_id": "<page-object-id>",
            "thumbnail_size": "LARGE",
        },
        "cli": "google-kit slides thumbnail <presentation-id> <page-object-id> --thumbnail-size LARGE",
    }],
))
