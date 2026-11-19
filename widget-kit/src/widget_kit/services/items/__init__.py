"""Register the sample ``items`` ops. Copy this directory to add a new service."""
from __future__ import annotations

from widget_kit.registry import OpSpec, register

from .core import items_create, items_list
from .models import (
    ItemsCreateInput,
    ItemsCreateOutput,
    ItemsListInput,
    ItemsListOutput,
)

register(OpSpec(
    name="items.list",
    fn=items_list,
    input_model=ItemsListInput,
    output_model=ItemsListOutput,
    posture="read",
    scopes=["widget-kit:items.read"],
    perf={"api": "Widget", "method": "items.list"},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "List up to 5 items",
        "input": {"limit": 5},
        "cli": "widget-kit items list --limit 5",
    }],
    aliases=["list items", "show items"],
    keywords=["items", "list"],
))

register(OpSpec(
    name="items.create",
    fn=items_create,
    input_model=ItemsCreateInput,
    output_model=ItemsCreateOutput,
    posture="write",
    scopes=["widget-kit:items.write"],
    perf={"api": "Widget", "method": "items.create"},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Create an item named 'demo'",
        "input": {"name": "demo"},
        "cli": "widget-kit items create --name demo",
    }],
    aliases=["create item", "add item"],
    keywords=["items", "create"],
))
