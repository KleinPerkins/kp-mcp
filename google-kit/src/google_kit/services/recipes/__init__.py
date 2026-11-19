"""Recipes service — first-class composition recipes (architecture brief §4).

Each recipe composes already-covered single-API ops behind the LIFO saga
executor and is exposed as a normal registry op (``recipes.<id>``) so it gets
CLI + MCP surfaces for free. Recipes declare a ``recipe`` id (and populate
``meta.recipe_id`` / ``meta.saga_compensated`` at runtime) and add no new OAuth
scopes — their scope set is the union of the composed ops' scopes.
"""
from __future__ import annotations

from google_kit.registry import OpSpec, register

from .core import (
    BUILD_STYLED_SCOPES,
    BUILD_THEN_SHARE_SCOPES,
    HYDRATE_THEN_REFINE_SCOPES,
    TEMPLATE_MERGE_SCOPES,
    recipe_build_styled,
    recipe_build_then_share,
    recipe_hydrate_then_refine,
    recipe_template_merge,
)
from .models import (
    BuildStyledInput,
    BuildStyledOutput,
    BuildThenShareInput,
    BuildThenShareOutput,
    HydrateThenRefineInput,
    HydrateThenRefineOutput,
    TemplateMergeInput,
    TemplateMergeOutput,
)

#: Per-service F5 write gate (off by default) for the composition recipes. The
#: recipe core fns call the composed ops' core functions directly (bypassing the
#: adapter-layer per-op gate), so each recipe declares its own write gate.
#: Satisfied by the ``GOOGLE_KIT_ENABLE_WRITES`` umbrella. See core/flags.py.
_RECIPES_WRITE_FLAG = "GOOGLE_KIT_ENABLE_RECIPES_WRITE"

register(OpSpec(
    name="recipes.build_styled",
    fn=recipe_build_styled,
    input_model=BuildStyledInput,
    output_model=BuildStyledOutput,
    posture="write",
    scopes=BUILD_STYLED_SCOPES,
    perf={
        "api": "Docs v1 + Drive v3",
        "method": "docs.from_markdown → docs.apply_styles (LIFO saga: drive.trash)",
        "quota": "≈4 calls/run",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Create a Google Doc from Markdown and apply a local style profile",
        "input": {
            "markdown_content": "# Styled Plan\n\nDraft.",
            "title": "Styled Plan",
            "style_profile": "default",
        },
        "cli": "google-kit recipes build-styled --markdown-content '# Styled Plan' --title 'Styled Plan' --style-profile default",
        "notes": "Saga: if style application fails, the created Doc is trashed (LIFO).",
    }],
    capability="doc.build_styled",
    plane="content",
    recipe="build-styled",
    aliases=["create a styled doc", "build styled markdown doc", "draft with my doc style"],
    keywords=["create", "style", "styled", "doc", "markdown", "compose"],
    flag=_RECIPES_WRITE_FLAG,
))

register(OpSpec(
    name="recipes.build_then_share",
    fn=recipe_build_then_share,
    input_model=BuildThenShareInput,
    output_model=BuildThenShareOutput,
    posture="write",
    scopes=BUILD_THEN_SHARE_SCOPES,
    perf={
        "api": "Docs v1 + Drive v3",
        "method": "docs.from_markdown → drive.permissions.create (LIFO saga: drive.trash)",
        "quota": "≈4 calls/run",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Create a styled Doc from Markdown and share it with a teammate",
        "input": {
            "markdown_content": "# Q3 Plan\n\nDraft.",
            "title": "Q3 Plan",
            "share_with": "teammate@example.com",
            "role": "writer",
        },
        "cli": "google-kit recipes build-then-share --markdown-content '# Q3 Plan' --title 'Q3 Plan' --share-with teammate@example.com --role writer",
        "notes": "Saga: if sharing fails the created Doc is trashed (LIFO) and status=rolled_back is returned with meta.saga_compensated=true.",
    }],
    capability="doc.build_and_share",
    plane="content",
    recipe="build-then-share",
    aliases=["create and share a doc", "publish a markdown doc", "draft and share"],
    keywords=["create", "share", "publish", "doc", "markdown", "compose"],
    flag=_RECIPES_WRITE_FLAG,
))

register(OpSpec(
    name="recipes.template_merge",
    fn=recipe_template_merge,
    input_model=TemplateMergeInput,
    output_model=TemplateMergeOutput,
    posture="write",
    scopes=TEMPLATE_MERGE_SCOPES,
    perf={
        "api": "Drive v3 + Docs v1",
        "method": "drive.copy → docs.batchUpdate(replaceAllText) (LIFO saga: drive.trash)",
        "quota": "≈2 calls/run",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Copy a template doc and merge named fields into the copy",
        "input": {
            "template_id": "<template-doc-id>",
            "new_name": "Offer — Jordan",
            "replacements": {"{{name}}": "Jordan", "{{role}}": "Engineer"},
        },
        "cli": "google-kit recipes template-merge --template-id <id> --new-name 'Offer — Jordan' --replacements '{\"{{name}}\":\"Jordan\"}'",
        "notes": "Saga: if the merge fails the copy is trashed (LIFO) and status=rolled_back is returned.",
    }],
    capability="doc.template_merge",
    plane="content",
    recipe="template-merge",
    aliases=["fill in a template", "merge fields into a template", "mail merge a doc"],
    keywords=["template", "merge", "copy", "replace", "fields", "placeholders"],
    flag=_RECIPES_WRITE_FLAG,
))

register(OpSpec(
    name="recipes.hydrate_then_refine",
    fn=recipe_hydrate_then_refine,
    input_model=HydrateThenRefineInput,
    output_model=HydrateThenRefineOutput,
    posture="write",
    scopes=HYDRATE_THEN_REFINE_SCOPES,
    perf={
        "api": "Drive v3 + Docs v1",
        "method": "drive.fetch → docs.batchUpdate",
        "quota": "≈2 calls/run",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Read a Doc for context, then apply a batch of refinement edits",
        "input": {
            "document_id": "<doc-id>",
            "requests": [{"insertText": {"location": {"index": 1}, "text": "Summary\n"}}],
        },
        "cli": "google-kit recipes hydrate-then-refine --document-id <id> --requests '[{\"insertText\":{\"location\":{\"index\":1},\"text\":\"Summary\\n\"}}]'",
        "notes": "Hydrate is read-only (no compensation); refine applies the requests. A refine failure leaves no mutation to roll back.",
    }],
    capability="doc.hydrate_and_refine",
    plane="content",
    recipe="hydrate-then-refine",
    aliases=["read then edit a doc", "refine a document", "update a doc with context"],
    keywords=["hydrate", "refine", "read", "edit", "update", "context"],
    flag=_RECIPES_WRITE_FLAG,
))
