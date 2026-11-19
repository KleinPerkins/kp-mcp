"""Docgen interface: consumes OpSpecLike registry entries and emits doc artifacts.

Defines the OpSpecLike Protocol so that both the testkit and google-kit's registry
share a single contract without a circular dependency.

Phase 4/5 implement the concrete generators (doc cards, CLI help, MCP schema).
"""

import json
from typing import Any, Callable, Protocol, runtime_checkable

from pydantic import BaseModel, Field


def mcp_tool_name(op_name: str) -> str:
    """Map a dotted OpSpec name to an MCP-valid tool name.

    MCP clients (e.g. Cursor) require tool names to match ``^[a-zA-Z0-9_]+$`` —
    dots are rejected — so the registry's dotted op name (``calendar.create``)
    cannot be used verbatim. This replaces ``.`` with ``_`` (``calendar_create``).

    The mapping is NOT reversible by a naive ``str.replace`` because op segments
    already contain underscores (``gmail.manage_labels`` → ``gmail_manage_labels``;
    a reverse replace would wrongly yield ``gmail.manage.labels``). Callers that
    need the reverse direction must build an explicit forward map and guard it for
    injectivity — see ``google_kit.mcp._build_tool_map``.

    This is the single source of truth for tool-name sanitization shared by the
    MCP server adapter and docgen, so every surface advertises the same name.
    """
    return op_name.replace(".", "_")


@runtime_checkable
class OpSpecLike(Protocol):
    """Minimal protocol consumed by docgen and registry tooling.

    Every entry in a kit's registry must satisfy this interface.
    Full definition lives in google_kit.registry; this protocol is the
    dependency-inversion point so kp-mcp-bootstrap has no google-kit dep.
    """

    name: str
    posture: str
    scopes: list[str]
    perf: dict[str, Any]
    batching: dict[str, Any]
    formatting: dict[str, Any]
    examples: list[Any]
    fn: Callable[..., Any]
    input_model: type[BaseModel]
    output_model: type[BaseModel]


class DocCard(BaseModel):
    """Generated per-capability documentation card."""

    name: str
    posture: str
    scopes: list[str]
    schema_input: dict[str, Any]
    schema_output: dict[str, Any]
    perf: dict[str, Any]
    batching: dict[str, Any]
    formatting: dict[str, Any]
    examples: list[Any]
    errors: list[dict[str, str]] = Field(default_factory=list)
    cli_help: str
    mcp_schema: dict[str, Any]


class Docgen:
    """Generates doc cards, CLI help strings, and MCP tool schemas from an OpSpec."""

    def emit_card(self, spec: OpSpecLike) -> DocCard:
        """Emit a DocCard for a single OpSpec entry."""
        return DocCard(
            name=spec.name,
            posture=spec.posture,
            scopes=spec.scopes,
            schema_input=spec.input_model.model_json_schema(),
            schema_output=spec.output_model.model_json_schema(),
            perf=spec.perf,
            batching=spec.batching,
            formatting=spec.formatting,
            examples=spec.examples,
            errors=getattr(spec, "errors", []),
            cli_help=self.emit_cli_help(spec),
            mcp_schema=self.emit_mcp_schema(spec),
        )

    def emit_cli_help(self, spec: OpSpecLike) -> str:
        """Return the CLI help string for an OpSpec entry."""
        scopes_str = ", ".join(f"`{s}`" for s in spec.scopes)
        lines = [
            f"google-kit {spec.name.replace('.', ' ')}",
            f"Posture: {spec.posture}",
            f"Scopes: {scopes_str}",
        ]
        if spec.examples:
            ex = spec.examples[0]
            lines.append(f"Example: {ex.get('cli', '')}")
        return "\n".join(lines)

    def emit_mcp_schema(self, spec: OpSpecLike) -> dict[str, Any]:
        """Return the MCP tool schema dict for an OpSpec entry.

        ``name`` is the MCP-valid tool name (``mcp_tool_name``), not the dotted
        registry op name, so the schema advertises the name clients must call.
        """
        doc = (spec.fn.__doc__ or "").strip()
        description = doc.splitlines()[0] if doc else ""
        return {
            "name": mcp_tool_name(spec.name),
            "description": description,
            "inputSchema": spec.input_model.model_json_schema(),
            "outputSchema": spec.output_model.model_json_schema(),
        }

    def emit_markdown(self, spec: OpSpecLike) -> str:
        """Render a per-capability markdown doc card."""
        card = self.emit_card(spec)
        props = card.schema_input.get("properties", {})
        required = set(card.schema_input.get("required", []))

        input_rows = []
        for fname, fdef in props.items():
            ftype = fdef.get("type", fdef.get("anyOf", [{}])[0].get("type", "any"))
            req = "Yes" if fname in required else "No"
            desc = fdef.get("description", fdef.get("title", ""))
            default = fdef.get("default", "")
            extra = f" (default: {default!r})" if default != "" else ""
            input_rows.append(f"| `{fname}` | {ftype} | {req} | {desc}{extra} |")

        input_table = "\n".join(
            ["| Field | Type | Required | Description |",
             "|-------|------|----------|-------------|"]
            + (input_rows or ["| — | — | — | — |"])
        )

        # Derive output data fields from the output schema.
        # output_model is always OutputEnvelope[XxxData]; extract the 'data' definition.
        output_rows = self._extract_data_fields(card.schema_output)
        if output_rows:
            output_table = "\n".join(
                ["| Field | Type | Description |",
                 "|-------|------|-------------|"]
                + output_rows
            )
            output_section = f"## Output (`data` fields)\n\n{output_table}\n\n"
        else:
            output_section = ""

        scopes_str = " ".join(f"`{s}`" for s in card.scopes)
        perf_lines = "\n".join(f"- {k}: {v}" for k, v in card.perf.items()) if card.perf else "- Standard"

        if card.errors:
            errors_table = "\n".join(
                [
                    "| Class | When | Retry |",
                    "|-------|------|-------|",
                    *[
                        f"| `{item['class']}` | {item['when']} | {item['retry']} |"
                        for item in card.errors
                    ],
                ]
            )
        else:
            # Preserve the generated contract for kits that have not opted into
            # operation-specific retry metadata.
            errors_table = (
                "| Class | When |\n"
                "|-------|------|\n"
                "| `Auth` | Invalid or expired credentials |\n"
                "| `QuotaRateLimit` | Quota exceeded; retried automatically |\n"
                "| `Transient` | 5xx server error; retried automatically (max 4 attempts) |\n"
                "| `NotFound` | Resource not found |"
            )

        example_block = ""
        if card.examples:
            ex = card.examples[0]
            if "." in card.name:
                svc, op = card.name.split(".", 1)
            else:
                svc, op = "", card.name
            func_name = f"{svc}_{op.replace('.', '_')}"
            model_name = "".join(p.title() for p in (svc + "_" + op.replace(".", "_")).split("_")) + "Input"
            mcp_tool = mcp_tool_name(card.name)
            cli_line = ex.get("cli", f"google-kit {card.name.replace('.', ' ')}")
            mcp_args = ex.get("input", {})
            mcp_json = json.dumps(mcp_args, indent=2) if mcp_args else "{}"
            notes = ex.get("notes", "")
            notes_block = f"\n> **Note:** {notes}" if notes else ""
            example_block = (
                "\n## Example\n\n"
                f"**CLI:** `{cli_line}`\n\n"
                f"**MCP tool:** `{mcp_tool}`\n"
                "```json\n"
                f"{mcp_json}\n"
                "```"
                + notes_block
                + "\n"
            )

        return (
            f"# {card.name}\n\n"
            f"**Posture:** {card.posture}  "
            f"**Scopes:** {scopes_str}\n\n"
            f"## Input\n\n{input_table}\n\n"
            + output_section
            + f"## Performance / Quota\n\n{perf_lines}\n\n"
            f"## Errors\n\n{errors_table}"
            + example_block
            + "\n"
        )

    def _extract_data_fields(self, schema_output: dict[str, Any]) -> list[str]:
        """Extract field rows for the 'data' property of an OutputEnvelope schema.

        OutputEnvelope[XxxData] schemas have 'data' as a $ref to XxxData in $defs.
        Returns an empty list if the schema is not an OutputEnvelope or has no data fields.
        """
        defs = schema_output.get("$defs", {})
        data_prop = schema_output.get("properties", {}).get("data", {})

        # Resolve $ref → definition dict
        if "$ref" in data_prop:
            ref = data_prop["$ref"]  # e.g. "#/$defs/DriveFetchData"
            def_key = ref.split("/")[-1]
            data_def = defs.get(def_key, {})
        else:
            data_def = data_prop

        props = data_def.get("properties", {})
        if not props:
            return []

        required = set(data_def.get("required", []))
        rows = []
        for fname, fdef in props.items():
            # Resolve $ref fields
            if "$ref" in fdef:
                ref_key = fdef["$ref"].split("/")[-1]
                resolved = defs.get(ref_key, fdef)
                ftype = "object"
                desc = resolved.get("description", resolved.get("title", ""))
            elif "anyOf" in fdef:
                non_null = [x for x in fdef["anyOf"] if x.get("type") != "null"]
                ftype = non_null[0].get("type", "any") if non_null else "any"
                desc = fdef.get("description", fdef.get("title", ""))
            else:
                ftype = fdef.get("type", "any")
                desc = fdef.get("description", fdef.get("title", ""))
            rows.append(f"| `{fname}` | {ftype} | {desc} |")
        return rows
