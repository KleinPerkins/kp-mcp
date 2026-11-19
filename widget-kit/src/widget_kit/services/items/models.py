"""Pydantic models for the sample ``items`` service.

Replace ``items`` with your real service(s). Each op has an Input model and an
``OutputEnvelope[XxxData]`` output model.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from widget_kit.core.normalize import OutputEnvelope


class ItemsListInput(BaseModel):
    """Input for ``items.list``."""

    query: str = Field(default="", description="Optional filter string.")
    limit: int = Field(default=10, description="Maximum number of items to return.")


class Item(BaseModel):
    """One item record."""

    id: str
    name: str


class ItemsListData(BaseModel):
    """Result payload for ``items.list``."""

    items: list[Item] = Field(default_factory=list)
    count: int = 0


ItemsListOutput = OutputEnvelope[ItemsListData]


class ItemsCreateInput(BaseModel):
    """Input for ``items.create``."""

    name: str = Field(description="Name of the item to create.")


class ItemsCreateData(BaseModel):
    """Result payload for ``items.create``."""

    id: str
    name: str


ItemsCreateOutput = OutputEnvelope[ItemsCreateData]
