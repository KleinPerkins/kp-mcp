"""google-kit auth subcommand — login, status, logout.

Never prints secret values. Injection seams (_store_factory, _flow_factory) allow
tests to substitute fake implementations without touching Keychain or network.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable
from urllib.parse import urlparse

from kp_mcp_bootstrap.secrets import SecretStore

_CREDENTIAL_KEYS: tuple[str, ...] = ("access_token", "refresh_token")
_ALL_KEYS: tuple[str, ...] = ("client_id", "client_secret", "access_token", "refresh_token")

# Opt-in env var carrying extra OAuth scopes to request at login, in addition to
# the shared GOOGLE_KIT_SCOPES union (comma/space separated). Unioned with any
# --scopes flag values. Used for sandbox new-API consent — see
# docs/dev/LIVE-E2E-NEW-APIS.md. Empty/unset => default behavior (10 scopes).
_EXTRA_SCOPES_ENV: str = "GOOGLE_KIT_EXTRA_SCOPES"

# Valid extra scopes are full Google OAuth scope URLs. These hosts cover every
# google-kit scope (including the new-API scopes); anything else fails loud.
_GOOGLE_SCOPE_HOSTS: tuple[str, ...] = ("googleapis.com", "google.com")


def _split_scope_tokens(raw: str | None) -> list[str]:
    """Split one comma/space-separated scope string into individual tokens."""
    if not raw:
        return []
    return [tok for tok in raw.replace(",", " ").split() if tok]


def _collect_extra_scope_tokens(
    flag_values: list[str] | None, env_value: str | None
) -> list[str]:
    """Flatten --scopes flag values and the env var into one token list.

    Each input may itself be comma/space separated. Flag tokens come first (in
    the order given), then env tokens; dedup + ordering happens in
    :func:`_union_scopes`.
    """
    tokens: list[str] = []
    for raw in flag_values or []:
        tokens.extend(_split_scope_tokens(raw))
    tokens.extend(_split_scope_tokens(env_value))
    return tokens


def _is_google_scope_url(scope: str) -> bool:
    """True if *scope* is an ``https://`` URL on a known Google scope host."""
    parsed = urlparse(scope)
    host = parsed.netloc.lower()
    return parsed.scheme == "https" and any(
        host == h or host.endswith("." + h) for h in _GOOGLE_SCOPE_HOSTS
    )


def _union_scopes(base: list[str], extra_tokens: list[str]) -> list[str]:
    """Return ``base`` unioned with validated extra scopes, deterministically.

    ``base`` keeps its canonical order; *new* extras (those not already in base)
    are deduplicated and appended in sorted order. With no extra tokens the
    result is byte-identical to ``base`` (so default login is unchanged).

    Raises:
        ValueError: if any extra token is not a full Google OAuth scope URL.
            The offending value is NOT echoed (never leak provided input).
    """
    if any(not _is_google_scope_url(tok) for tok in extra_tokens):
        raise ValueError("malformed extra OAuth scope")
    base_set = set(base)
    new_extras = sorted({tok for tok in extra_tokens if tok not in base_set})
    return list(base) + new_extras


def _resolve_profile(profile: str | None) -> str:
    from kp_mcp_bootstrap.config import load_config
    cfg = load_config()
    return profile or cfg.profile


def _default_store_factory(profile: str) -> SecretStore:
    from kp_mcp_bootstrap.secrets import KeychainSecretStore
    return KeychainSecretStore(profile=profile)


def _default_flow_factory(
    store: SecretStore,
    client_id: str,
    *,
    headless: bool = False,
) -> Any:
    from google_kit.core.client import _GOOGLE_AUTH_ENDPOINT, _GOOGLE_TOKEN_ENDPOINT
    from kp_mcp_bootstrap.oauth import LoopbackPKCEFlow

    return LoopbackPKCEFlow(
        store=store,
        auth_endpoint=_GOOGLE_AUTH_ENDPOINT,
        token_endpoint=_GOOGLE_TOKEN_ENDPOINT,
        client_id=client_id,
        headless=headless,
    )


def cmd_login(
    profile: str | None,
    *,
    force: bool = False,
    headless: bool = False,
    extra_scopes: list[str] | None = None,
    personal: bool = False,
    expected_email: str | None = None,
    expected_subject: str | None = None,
    expected_client_id: str | None = None,
    expected_project_id: str | None = None,
    client_file: str | None = None,
    client_file_sha256: str | None = None,
    config_dir: str | None = None,
    expected_inventory_digest: str | None = None,
    personal_scopes: list[str] | None = None,
    _store_factory: Callable[[str], SecretStore] | None = None,
    _flow_factory: Callable[..., Any] | None = None,
    _transport_factory: Callable[..., Any] | None = None,
) -> int:
    """Run OAuth PKCE flow and persist tokens to the Keychain.

    Requires client_id and client_secret already present in the Keychain.
    Use --force to re-consent even when a token exists.
    Use --headless to print the auth URL to stderr instead of opening a browser.

    By default the flow requests exactly GOOGLE_KIT_SCOPES (the shared cutover
    consent union, unchanged). Extra scopes may be requested for THIS login only
    via ``extra_scopes`` (the --scopes flag) and/or the GOOGLE_KIT_EXTRA_SCOPES
    env var (both comma/space separated; the two are unioned). This is the
    opt-in path to grant new-API scopes to a sandbox profile WITHOUT widening the
    shared union (which would force re-consent for every profile, prod included).
    Extra scopes must be full Google OAuth scope URLs; malformed input fails loud
    and the offending value is never echoed.

    Returns 0 on success, 1 on error.
    """
    personal_options = (expected_email, expected_subject, expected_client_id,
                        expected_project_id, client_file, client_file_sha256,
                        config_dir, expected_inventory_digest, personal_scopes)
    if personal or any(value is not None for value in personal_options):
        from google_kit.core.personal_login import login_personal
        if personal is not True or force or extra_scopes or os.environ.get(_EXTRA_SCOPES_ENV):
            print(json.dumps({'status':'held','reason':'personal_scope_override_refused'}), file=sys.stderr)
            return 1
        from google_kit.registry import all_specs
        operations = [{'name':s.name,'scopes':list(s.scopes),'posture':s.posture,'flag':s.flag} for s in all_specs()]
        result = login_personal(profile=profile, expected_email=expected_email,
            expected_subject=expected_subject, expected_client_id=expected_client_id,
            expected_project_id=expected_project_id, client_file=client_file,
            client_file_sha256=client_file_sha256, config_dir=config_dir,
            expected_inventory_digest=expected_inventory_digest, operations=operations, requested_scopes=personal_scopes,
            store_factory=_store_factory or _default_store_factory,
            flow_factory=_flow_factory, transport_factory=_transport_factory, headless=headless)
        success = result['status'] == 'verified_credentials_created'
        print(json.dumps(result, indent=2, sort_keys=True), file=sys.stdout if success else sys.stderr)
        return 0 if success else 1
    active_profile = _resolve_profile(profile)
    make_store = _store_factory or _default_store_factory
    store = make_store(active_profile)

    missing = [k for k in ("client_id", "client_secret") if not store.has(k)]
    if missing:
        print(
            f"error: {', '.join(missing)} not found in Keychain for profile '{active_profile}'.\n"
            "Import client_secret.json into the Keychain first:\n"
            "  security add-generic-password -s google-kit -a default:client_id -w <value>\n"
            "  security add-generic-password -s google-kit -a default:client_secret -w <value>",
            file=sys.stderr,
        )
        return 1

    if not force and store.has("access_token"):
        print(f"Already logged in for profile '{active_profile}'. Use --force to re-consent.")
        return 0

    from google_kit.core.auth import GOOGLE_KIT_SCOPES

    extra_tokens = _collect_extra_scope_tokens(
        extra_scopes, os.environ.get(_EXTRA_SCOPES_ENV)
    )
    if extra_tokens:
        try:
            requested_scopes = _union_scopes(GOOGLE_KIT_SCOPES, extra_tokens)
        except ValueError:
            print(
                "error: invalid extra OAuth scope. Extra scopes must be full "
                "Google OAuth scope URLs, e.g.\n"
                "  https://www.googleapis.com/auth/directory.readonly\n"
                f"Provide them via --scopes or {_EXTRA_SCOPES_ENV} "
                "(comma/space separated).",
                file=sys.stderr,
            )
            return 1
    else:
        requested_scopes = GOOGLE_KIT_SCOPES

    client_id = store.get("client_id")

    make_flow = _flow_factory or _default_flow_factory
    flow = make_flow(store, client_id, headless=headless)

    code = flow.authorize(requested_scopes)
    flow.exchange(code)

    present = [k for k in _ALL_KEYS if store.has(k)]

    # Seed the profile's write-authorization config (every gated tool at 0 /
    # default-deny) on first login, so a freshly-created profile has an explicit,
    # inspectable authorization surface. Idempotent: existing grants are kept.
    from google_kit.core.authz import seed_profile

    seed_profile(active_profile)

    print(f"Login successful for profile '{active_profile}'. Keys present: {', '.join(present)}.")
    return 0


def cmd_status(
    profile: str | None,
    *,
    _store_factory: Callable[[str], SecretStore] | None = None,
) -> int:
    """Report Keychain key presence for the profile (never prints values).

    Returns 0 if logged in (access_token or refresh_token present), 1 otherwise.
    """
    active_profile = _resolve_profile(profile)
    make_store = _store_factory or _default_store_factory
    store = make_store(active_profile)

    print(f"Profile: {active_profile}")
    for key in _ALL_KEYS:
        present = store.has(key)
        print(f"  {key}: {'present' if present else 'absent'}")

    logged_in = store.has("access_token") or store.has("refresh_token")
    if not logged_in:
        print("Hint: run 'google-kit auth login' to authenticate.")
        return 1
    return 0


def cmd_logout(
    profile: str | None,
    *,
    all_: bool = False,
    _store_factory: Callable[[str], SecretStore] | None = None,
) -> int:
    """Delete tokens (and credentials if --all) from the Keychain.

    Always deletes access_token and refresh_token.
    With --all also deletes client_id and client_secret.

    Returns 0 always.
    """
    active_profile = _resolve_profile(profile)
    make_store = _store_factory or _default_store_factory
    store = make_store(active_profile)

    keys_to_remove = list(_ALL_KEYS) if all_ else list(_CREDENTIAL_KEYS)
    removed = [k for k in keys_to_remove if store.has(k)]
    for key in removed:
        store.delete(key)

    if removed:
        print(f"Removed from profile '{active_profile}': {', '.join(removed)}.")
    else:
        print(f"Nothing to remove for profile '{active_profile}'.")
    return 0


def _resolve_gated_op(op: str) -> tuple[str | None, str | None]:
    """Resolve a user-supplied op name to a registered op that requires auth.

    Accepts the canonical dotted name (``gmail.send``) and tolerates dashes within
    the op part (``gmail.batch-modify`` → ``gmail.batch_modify``). Returns
    ``(canonical_name, None)`` on success, or ``(None, error_message)`` if the op
    is unknown or does not require authorization (a read / admin op).
    """
    from google_kit.core.authz import requires_authorization
    from google_kit.registry import all_specs, get

    candidate = (op or "").strip()
    names = {spec.name for spec in all_specs()}
    if candidate not in names and "." in candidate:
        service, _, rest = candidate.partition(".")
        candidate = f"{service}.{rest.replace('-', '_')}"
    try:
        spec = get(candidate)
    except KeyError:
        return None, (
            f"error: unknown operation {op!r}. Use the dotted op name, e.g. 'gmail.send'."
        )
    if not requires_authorization(spec):
        return None, (
            f"error: {spec.name} is a read/admin op and does not require authorization."
        )
    return spec.name, None


def cmd_grant(profile: str | None, op: str) -> int:
    """Authorize (set to 1) a write op for the profile. Returns 0 / 1."""
    from google_kit.core.authz import resolve_active_profile, set_authorization

    active_profile = resolve_active_profile(profile)
    name, err = _resolve_gated_op(op)
    if err is not None:
        print(err, file=sys.stderr)
        return 1
    set_authorization(active_profile, name, 1)
    print(f"Authorized {name} for profile '{active_profile}'.")
    return 0


def cmd_revoke(profile: str | None, op: str) -> int:
    """De-authorize (set to 0) a write op for the profile. Returns 0 / 1."""
    from google_kit.core.authz import resolve_active_profile, set_authorization

    active_profile = resolve_active_profile(profile)
    name, err = _resolve_gated_op(op)
    if err is not None:
        print(err, file=sys.stderr)
        return 1
    set_authorization(active_profile, name, 0)
    print(f"Revoked {name} for profile '{active_profile}'.")
    return 0


def cmd_authorizations(profile: str | None, *, fmt: str = "json") -> int:
    """Print the per-tool write authorization (1/0) for the profile. Returns 0.

    Lists every op that requires authorization with its current grant for the
    profile (persisted ``1`` or default ``0``). ``--format json`` emits a stable
    object; otherwise a human-readable table.
    """
    from google_kit.core.authz import authorization_view, resolve_active_profile

    active_profile = resolve_active_profile(profile)
    view = authorization_view(active_profile)

    if fmt == "json":
        import json

        print(json.dumps(
            {"profile": active_profile, "tools": view},
            indent=2, sort_keys=True,
        ))
        return 0

    print(f"Write authorization for profile '{active_profile}':")
    if not view:
        print("  (no ops require authorization)")
        return 0
    for name in sorted(view):
        mark = "1" if view[name] else "0"
        print(f"  [{mark}] {name}")
    granted = sum(1 for v in view.values() if v)
    print(f"  {granted}/{len(view)} authorized.")
    return 0


def cmd_inspect(
    profile: str | None, *, expected_email: str, expected_subject: str, expected_client_id: str,
    config_dir: str, expected_inventory_digest: str, fmt: str = 'json',
    _store_factory=None, _transport_factory=None,
) -> int:
    """Inspect one explicit identity/scope/authz binding without refresh/writes.

    Missing authorization data remains default-deny evidence; malformed data is
    refused. A successful report is diagnostic, never execution or registration
    authority. Stock login/token adoption is deliberately a separate operation.
    """
    from google_kit.core.personal_preflight import (
        CLIENT, EMAIL, PROFILE, SUBJECT, GoogleReadTransport, Refused, inspect_profile,
    )
    from google_kit.core.personal_authz import read_authorizations
    from google_kit.registry import all_specs

    try:
        if not isinstance(profile,str) or not PROFILE.fullmatch(profile):
            raise Refused('explicit_profile_required')
        if not isinstance(expected_email,str) or not EMAIL.fullmatch(expected_email):
            raise Refused('expected_identity_required')
        if not isinstance(expected_subject,str) or not SUBJECT.fullmatch(expected_subject):
            raise Refused('expected_identity_required')
        if not isinstance(expected_client_id,str) or not CLIENT.fullmatch(expected_client_id):
            raise Refused('expected_client_identity_required')
        operations=[{'name':s.name,'scopes':list(s.scopes),'posture':s.posture,'flag':s.flag} for s in all_specs()]
        before=read_authorizations(config_dir=config_dir,profile=profile,
            operations=operations,expected_inventory_digest=expected_inventory_digest)
        store=(_store_factory or _default_store_factory)(profile)
        transport=(_transport_factory or GoogleReadTransport)()
        report=inspect_profile(profile=profile,expected_email=expected_email,
            expected_subject=expected_subject,expected_client_id=expected_client_id,store=store,transport=transport,
            operations=operations,expected_inventory_digest=expected_inventory_digest)
        after=read_authorizations(config_dir=config_dir,profile=profile,
            operations=operations,expected_inventory_digest=expected_inventory_digest)
        if before!=after:raise Refused('authorization_changed')
        report['authorization_snapshot']=after
        report['operation_grants_read_or_changed']=after['profile_grants_observed']
        report['operation_grants_observed']=after['profile_grants_observed']
        report['operation_grants_changed']=False
        if fmt=='text':
            print(f"Profile: {profile}\nExpected account: {expected_email}\nIdentity matches: true")
            print(f"Observed scopes: {len(report['observed_token_scopes'])}\nAuthorization snapshot: {after['state']}\nExecution authorized: false")
        else:
            print(json.dumps(report,indent=2,sort_keys=True))
        return 0
    except Refused as exc:
        reason=exc.reason if type(exc) is Refused else 'inspection_unavailable'
        print(json.dumps({'status':'refused','reason':reason}),file=sys.stderr)
        return 1
    except Exception:
        print(json.dumps({'status':'refused','reason':'inspection_unavailable'}),file=sys.stderr)
        return 1
