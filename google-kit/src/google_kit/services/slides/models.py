"""Pydantic input / output models for all Slides service operations."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from google_kit.core.normalize import OutputEnvelope


class SlidesCreateInput(BaseModel):
    """Input for ``slides.create``: create a new presentation."""

    title: str
    folder_id: str | None = Field(default=None, description="Drive folder ID to move the presentation into")


class SlidesCreateData(BaseModel):
    """Data payload for ``slides.create``."""

    presentation_id: str
    url: str
    title: str
    slide_count: int


SlidesCreateOutput = OutputEnvelope[SlidesCreateData]


class SlidesGetInput(BaseModel):
    """Input for ``slides.get``: retrieve presentation metadata and slide list."""

    presentation_id: str


class SlideSummary(BaseModel):
    """Summary of one slide in a presentation."""

    object_id: str
    element_count: int
    layout_object_id: str


class SlidesGetData(BaseModel):
    """Data payload for ``slides.get``.

    Note: ``revision_id`` and all ``object_id`` / ``layout_object_id`` values
    are nondeterministic across API calls; excluded from normalized-json parity.
    Semantic refine DEFERRED(P6).
    """

    presentation_id: str
    title: str
    revision_id: str
    url: str
    slide_count: int
    slides: list[SlideSummary]


SlidesGetOutput = OutputEnvelope[SlidesGetData]


class SlidesAddSlideInput(BaseModel):
    """Input for ``slides.add_slide``: add a new slide to a presentation."""

    presentation_id: str
    layout: str = Field(default="BLANK", description="Predefined layout name (e.g. BLANK, TITLE, TITLE_AND_BODY)")
    insert_at: int | None = Field(default=None, description="0-based insertion index; appends if omitted")
    title_text: str | None = Field(default=None, description="Text to insert into the TITLE placeholder")
    body_text: str | None = Field(default=None, description="Text to insert into the BODY placeholder")


class SlidesAddSlideData(BaseModel):
    """Data payload for ``slides.add_slide``."""

    slide_id: str
    presentation_id: str


SlidesAddSlideOutput = OutputEnvelope[SlidesAddSlideData]


class SlidesUpdateTextInput(BaseModel):
    """Input for ``slides.update_text``: replace or insert text in a presentation.

    Two modes (mutually exclusive):
      - Global replace: provide ``find`` + ``replace`` (case-sensitive replaceAllText).
      - Direct insert: provide ``object_id`` + ``text`` (deleteText + insertText on a shape).
    """

    presentation_id: str
    find: str | None = Field(default=None, description="Text to find for global case-sensitive replacement")
    replace: str | None = Field(default=None, description="Replacement text (used with find)")
    object_id: str | None = Field(default=None, description="Shape object ID for direct text update")
    text: str | None = Field(default=None, description="New text content (used with object_id)")


class SlidesUpdateTextData(BaseModel):
    """Data payload for ``slides.update_text``."""

    presentation_id: str
    occurrences_changed: int | None = None


SlidesUpdateTextOutput = OutputEnvelope[SlidesUpdateTextData]


class SlidesAddImageInput(BaseModel):
    """Input for ``slides.add_image``: add an image to a slide from a URL."""

    presentation_id: str
    slide_id: str = Field(description="Object ID of the target slide")
    url: str = Field(description="Publicly accessible image URL")
    x: float = Field(default=1.0, description="X position in inches")
    y: float = Field(default=1.0, description="Y position in inches")
    width: float = Field(default=4.0, description="Width in inches")
    height: float = Field(default=3.0, description="Height in inches")
    object_id: str | None = Field(
        default=None,
        description="Optional stable object ID override (for deterministic tests; auto-generated if omitted)",
    )


class SlidesAddImageData(BaseModel):
    """Data payload for ``slides.add_image``."""

    object_id: str
    presentation_id: str


SlidesAddImageOutput = OutputEnvelope[SlidesAddImageData]


class SlidesThumbnailInput(BaseModel):
    """Input for ``slides.thumbnail``: get the thumbnail image for a single slide page."""

    presentation_id: str
    page_object_id: str
    mime_type: str | None = Field(default=None, description="Thumbnail MIME type (e.g. PNG)")
    thumbnail_size: str | None = Field(default=None, description="Thumbnail size: LARGE, MEDIUM, or SMALL")


class SlidesThumbnailData(BaseModel):
    """Data payload for ``slides.thumbnail``."""

    content_url: str
    width: int
    height: int


SlidesThumbnailOutput = OutputEnvelope[SlidesThumbnailData]
