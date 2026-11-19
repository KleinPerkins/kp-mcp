"""google-kit CLI adapter — thin generic wrapper over the registry.

Entry point:  google-kit <service> <op> [--field value ...] [--format json|text]
Special mode: google-kit mcp  — starts the MCP stdio server

Derivation from the registry is fully generic: adding an OpSpec automatically
adds a CLI subcommand without any adapter edits (R2).

The ``service=`` injection seam on every core function is preserved — tests
pass ``_service_factory`` to bypass Keychain auth entirely.
"""
from __future__ import annotations

import argparse
import inspect
import json
import sys
from typing import Any, Callable

import google_kit  # noqa: F401 — triggers service auto-registration
from pydantic import ValidationError as PydanticValidationError

from google_kit.core.errors import GoogleKitError, Validation
from google_kit.core.flags import ensure_enabled
from google_kit.core.normalize import OutputEnvelope, stable_json
from google_kit.core.run_id import new_run_id, reset_run_id, set_run_id
from google_kit.registry import all_specs, get

_GLOBAL_OPTIONS_WITH_VALUE = {"--format", "--profile", "--personal-context", "--personal-context-sha256"}


def _first_line(doc: str | None) -> str:
    if not doc:
        return ""
    return doc.strip().splitlines()[0]


def _schema_to_argparse(parser: argparse.ArgumentParser, schema: dict[str, Any]) -> None:
    """Add --flag arguments to parser derived from a pydantic JSON schema."""
    props = schema.get("properties", {})
    required_fields = set(schema.get("required", []))

    for field_name, fdef in props.items():
        flag = f"--{field_name.replace('_', '-')}"
        help_text = fdef.get("description", fdef.get("title", field_name))
        default = fdef.get("default", None)
        required = field_name in required_fields

        raw_type = fdef.get("type")
        if raw_type is None and "anyOf" in fdef:
            non_null = [x for x in fdef["anyOf"] if x.get("type") != "null"]
            raw_type = non_null[0].get("type") if non_null else "string"

        if raw_type == "integer":
            parser.add_argument(
                flag, default=default, type=int,
                help=help_text, dest=field_name, required=required,
            )
        elif raw_type == "number":
            parser.add_argument(
                flag, default=default, type=float,
                help=help_text, dest=field_name, required=required,
            )
        elif _is_jsonish_schema_field(fdef):
            parser.add_argument(
                flag, default=None, metavar="JSON",
                help=f"{help_text} (JSON string)", dest=field_name, required=required,
            )
        else:
            parser.add_argument(
                flag, default=default,
                help=help_text, dest=field_name, required=required,
            )


def _is_jsonish_schema_field(fdef: dict[str, Any]) -> bool:
    """Return True when a CLI field should be decoded from a JSON string."""
    if fdef.get("type") in ("array", "object"):
        return True
    if "$ref" in fdef:
        return True
    for branch in fdef.get("anyOf", []):
        if branch.get("type") in ("array", "object") or "$ref" in branch:
            return True
    return False


def _normalize_global_options(argv: list[str]) -> list[str]:
    """Allow global CLI flags before or after subcommands.

    ``argparse`` only accepts top-level options before the first positional by
    default, but operators naturally try ``google-kit help ... --format text``.
    Move known global options to the front before parsing so both forms work.
    """
    global_args: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        matched_inline = next(
            (opt for opt in _GLOBAL_OPTIONS_WITH_VALUE if arg.startswith(f"{opt}=")),
            None,
        )
        if matched_inline:
            global_args.append(arg)
            i += 1
        elif arg in _GLOBAL_OPTIONS_WITH_VALUE and i + 1 < len(argv):
            global_args.extend([arg, argv[i + 1]])
            i += 2
        else:
            rest.append(arg)
            i += 1
    return global_args + rest


def _json_flag_example(fdef: dict[str, Any]) -> str:
    raw_type = fdef.get("type")
    if raw_type is None and "anyOf" in fdef:
        non_null = [x for x in fdef["anyOf"] if x.get("type") != "null"]
        raw_type = non_null[0].get("type") if non_null else "object"
    if raw_type == "array":
        return "'[\"value\"]'"
    if raw_type == "object":
        return "'{\"key\":\"value\"}'"
    return "valid JSON"


def _format_pydantic_validation_error(spec: Any, exc: PydanticValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()) if part != "__root__")
        flag = f"--{loc.replace('_', '-')}" if loc else "input"
        parts.append(f"{flag}: {err.get('msg', 'invalid value')}")
    detail = "; ".join(parts) or "invalid input"
    return f"Invalid arguments for {spec.name}: {detail}"


def _coerce_argv_to_model(spec: Any, namespace: argparse.Namespace) -> Any:
    """Build and validate the input model from a parsed argparse Namespace."""
    schema = spec.input_model.model_json_schema()
    props = schema.get("properties", {})
    raw: dict[str, Any] = {}

    for field_name, fdef in props.items():
        val = getattr(namespace, field_name, None)
        if val is None:
            continue

        raw_type = fdef.get("type")
        if raw_type is None and "anyOf" in fdef:
            non_null = [x for x in fdef["anyOf"] if x.get("type") != "null"]
            raw_type = non_null[0].get("type") if non_null else "string"

        if _is_jsonish_schema_field(fdef) and isinstance(val, str):
            try:
                val = json.loads(val)
            except json.JSONDecodeError as exc:
                flag = f"--{field_name.replace('_', '-')}"
                raise Validation(
                    f"Invalid JSON for {flag}: expected {_json_flag_example(fdef)}; "
                    f"{exc.msg}.",
                    op=spec.name,
                ) from exc
        elif raw_type == "boolean" and isinstance(val, str):
            val = val.strip().lower() in ("1", "true", "yes", "on")

        raw[field_name] = val

    try:
        return spec.input_model.model_validate(raw)
    except PydanticValidationError as exc:
        raise Validation(_format_pydantic_validation_error(spec, exc), op=spec.name) from exc


def _print_envelope(envelope: OutputEnvelope, *, fmt: str) -> None:
    """Print OutputEnvelope to stdout in the requested format."""
    if fmt == "text":
        data = envelope.data
        if hasattr(data, "model_dump"):
            print(stable_json(data.model_dump()))
        else:
            print(str(data))
    else:
        print(stable_json(envelope.model_dump()))


def _cli_form(op: str) -> str:
    """Render an op name as its CLI invocation form (``svc op-slug``)."""
    svc, _, rest = op.partition(".")
    return f"{svc} {rest.replace('_', '-')}"


def cmd_help(intent: str, *, limit: int = 5, fmt: str = "json") -> int:
    """Resolve a natural-language *intent* to matching ops (E6 how-do-I helper)."""
    from google_kit.core.manifest import resolve_intent
    from google_kit.registry import get

    if not intent.strip():
        print("usage: google-kit help <intent words>", file=sys.stderr)
        return 1

    matches = resolve_intent(intent, limit=limit)
    if not matches:
        print(f"no operations matched {intent!r}.", file=sys.stderr)
        return 1

    if fmt == "text":
        for m in matches:
            spec = get(m.op)
            print(f"google-kit {_cli_form(m.op):28} — {_first_line(spec.fn.__doc__)}")
        return 0

    rows = [
        {
            "op": m.op,
            "cli": f"google-kit {_cli_form(m.op)}",
            "summary": _first_line(get(m.op).fn.__doc__),
            "score": m.score,
            "matched": list(m.matched),
        }
        for m in matches
    ]
    print(stable_json({"intent": intent, "matches": rows}))
    return 0


def _bootstrap_outcome(action: str, value: Any) -> str:
    """Render one platform's bootstrap result for ``--format text``."""
    if isinstance(value, bool):
        if action == "unregister":
            return "removed" if value else "already-absent"
        return "changed" if value else "already-up-to-date"
    return str(value)


def cmd_bootstrap(*, dry_run: bool = False, remove: bool = False, fmt: str = "json") -> int:
    """Report explicit registration results or a bounded missing-authority refusal."""
    import google_kit.bootstrap as gk_bootstrap

    from kp_mcp_bootstrap.registrars import Outcome, RegistrarError, Result

    try:
        if remove:
            paths = gk_bootstrap.default_platform_paths()
            result = gk_bootstrap.unregister_all(
                cursor_path=paths["cursor"],
                codex_path=paths["codex"],
                claude_path=paths["claude"], dry_run=dry_run,
            )
            action = "unregister"
        else:
            result = gk_bootstrap.bootstrap(dry_run=dry_run)
            action = "dry-run" if dry_run else "register"
    except RegistrarError as exc:
        print(stable_json({"status": "refused", "reason_codes": [code.value for code in exc.reason_codes],
                           "next_action": "Live registration is blocked until native writer exclusion is qualified; use the separate owner workflow."}), file=sys.stderr)
        return 1
    failed = any(isinstance(value, Result) and value.outcome not in {Outcome.APPLIED, Outcome.NO_CHANGE}
                 for value in result.values())
    result = {key: value.to_dict() if hasattr(value, "to_dict") else value for key, value in result.items()}

    if fmt == "text":
        for platform in ("cursor", "codex", "claude"):
            print(f"{platform}: {_bootstrap_outcome(action, result.get(platform))}")
    else:
        payload: dict[str, Any] = {
            "action": action,
            "platforms": {platform: result.get(platform) for platform in ("cursor", "codex", "claude")},
        }
        if "doc_styles" in result:
            payload["doc_styles"] = result["doc_styles"]
        print(stable_json(payload))
    return int(failed)


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser from the registry (generic over all specs)."""
    top = argparse.ArgumentParser(
        allow_abbrev=False,  # Subcommands own --personal; never consume it as a global prefix.
        prog="google-kit",
        description="google-kit: Google Workspace toolkit. "
                    "Use 'google-kit mcp' to start the MCP stdio server.",
    )
    top.add_argument(
        "--format", choices=["json", "text"], default="json",
        help="Output format (default: json).",
    )
    top.add_argument(
        "--profile", default=None,
        help="Keychain profile (default: GOOGLE_KIT_PROFILE env var or 'default').",
    )

    top.add_argument("--personal-context", help="Exact reviewed personal consumer context file; no legacy defaults.")
    top.add_argument("--personal-context-sha256", help="SHA-256 of the reviewed personal context file.")
    svc_subs = top.add_subparsers(dest="service", metavar="SERVICE")

    svc_subs.add_parser("mcp", help="Start the MCP stdio server.")

    help_p = svc_subs.add_parser(
        "help", help="Resolve a natural-language intent to matching operations."
    )
    help_p.add_argument(
        "intent", nargs="*", help="Intent words, e.g. send an email (quotes optional)."
    )
    help_p.add_argument(
        "--limit", type=int, default=5, help="Max matches to show (default: 5)."
    )

    _add_auth_parser(svc_subs)
    _add_bootstrap_parser(svc_subs)

    by_service: dict[str, list[Any]] = {}
    for spec in sorted(all_specs(), key=lambda s: s.name):
        svc = spec.name.split(".")[0]
        by_service.setdefault(svc, []).append(spec)

    for svc, specs in sorted(by_service.items()):
        svc_parser = svc_subs.add_parser(svc, help=f"{svc} service operations.")
        op_subs = svc_parser.add_subparsers(dest="op", metavar="OP")

        for spec in specs:
            op_slug = spec.name.split(".", 1)[1].replace("_", "-")
            op_parser = op_subs.add_parser(
                op_slug,
                help=_first_line(spec.fn.__doc__),
            )
            _schema_to_argparse(op_parser, spec.input_model.model_json_schema())

    return top


def _add_auth_parser(svc_subs: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the 'auth' subcommand: login/status/logout + write-authorization
    management (grant/revoke/authorizations)."""
    auth_parser = svc_subs.add_parser(
        "auth",
        help="Manage OAuth credentials + per-profile write authorization "
             "(login/status/logout/grant/revoke/authorizations/inspect).",
    )
    auth_subs = auth_parser.add_subparsers(dest="auth_cmd", metavar="CMD")

    login_p = auth_subs.add_parser("login", help="Run the PKCE OAuth flow and persist tokens.")
    login_p.add_argument("--profile", default=argparse.SUPPRESS, dest="profile",
                         help="Keychain profile override.")
    login_p.add_argument("--force", action="store_true", default=False,
                         help="Re-consent even if a token already exists.")
    login_p.add_argument("--headless", action="store_true", default=False,
                         help="Print auth URL to stderr instead of opening a browser.")
    login_p.add_argument('--personal', action='store_true', default=False,
                         help='Enroll one explicitly reviewed fresh personal profile; verify identity before create-only persistence.')
    login_p.add_argument('--expected-email')
    login_p.add_argument('--expected-subject')
    login_p.add_argument('--expected-client-id')
    login_p.add_argument('--expected-project-id')
    login_p.add_argument('--client-secret-file', dest='client_file')
    login_p.add_argument('--client-file-sha256')
    login_p.add_argument('--config-dir')
    login_p.add_argument('--inventory-sha256')
    login_p.add_argument('--personal-scope', action='append', dest='personal_scopes',
                         help='One exact reviewed scope; repeat for the complete personal request. No union or ambient additions.')
    login_p.add_argument(
        "--scopes", action="append", default=None, dest="extra_scopes", metavar="SCOPE",
        help="Extra OAuth scope URL(s) to request for THIS login only, unioned with the "
             "shared GOOGLE_KIT_SCOPES (comma/space separated; repeatable). Alternatively "
             "set GOOGLE_KIT_EXTRA_SCOPES. Use for sandbox new-API consent; does NOT change "
             "the shared union.",
    )

    status_p = auth_subs.add_parser("status", help="Report Keychain key presence for the profile.")
    status_p.add_argument("--profile", default=argparse.SUPPRESS, dest="profile",
                          help="Keychain profile override.")

    logout_p = auth_subs.add_parser("logout", help="Delete tokens (and credentials) from Keychain.")
    logout_p.add_argument("--profile", default=argparse.SUPPRESS, dest="profile",
                          help="Keychain profile override.")
    logout_p.add_argument("--all", action="store_true", default=False, dest="all_keys",
                          help="Also delete client_id and client_secret.")

    grant_p = auth_subs.add_parser(
        "grant", help="Authorize a write op (1) for the profile (e.g. gmail.send).")
    grant_p.add_argument("op", help="Op name to authorize, e.g. 'gmail.send'.")
    grant_p.add_argument("--profile", default=argparse.SUPPRESS, dest="profile",
                         help="Keychain profile override.")

    revoke_p = auth_subs.add_parser(
        "revoke", help="De-authorize a write op (0) for the profile.")
    revoke_p.add_argument("op", help="Op name to revoke, e.g. 'gmail.send'.")
    revoke_p.add_argument("--profile", default=argparse.SUPPRESS, dest="profile",
                          help="Keychain profile override.")

    authz_p = auth_subs.add_parser(
        "authorizations", help="List per-tool write authorization (1/0) for the profile.")
    authz_p.add_argument("--profile", default=argparse.SUPPRESS, dest="profile",
                         help="Keychain profile override.")

    inspect_p = auth_subs.add_parser(
        'inspect', help='Read-only explicit personal identity/scope/authorization diagnostics; never refresh or authorize.')
    inspect_p.add_argument('--profile', default=argparse.SUPPRESS, dest='profile',
                           help='Explicit selected profile; no ambient/default fallback.')
    inspect_p.add_argument('--expected-email', required=True)
    inspect_p.add_argument('--expected-subject', required=True)
    inspect_p.add_argument('--expected-client-id', required=True,
                           help='Independently reviewed OAuth client ID; ownership is a separate prerequisite.')
    inspect_p.add_argument('--config-dir', required=True,
                           help='Explicit absolute config directory; no creation or repair.')
    inspect_p.add_argument('--inventory-sha256', required=True,
                           help='Reviewed complete canonical operation projection digest.')


def _add_bootstrap_parser(svc_subs: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register the 'bootstrap' non-service subcommand (platform registration)."""
    boot_p = svc_subs.add_parser(
        "bootstrap",
        help="Report registration authority requirements; live CLI writes are unavailable.",
    )
    boot_p.add_argument(
        "--dry-run", action="store_true", default=False, dest="dry_run",
        help="Request a read-only preview; reports missing owner context in this CLI.",
    )
    boot_p.add_argument(
        "--remove", "--unregister", action="store_true", default=False, dest="remove",
        help="Request withdrawal; requires the separate owner approval workflow.",
    )


def _default_service_factory(op_name: str, *, profile: str | None = None) -> Any:
    """Default factory: build real service from macOS Keychain."""
    from google_kit.core.auth import build_service_for_op

    return build_service_for_op(op_name, profile=profile)


def _service_kwargs(
    spec: Any,
    factory: Callable[..., Any],
    op_name: str,
    profile: str | None,
) -> dict[str, Any]:
    """Build the service kwargs to splat into a core fn (engine injection seam).

    Three shapes, derived from the core fn signature so adding an op needs no
    adapter edit:

    * Recipe ops (``recipes.*``) span multiple APIs → ``service`` is a *resolver*
      callable ``prefix -> resource``.
    * Multi-service ops (params named ``<prefix>_service``, e.g.
      ``drive_service`` + ``docs_service``) → one built resource per prefix, so
      these ops are reachable from CLI/MCP (not just direct calls).
    * 1:1 ops (a plain ``service`` param) → a single built resource for the op's
      own API.
    """
    if spec.name.startswith("recipes."):
        def _resolver(api_prefix: str) -> Any:
            return factory(f"{api_prefix}._recipe", profile=profile)

        return {"service": _resolver}

    kwargs: dict[str, Any] = {}
    for pname in inspect.signature(spec.fn).parameters:
        if pname == "service":
            kwargs["service"] = factory(op_name, profile=profile)
        elif pname.endswith("_service"):
            prefix = pname[: -len("_service")]
            kwargs[pname] = factory(f"{prefix}._svc", profile=profile)
    return kwargs


def _main(
    argv: list[str] | None = None,
    *,
    _service_factory: Callable[..., Any] | None = None,
    _store_factory: Callable[..., Any] | None = None,
    _flow_factory: Callable[..., Any] | None = None,
    _transport_factory: Callable[..., Any] | None = None,
) -> None:
    """CLI entry point for google-kit.

    Args:
        argv: Argument vector (defaults to sys.argv[1:]).
        _service_factory: Override the auth builder for tests. Called as
            ``_service_factory(op_name, profile=profile)``. Defaults to real
            Keychain auth via :func:`google_kit.core.auth.build_service_for_op`.
        _store_factory: Override the SecretStore builder for auth subcommand tests.
            Called as ``_store_factory(profile)``. Defaults to KeychainSecretStore.
        _flow_factory: Override the PKCE flow builder for auth subcommand tests.
            Called as ``_flow_factory(store, client_id, headless=bool)``.
            Defaults to LoopbackPKCEFlow with Google endpoints.
    """
    parser = _build_parser()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    ns = parser.parse_args(_normalize_global_options(raw_argv))

    if ns.service is None:
        parser.print_help()
        sys.exit(0)

    if ns.service == "mcp":
        import asyncio

        from google_kit.mcp import run_server

        asyncio.run(run_server())
        return

    if ns.service == "help":
        intent = " ".join(getattr(ns, "intent", []) or [])
        sys.exit(
            cmd_help(
                intent,
                limit=getattr(ns, "limit", 5),
                fmt=getattr(ns, "format", "json"),
            )
        )

    if ns.service == "auth":
        from google_kit.cli.auth import (
            cmd_authorizations,
            cmd_grant,
            cmd_inspect,
            cmd_login,
            cmd_logout,
            cmd_revoke,
            cmd_status,
        )

        auth_cmd = getattr(ns, "auth_cmd", None)
        if auth_cmd is None:
            print(
                "Usage: google-kit auth <cmd>  [options]\n"
                "Commands: login, status, logout, grant, revoke, authorizations, inspect",
                file=sys.stderr,
            )
            sys.exit(1)

        profile = getattr(ns, "profile", None)

        # Mirror the op-path handler: surface a domain error (e.g. an invalid
        # profile rejected by the authz store) as a clean message + exit code,
        # never a bare traceback. `sys.exit` raises SystemExit, which is not a
        # GoogleKitError, so successful dispatch still exits normally.
        try:
            if auth_cmd == "login":
                rc = cmd_login(
                    profile,
                    force=ns.force,
                    headless=ns.headless,
                    extra_scopes=getattr(ns, "extra_scopes", None),
                    personal=ns.personal,
                    expected_email=ns.expected_email, expected_subject=ns.expected_subject,
                    expected_client_id=ns.expected_client_id, expected_project_id=ns.expected_project_id,
                    client_file=ns.client_file, client_file_sha256=ns.client_file_sha256,
                    config_dir=ns.config_dir, expected_inventory_digest=ns.inventory_sha256,
                    personal_scopes=ns.personal_scopes,
                    _store_factory=_store_factory,
                    _flow_factory=_flow_factory,
                    _transport_factory=_transport_factory,
                )
            elif auth_cmd == "status":
                rc = cmd_status(profile, _store_factory=_store_factory)
            elif auth_cmd == "logout":
                rc = cmd_logout(profile, all_=ns.all_keys, _store_factory=_store_factory)
            elif auth_cmd == "grant":
                rc = cmd_grant(profile, ns.op)
            elif auth_cmd == "revoke":
                rc = cmd_revoke(profile, ns.op)
            elif auth_cmd == "authorizations":
                rc = cmd_authorizations(profile, fmt=getattr(ns, "format", "json"))
            elif auth_cmd == 'inspect':
                rc = cmd_inspect(profile, expected_email=ns.expected_email,
                    expected_subject=ns.expected_subject,expected_client_id=ns.expected_client_id,config_dir=ns.config_dir,
                    expected_inventory_digest=ns.inventory_sha256,
                    fmt=getattr(ns,'format','json'),_store_factory=_store_factory,
                    _transport_factory=_transport_factory)
            else:
                rc = 0
        except GoogleKitError as exc:
            print(f"error: {exc.message}", file=sys.stderr)
            sys.exit(exc.to_exit_code())
        sys.exit(rc)

    if ns.service == "bootstrap":
        sys.exit(
            cmd_bootstrap(
                dry_run=getattr(ns, "dry_run", False),
                remove=getattr(ns, "remove", False),
                fmt=getattr(ns, "format", "json"),
            )
        )

    if not hasattr(ns, "op") or ns.op is None:
        ops = sorted(
            spec.name.split(".", 1)[1].replace("_", "-")
            for spec in all_specs()
            if spec.name.startswith(f"{ns.service}.")
        )
        print(
            f"Usage: google-kit {ns.service} <op>  [options]\n"
            f"Operations: {', '.join(ops) or '(none)'}",
            file=sys.stderr,
        )
        sys.exit(1)

    op_name = f"{ns.service}.{ns.op.replace('-', '_')}"
    try:
        spec = get(op_name)
    except KeyError:
        print(f"error: unknown operation {op_name!r}", file=sys.stderr)
        sys.exit(1)

    factory = _service_factory or _default_service_factory
    profile = getattr(ns, "profile", None)
    token = set_run_id(new_run_id())
    try:
        from google_kit.core.personal_runtime import operation
        with operation(spec, profile):
            inp = _coerce_argv_to_model(spec, ns)
            ensure_enabled(spec, profile=profile)
            result = spec.fn(inp, **_service_kwargs(spec, factory, op_name, profile))
            _print_envelope(result, fmt=getattr(ns, "format", "json"))
    except SystemExit:
        raise
    except GoogleKitError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        sys.exit(exc.to_exit_code())
    except Exception as exc:
        from google_kit.core.redaction import redact_string

        print(f"error: {redact_string(str(exc))}", file=sys.stderr)
        sys.exit(1)
    finally:
        reset_run_id(token)


def main(argv=None, *, _service_factory=None, _store_factory=None, _flow_factory=None,
         _transport_factory=None, _personal_store_factory=None,
         _personal_transport=None, _personal_build_fn=None):
    """Keep legacy callers unchanged; explicit paired context selects personal consumption."""
    raw = list(sys.argv[1:] if argv is None else argv)
    wants_personal = any(a in ("--personal-context", "--personal-context-sha256")
        or a.startswith(("--personal-context=", "--personal-context-sha256=")) for a in raw)
    kwargs = dict(_service_factory=_service_factory, _store_factory=_store_factory,
                  _flow_factory=_flow_factory, _transport_factory=_transport_factory)
    if not wants_personal:
        return _main(raw, **kwargs)
    from google_kit.core.personal_runtime import activate, held, PersonalRuntimeError
    ns = _build_parser().parse_args(_normalize_global_options(raw))
    try:
        if not ns.personal_context or not ns.personal_context_sha256:
            held("paired_context_options_required")
        if ns.service in (None, "auth", "bootstrap"):
            held("personal_consumer_command_required")
        with activate(ns.personal_context, ns.personal_context_sha256,
                      profile=getattr(ns, "profile", None),
                      store_factory=_personal_store_factory, transport=_personal_transport,
                      build_fn=_personal_build_fn):
            return _main(raw, **kwargs)
    except PersonalRuntimeError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        sys.exit(exc.to_exit_code())
