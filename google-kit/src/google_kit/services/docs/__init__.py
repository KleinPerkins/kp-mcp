"""Docs service — registers Docs ops in the google-kit registry."""
from __future__ import annotations

from google_kit.registry import OpSpec, register

from .core import (
    docs_apply_styles,
    docs_batch_update,
    docs_extract_styles,
    docs_from_markdown,
    docs_styles_add,
    docs_styles_apply,
    docs_styles_doctor,
    docs_styles_remove,
    docs_styles_repair,
    docs_styles_set_default,
    docs_styles_update,
    docs_styles_view,
)
from .models import (
    DocsApplyStylesInput,
    DocsApplyStylesOutput,
    DocsBatchUpdateInput,
    DocsBatchUpdateOutput,
    DocsExtractStylesInput,
    DocsExtractStylesOutput,
    DocsFromMarkdownInput,
    DocsFromMarkdownOutput,
    DocsStylesAddInput,
    DocsStylesAddOutput,
    DocsStylesApplyInput,
    DocsStylesDoctorInput,
    DocsStylesDoctorOutput,
    DocsStylesRemoveInput,
    DocsStylesRemoveOutput,
    DocsStylesSetDefaultInput,
    DocsStylesSetDefaultOutput,
    DocsStylesUpdateInput,
    DocsStylesUpdateOutput,
    DocsStylesViewInput,
    DocsStylesViewOutput,
)

_DRIVE_FULL = "https://www.googleapis.com/auth/drive"
_DOCUMENTS = "https://www.googleapis.com/auth/documents"

#: Per-service F5 write gate (off by default). Satisfied by the
#: ``GOOGLE_KIT_ENABLE_WRITES`` umbrella. See core/flags.py.
_DOCS_WRITE_FLAG = "GOOGLE_KIT_ENABLE_DOCS_WRITE"

register(OpSpec(
    name="docs.from_markdown",
    fn=docs_from_markdown,
    input_model=DocsFromMarkdownInput,
    output_model=DocsFromMarkdownOutput,
    posture="write",
    scopes=[_DRIVE_FULL, _DOCUMENTS],
    perf={
        "api": "Drive v3 + Docs v1",
        "method": "files.create (resumable) + documents.get + documents.batchUpdate",
        "quota": "500 req/day",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Convert a Markdown string to a styled Google Doc",
        "input": {
            "markdown_content": "# Hello\n\nWorld.",
            "title": "My Doc",
            "folder_id": "<folder-id>",
        },
        "cli": "google-kit docs from-markdown --markdown-content '# Hello\n\nWorld.' --title 'My Doc' --folder-id <folder-id>",
        "notes": "Formatting contract: headings → H1/H2/H3 styles, bold/italic/code preserved, margins and fonts match the legacy md-to-google-doc workflow defaults.",
    }],
    flag=_DOCS_WRITE_FLAG,
))

register(OpSpec(
    name="docs.extract_styles",
    fn=docs_extract_styles,
    input_model=DocsExtractStylesInput,
    output_model=DocsExtractStylesOutput,
    posture="read",
    scopes=[_DOCUMENTS],
    perf={
        "api": "Docs v1",
        "method": "documents.get(includeTabsContent=true)",
        "quota": "300 req/min/user",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Extract named styles from a source Google Doc and save them locally",
        "input": {"document_id": "<doc-id>", "style_profile": "default"},
        "cli": "google-kit docs extract-styles --document-id <doc-id> --style-profile default",
        "notes": "Local save writes config_dir/doc-styles/<name>.json with private permissions.",
    }],
    plane="content",
    capability="doc.style.extract",
    aliases=["extract doc styles", "save google doc styles", "copy my doc style"],
    keywords=["style", "styles", "extract", "profile", "theme"],
))

register(OpSpec(
    name="docs.apply_styles",
    fn=docs_apply_styles,
    input_model=DocsApplyStylesInput,
    output_model=DocsApplyStylesOutput,
    posture="write",
    scopes=[_DOCUMENTS],
    perf={
        "api": "Docs v1",
        "method": "documents.batchUpdate(updateNamedStyle + updateDocumentStyle)",
        "quota": "300 req/min/user",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Apply a local style profile to an existing Google Doc",
        "input": {"document_id": "<doc-id>", "style_profile": "default", "dry_run": True},
        "cli": "google-kit docs apply-styles --document-id <doc-id> --style-profile default --dry-run true",
        "notes": "Use dry_run=true to preview computed batchUpdate requests without mutating.",
    }],
    plane="content",
    capability="doc.style.apply",
    aliases=["apply doc styles", "restyle a google doc", "make this doc use my style"],
    keywords=["style", "styles", "apply", "profile", "theme"],
    flag=_DOCS_WRITE_FLAG,
))

register(OpSpec(
    name="docs.batch_update",
    fn=docs_batch_update,
    input_model=DocsBatchUpdateInput,
    output_model=DocsBatchUpdateOutput,
    posture="write",
    scopes=[_DOCUMENTS],
    perf={
        "api": "Docs v1",
        "method": "documents.batchUpdate",
        "quota": "300 req/min/user",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Insert text at position 1 in a Google Doc",
        "input": {
            "document_id": "<doc-id>",
            "requests": [{"insertText": {"location": {"index": 1}, "text": "Hello World\n"}}],
        },
        "cli": "google-kit docs batch-update --document-id <doc-id> --requests '[{\"insertText\":{\"location\":{\"index\":1},\"text\":\"Hello World\\n\"}}]'",
        "notes": "Accepts any valid Docs API request object. Multiple request types may be mixed in a single call.",
    }],
    plane="content",
    capability="doc.batch_update",
    aliases=["edit a doc", "modify a google doc", "apply changes to a document"],
    keywords=["edit", "modify"],
    flag=_DOCS_WRITE_FLAG,
))

register(OpSpec(
    name="docs.styles_view",
    fn=docs_styles_view,
    input_model=DocsStylesViewInput,
    output_model=DocsStylesViewOutput,
    posture="read",
    scopes=[_DOCUMENTS],
    perf={"api": "local filesystem", "method": "read config_dir/doc-styles", "quota": "n/a"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "List local style profiles",
        "input": {},
        "cli": "google-kit docs styles-view",
    }],
    plane="content",
    capability="doc.style.manage",
    aliases=["view styles", "list doc styles", "show my style profiles"],
    keywords=["style", "styles", "view", "list", "profile"],
))

register(OpSpec(
    name="docs.styles_add",
    fn=docs_styles_add,
    input_model=DocsStylesAddInput,
    output_model=DocsStylesAddOutput,
    posture="read",
    scopes=[_DOCUMENTS],
    perf={"api": "Docs v1 or local filesystem", "method": "documents.get or starter template", "quota": "300 req/min/user"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Create a local style profile from a source Doc",
        "input": {"style_profile": "default", "document_id": "<doc-id>"},
        "cli": "google-kit docs styles-add --style-profile default --document-id <doc-id>",
    }],
    plane="content",
    capability="doc.style.manage",
    aliases=["add styles", "create a style profile", "save styles"],
    keywords=["style", "styles", "add", "create", "profile"],
))

register(OpSpec(
    name="docs.styles_update",
    fn=docs_styles_update,
    input_model=DocsStylesUpdateInput,
    output_model=DocsStylesUpdateOutput,
    posture="read",
    scopes=[_DOCUMENTS],
    perf={"api": "local filesystem", "method": "merge profile JSON", "quota": "n/a"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Update a local style profile",
        "input": {"style_profile": "default", "updates": {"document_style": {"documentFormat": {"documentMode": "PAGELESS"}}}},
        "cli": "google-kit docs styles-update --style-profile default --updates '{\"document_style\":{\"documentFormat\":{\"documentMode\":\"PAGELESS\"}}}'",
    }],
    plane="content",
    capability="doc.style.manage",
    aliases=["update styles", "edit a style profile", "change my doc style"],
    keywords=["style", "styles", "update", "edit", "profile"],
))

register(OpSpec(
    name="docs.styles_remove",
    fn=docs_styles_remove,
    input_model=DocsStylesRemoveInput,
    output_model=DocsStylesRemoveOutput,
    posture="read",
    scopes=[_DOCUMENTS],
    perf={"api": "local filesystem", "method": "delete profile JSON", "quota": "n/a"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Remove a local style profile",
        "input": {"style_profile": "old"},
        "cli": "google-kit docs styles-remove --style-profile old",
    }],
    plane="content",
    capability="doc.style.manage",
    aliases=["remove styles", "delete a style profile"],
    keywords=["style", "styles", "remove", "delete", "profile"],
))

register(OpSpec(
    name="docs.styles_set_default",
    fn=docs_styles_set_default,
    input_model=DocsStylesSetDefaultInput,
    output_model=DocsStylesSetDefaultOutput,
    posture="read",
    scopes=[_DOCUMENTS],
    perf={"api": "local filesystem", "method": "copy profile to default", "quota": "n/a"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Set a local style profile as the default profile",
        "input": {"style_profile": "team"},
        "cli": "google-kit docs styles-set-default --style-profile team",
    }],
    plane="content",
    capability="doc.style.manage",
    aliases=["set default style", "make this my default doc style"],
    keywords=["style", "styles", "default", "profile"],
))

register(OpSpec(
    name="docs.styles_apply",
    fn=docs_styles_apply,
    input_model=DocsStylesApplyInput,
    output_model=DocsApplyStylesOutput,
    posture="write",
    scopes=[_DOCUMENTS],
    perf={
        "api": "Docs v1",
        "method": "documents.batchUpdate(updateNamedStyle + updateDocumentStyle)",
        "quota": "300 req/min/user",
    },
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Apply a local style profile to a Google Doc",
        "input": {"document_id": "<doc-id>", "style_profile": "default"},
        "cli": "google-kit docs styles-apply --document-id <doc-id> --style-profile default",
    }],
    plane="content",
    capability="doc.style.apply",
    aliases=["styles apply", "apply my style", "restyle this doc"],
    keywords=["style", "styles", "apply", "profile"],
    flag=_DOCS_WRITE_FLAG,
))

register(OpSpec(
    name="docs.styles_doctor",
    fn=docs_styles_doctor,
    input_model=DocsStylesDoctorInput,
    output_model=DocsStylesDoctorOutput,
    posture="read",
    scopes=[_DOCUMENTS],
    perf={"api": "local filesystem", "method": "validate/quarantine/seed profiles", "quota": "n/a"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Validate and repair local style profiles",
        "input": {"seed_default": True},
        "cli": "google-kit docs styles-doctor --seed-default true",
    }],
    plane="content",
    capability="doc.style.manage",
    aliases=["styles doctor", "repair doc styles", "fix style profiles"],
    keywords=["style", "styles", "doctor", "repair", "profile"],
))

register(OpSpec(
    name="docs.styles_repair",
    fn=docs_styles_repair,
    input_model=DocsStylesDoctorInput,
    output_model=DocsStylesDoctorOutput,
    posture="read",
    scopes=[_DOCUMENTS],
    perf={"api": "local filesystem", "method": "validate/quarantine/seed profiles", "quota": "n/a"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "Repair local style profiles",
        "input": {"seed_default": True},
        "cli": "google-kit docs styles-repair --seed-default true",
    }],
    plane="content",
    capability="doc.style.manage",
    aliases=["styles repair", "repair style profiles"],
    keywords=["style", "styles", "repair", "doctor", "profile"],
))
