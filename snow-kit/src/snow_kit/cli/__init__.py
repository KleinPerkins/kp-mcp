"""snow-kit CLI — generic dispatcher over the registry (single-core/dual-surface).

Usage:
  snow-kit <svc> <op> [--field value ...]   run an op, print a JSON envelope
  snow-kit --list                           list every registered op
  snow-kit help <plain-English intent>      rank safe operations/workflows
  snow-kit mcp [--read-only]                start the MCP stdio server
  snow-kit setup [options] [--dry-run]      report setup authority requirements
  snow-kit bootstrap [--dry-run]            report registration authority requirements
  snow-kit status                           inspect redacted lifecycle status
  snow-kit doctor [--live]                  verify lifecycle and safe reads
  snow-kit repair                           report repair authority requirements
  snow-kit unregister [--dry-run]           report withdrawal authority requirements
  snow-kit auth <login|status|logout>       browser SSO helpers

Adding an op to the registry makes it available here automatically — no CLI edits.
"""
from __future__ import annotations

import json
import sys
from typing import Any

import snow_kit  # noqa: F401 — triggers service auto-registration
from pydantic import ValidationError as PydanticValidationError

from snow_kit.core.errors import SnowKitError
from snow_kit.core.flags import ensure_enabled
from snow_kit.core.intents import HelpInput, resolve_help
from snow_kit.core.normalize import stable_json
from snow_kit.registry import all_specs, get


def _coerce(value: str) -> Any:
    low = value.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    if value.startswith(("[", "{")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    return value


def _parse_fields(args: list[str]) -> dict[str, Any]:
    """Parse ``--key value`` / ``--flag`` tokens into a dict for model validation."""
    fields: dict[str, Any] = {}
    i = 0
    while i < len(args):
        tok = args[i]
        if tok.startswith("--"):
            key = tok[2:].replace("-", "_")
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                fields[key] = _coerce(args[i + 1])
                i += 2
            else:
                fields[key] = True
                i += 1
        else:
            i += 1
    return fields


def _list_ops() -> int:
    for spec in sorted(all_specs(), key=lambda s: s.name):
        print(f"{spec.name:30} {spec.posture}")
    return 0


def _help(args: list[str]) -> int:
    """Resolve plain-English intent without loading config or invoking an op."""
    words: list[str] = []
    limit = 5
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--limit":
            if index + 1 >= len(args):
                print("error: --limit requires an integer from 1 through 10", file=sys.stderr)
                return 2
            try:
                limit = int(args[index + 1])
            except ValueError:
                print("error: --limit requires an integer from 1 through 10", file=sys.stderr)
                return 2
            index += 2
            continue
        if token.startswith("--limit="):
            try:
                limit = int(token.split("=", 1)[1])
            except ValueError:
                print("error: --limit requires an integer from 1 through 10", file=sys.stderr)
                return 2
            index += 1
            continue
        if token.startswith("--"):
            print(f"error: unknown help option {token!r}", file=sys.stderr)
            return 2
        words.append(token)
        index += 1

    try:
        help_input = HelpInput(intent=" ".join(words), limit=limit)
    except PydanticValidationError as exc:
        detail = "; ".join(
            f"{'.'.join(str(part) for part in error.get('loc', ())) or 'input'}: "
            f"{error.get('msg', 'invalid value')}"
            for error in exc.errors()
        )
        print(f"error: invalid help request: {detail}", file=sys.stderr)
        return 2
    output = resolve_help(help_input.intent, limit=help_input.limit)
    print(stable_json(output.model_dump(mode="json")))
    return 1 if output.status == "no_match" else 0


def _lifecycle(command: str, args: list[str]) -> int:
    """Dispatch registration/status/doctor verbs without printing profile values."""
    from pathlib import Path

    from snow_kit import bootstrap as lifecycle

    dry_run = "--dry-run" in args
    live = "--live" in args
    require_registrations = "--skip-registrations" not in args
    binary: str | None = None
    config_path: Path | None = None
    for option, target in (("--binary", "binary"), ("--config", "config")):
        if option in args:
            index = args.index(option)
            if index + 1 >= len(args):
                print(f"error: {option} requires a value", file=sys.stderr)
                return 2
            if target == "binary":
                binary = args[index + 1]
            else:
                config_path = Path(args[index + 1]).expanduser()

    if command == "setup":
        option_keys = {
            "--user": "SNOW_KIT_USER",
            "--account": "SNOW_KIT_ACCOUNT",
            "--authenticator": "SNOW_KIT_AUTHENTICATOR",
            "--warehouse": "SNOW_KIT_WAREHOUSE",
            "--database": "SNOW_KIT_DATABASE",
            "--schema": "SNOW_KIT_SCHEMA",
            "--role": "SNOW_KIT_ROLE",
            "--permission-spec-path": "SNOW_KIT_PERMISSION_SPEC_PATH",
        }
        values: dict[str, str] = {}
        for option, key in option_keys.items():
            if option in args:
                index = args.index(option)
                if index + 1 >= len(args):
                    print(f"error: {option} requires a value", file=sys.stderr)
                    return 2
                values[key] = args[index + 1]
        context_repo: Path | None = None
        if "--context-repo" in args:
            index = args.index("--context-repo")
            if index + 1 >= len(args):
                print("error: --context-repo requires a value", file=sys.stderr)
                return 2
            context_repo = Path(args[index + 1]).expanduser()
        context_path_indexes = [
            index for index, value in enumerate(args) if value == "--context-path"
        ]
        if any(index + 1 >= len(args) for index in context_path_indexes):
            print("error: --context-path requires a value", file=sys.stderr)
            return 2
        context_paths = tuple(args[index + 1] for index in context_path_indexes)
        context_mode: str | None = None
        if "--context-mode" in args:
            index = args.index("--context-mode")
            if index + 1 >= len(args):
                print("error: --context-mode requires a value", file=sys.stderr)
                return 2
            context_mode = args[index + 1]
        result = lifecycle.setup(
            binary_path=binary,
            config_path=config_path,
            profile_values=values,
            context_repo=context_repo,
            context_paths=context_paths,
            context_mode=context_mode,
            dry_run=dry_run,
        )
    elif command == "bootstrap":
        result = lifecycle.bootstrap(
            binary_path=binary,
            config_path=config_path,
            dry_run=dry_run,
        )
    elif command == "repair":
        result = lifecycle.repair(
            binary_path=binary,
            config_path=config_path,
            dry_run=dry_run,
        )
    elif command == "status":
        result = lifecycle.status(binary_path=binary, config_path=config_path)
    elif command == "doctor":
        result = lifecycle.doctor(
            binary_path=binary,
            config_path=config_path,
            live=live,
            require_registrations=require_registrations,
        )
    elif command == "unregister":
        paths = lifecycle.default_platform_paths()
        result = lifecycle.unregister_all(
            cursor_path=paths["cursor"],
            codex_path=paths["codex"],
            claude_path=paths["claude"],
            dry_run=dry_run,
        )
    else:  # pragma: no cover - caller constrains commands.
        raise AssertionError(command)
    from kp_mcp_bootstrap.registrars import Outcome, Result

    registrations = result.get("registrations", result)
    failed = any(isinstance(value, Result) and value.outcome not in {Outcome.APPLIED, Outcome.NO_CHANGE}
                 for value in registrations.values())
    if "registrations" in result:
        result["registrations"] = {key: value.to_dict() if isinstance(value, Result) else value
                                   for key, value in registrations.items()}
    result = {key: value.to_dict() if isinstance(value, Result) else value for key, value in result.items()}
    print(stable_json(result))
    if command == "doctor" and not result.get("ready", False):
        return 1
    return int(failed or result.get("state") == "registration_incomplete")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--list":
        return _list_ops()
    if argv[0] == "help":
        return _help(argv[1:])
    if argv[0] == "mcp":
        from snow_kit.mcp import main as mcp_main

        mcp_main(argv[1:])
        return 0
    if argv[0] in {"setup", "bootstrap", "status", "doctor", "repair", "unregister"}:
        from kp_mcp_bootstrap.registrars import RegistrarError

        try:
            return _lifecycle(argv[0], argv[1:])
        except RegistrarError as exc:
            print(stable_json({"status": "refused", "reason_codes": [code.value for code in exc.reason_codes],
                               "next_action": "Live registration is blocked until native writer exclusion is qualified; use the separate owner workflow."}), file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001 - lifecycle errors use the shared JSON taxonomy.
            from snow_kit.core.errors import classify_connector

            classified = classify_connector(exc, op=argv[0])
            print(stable_json(classified.to_mcp_payload()), file=sys.stderr)
            return 1
    if argv[0] == "auth":
        from snow_kit.cli.auth import run_auth

        return run_auth(argv[1:])

    if len(argv) < 2:
        print("error: expected '<svc> <op>' (try --list)", file=sys.stderr)
        return 2
    op_name = f"{argv[0]}.{argv[1]}"
    try:
        spec = get(op_name)
    except KeyError:
        print(f"error: unknown op {op_name!r} (try --list)", file=sys.stderr)
        return 2

    inp = spec.input_model.model_validate(_parse_fields(argv[2:]))
    try:
        ensure_enabled(spec)
        result = spec.fn(inp)
    except SnowKitError as exc:
        print(stable_json(exc.to_mcp_payload()), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — surface as a JSON error envelope
        from snow_kit.core.errors import classify_connector

        classified = classify_connector(exc, op=op_name)
        print(stable_json(classified.to_mcp_payload()), file=sys.stderr)
        return 1
    print(stable_json(result.model_dump()))
    return 0
