"""Closed registrar-v1 records and canonical encodings."""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterator, Mapping, Sequence
from urllib.parse import urlsplit

from kp_mcp_bootstrap.errors import ReasonCode, RegistrarError


ADAPTER_VERSION = "kp-mcp/adapter/v1"
DEFINITION_SCHEMA = "kp-mcp/registration-definition/v1"
CONTEXT_SCHEMA = "kp-mcp/registration-context/v1"
AUTH_SCHEMA = "kp-mcp/auth-binding/v1"
WRITER_SCHEMA = "kp-mcp/writer-window/v1"
MIGRATION_SCHEMA = "kp-mcp/migration-evidence/v1"
PREVIEW_SCHEMA = "kp-mcp/registrar-preview/v1"
PREPARED_SCHEMA = "kp-mcp/prepared-operation/v1"
APPROVAL_SCHEMA = "kp-mcp/approval/v1"
RESULT_SCHEMA = "kp-mcp/registrar-result/v1"
INSPECTION_SCHEMA = "kp-mcp/registrar-inspection/v1"
ABSENT_DIGEST = "absent"
MAX_PREVIEW_SECONDS = 600

_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_KEY_PARTS = (
    "access_token", "api_key", "authorization", "bearer", "client_secret",
    "credential", "password", "private_key", "refresh_token", "secret", "token",
)


class Action(StrEnum):
    REGISTER = "register"
    ADOPT = "adopt"
    UNREGISTER = "unregister"
    RECOVER = "recover"
    ROLLBACK = "rollback"
    CANCEL = "cancel"


class Outcome(StrEnum):
    READY = "ready"
    APPLIED = "applied"
    NO_CHANGE = "no_change"
    CONFLICT = "conflict"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"
    RECOVERY_REQUIRED = "recovery_required"
    RECOVERED = "recovered"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


class RecoveryDisposition(StrEnum):
    COMPLETE = "complete"
    CANCEL = "cancel"


class ObservationStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    DISABLED = "disabled"


class OwnershipStatus(StrEnum):
    ABSENT = "absent"
    OWNED = "owned"
    UNKNOWN = "unknown"
    EXTERNAL = "external"
    CONFLICT = "conflict"


class AuthKind(StrEnum):
    NONE = "none"
    NATIVE_OAUTH = "native-oauth"
    ENVIRONMENT_REFERENCE = "environment-reference"


class OperationRefKind(StrEnum):
    COMMITTED_RECEIPT = "committed-receipt"
    PENDING_JOURNAL = "pending-journal"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timezone-aware datetime required")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone-aware datetime required")
    return parsed.astimezone(timezone.utc)


def _canonical(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return isoformat(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite numbers are not canonical")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "to_record"):
        return _canonical(value.to_record())
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    text = json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return (text + "\n").encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_value(value: Any) -> str:
    return digest_bytes(canonical_json_bytes(value))


def strict_json_loads(data: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> Any:
        raise ValueError("non-finite number")

    return json.loads(
        data.decode("utf-8"),
        object_pairs_hook=pairs,
        parse_constant=reject_constant,
    )


def bounded_id(value: str) -> str:
    return digest_bytes(value.encode("utf-8"))


def pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def pointer_unescape(value: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "~":
            output.append(value[index])
            index += 1
            continue
        if index + 1 >= len(value) or value[index + 1] not in {"0", "1"}:
            raise ValueError("invalid JSON Pointer escape")
        output.append("~" if value[index + 1] == "0" else "/")
        index += 2
    return "".join(output)


def validate_pointer_set(
    paths: Sequence[str], *, expected: frozenset[str] | None = None
) -> tuple[str, ...]:
    normalized = tuple(paths)
    if not normalized:
        raise ValueError("ownership pointers are required")
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate ownership pointer")
    decoded: list[tuple[str, ...]] = []
    for path in normalized:
        if not isinstance(path, str) or not path.startswith("/") or path == "/":
            raise ValueError("ownership pointer must be an absolute leaf pointer")
        segments = tuple(pointer_unescape(part) for part in path[1:].split("/"))
        rebuilt = "/" + "/".join(pointer_escape(part) for part in segments)
        if rebuilt != path:
            raise ValueError("noncanonical ownership pointer")
        decoded.append(segments)
    for index, left in enumerate(decoded):
        for right in decoded[index + 1 :]:
            shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
            if longer[: len(shorter)] == shorter:
                raise ValueError("overlapping ownership pointers")
    if expected is not None and frozenset(normalized) != expected:
        raise ValueError("ownership pointers do not equal the complete projection")
    return tuple(sorted(normalized))


def validate_hex(value: str, *, allow_absent: bool = False) -> str:
    if allow_absent and value == ABSENT_DIGEST:
        return value
    if not _HEX_RE.fullmatch(value):
        raise ValueError("expected SHA-256 digest")
    return value


def validate_identifier(value: str) -> str:
    if not value or value.strip() != value or any(ord(char) < 32 for char in value):
        raise ValueError("invalid identifier")
    return value


def _looks_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def _looks_secret_literal(value: str) -> bool:
    lower = value.lower()
    return (
        "bearer " in lower
        or "client_secret=" in lower
        or "access_token=" in lower
        or value.startswith(("sk-", "ghp_", "xox"))
    )


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    source_owner: str
    connection_id: str
    source_revision: str
    native_name: str

    def __post_init__(self) -> None:
        for value in (
            self.source_owner,
            self.connection_id,
            self.source_revision,
            self.native_name,
        ):
            validate_identifier(value)

    def to_record(self) -> dict[str, str]:
        return {
            "source_owner": self.source_owner,
            "connection_id": self.connection_id,
            "source_revision": self.source_revision,
            "native_name": self.native_name,
        }


@dataclass(frozen=True, slots=True, init=False)
class StdioTransport:
    command: str
    args: tuple[str, ...]
    _env_items: tuple[tuple[str, str], ...] = field(repr=False)
    kind: str = field(default="stdio", init=False)

    def __init__(
        self,
        command: str,
        args: Sequence[str] = (),
        env: Mapping[str, str] | None = None,
    ) -> None:
        if not isinstance(command, str) or not Path(command).is_absolute() or "\x00" in command:
            raise ValueError("stdio command must be a nonempty absolute path")
        if _looks_secret_literal(command):
            raise ValueError("literal credential material is not allowed")
        converted_args = tuple(args)
        if any(not isinstance(arg, str) or "\x00" in arg for arg in converted_args):
            raise ValueError("stdio args must be strings")
        if any(_looks_secret_literal(arg) for arg in converted_args):
            raise ValueError("literal credential material is not allowed")
        items: list[tuple[str, str]] = []
        for key, value in (env or {}).items():
            if not isinstance(key, str) or not _ENV_NAME_RE.fullmatch(key):
                raise ValueError("invalid environment variable name")
            if _looks_secret_key(key):
                raise ValueError("secret-bearing environment fields are not allowed")
            if not isinstance(value, str) or "\x00" in value or _looks_secret_literal(value):
                raise ValueError("invalid non-secret environment value")
            items.append((key, value))
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "args", converted_args)
        object.__setattr__(self, "_env_items", tuple(sorted(items)))
        object.__setattr__(self, "kind", "stdio")

    @property
    def env(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self._env_items))

    def to_record(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "command": self.command,
            "args": list(self.args),
            "env": dict(self._env_items),
        }

    def __repr__(self) -> str:
        keys = tuple(key for key, _value in self._env_items)
        return (
            f"StdioTransport(command={self.command!r}, args={self.args!r}, "
            f"env_keys={keys!r})"
        )


@dataclass(frozen=True, slots=True)
class StreamableHTTPTransport:
    url: str
    kind: str = field(default="streamable-http", init=False)

    def __post_init__(self) -> None:
        # urlsplit deliberately tolerates whitespace, empty delimiters and an
        # unchecked port. Reject those forms without normalizing the endpoint.
        try:
            if (
                not isinstance(self.url, str)
                or any(char.isspace() or ord(char) < 32 or 127 <= ord(char) <= 159 for char in self.url)
                or any(char in self.url for char in ("?", "#", "\\"))
                or re.search(r"%(?![0-9A-Fa-f]{2})", self.url)
            ):
                raise ValueError
            self.url.encode("utf-8")
            parts = urlsplit(self.url)
            if (
                parts.scheme != "https"
                or not parts.netloc
                or not parts.hostname
                or parts.username is not None
                or parts.password is not None
            ):
                raise ValueError
            # Accessing port validates numeric syntax and the 0..65535 range.
            port = parts.port
            if parts.netloc.startswith("["):
                suffix = parts.netloc[parts.netloc.index("]") + 1:]
                if suffix and (not suffix.startswith(":") or port is None):
                    raise ValueError
            else:
                host = parts.hostname.encode("idna").decode("ascii")
                if not re.fullmatch(r"(?:[A-Za-z0-9._~!$&'()*+,;=-]|%[0-9A-Fa-f]{2})+", host):
                    raise ValueError
            if parts.netloc.endswith(":"):
                raise ValueError
        except (ValueError, TypeError, UnicodeError):
            raise ValueError("streamable HTTP URL must be absolute HTTPS without credentials, query or fragment") from None

    def to_record(self) -> dict[str, str]:
        return {"kind": self.kind, "url": self.url}


Transport = StdioTransport | StreamableHTTPTransport


@dataclass(frozen=True, slots=True)
class RegistrationDefinition:
    connection_id: str
    source_owner: str
    source_revision: str
    native_name: str
    transport: Transport
    owned_paths: tuple[str, ...]
    schema: str = DEFINITION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != DEFINITION_SCHEMA:
            raise RegistrarError(ReasonCode.UNSUPPORTED_SCHEMA)
        SourceIdentity(
            source_owner=self.source_owner,
            connection_id=self.connection_id,
            source_revision=self.source_revision,
            native_name=self.native_name,
        )
        if isinstance(self.transport, StdioTransport):
            expected = {
                "/transport/kind",
                "/transport/command",
                "/transport/args",
                *(f"/transport/env/{pointer_escape(key)}" for key in self.transport.env),
            }
        elif isinstance(self.transport, StreamableHTTPTransport):
            expected = {"/transport/kind", "/transport/url"}
        else:
            raise RegistrarError(ReasonCode.UNSUPPORTED_TRANSPORT)
        object.__setattr__(
            self,
            "owned_paths",
            validate_pointer_set(self.owned_paths, expected=frozenset(expected)),
        )

    @property
    def identity(self) -> SourceIdentity:
        return SourceIdentity(
            source_owner=self.source_owner,
            connection_id=self.connection_id,
            source_revision=self.source_revision,
            native_name=self.native_name,
        )

    @classmethod
    def stdio(
        cls,
        identity: SourceIdentity,
        *,
        command: str,
        args: Sequence[str] = (),
        env: Mapping[str, str] | None = None,
    ) -> "RegistrationDefinition":
        transport = StdioTransport(command=command, args=args, env=env)
        paths = (
            "/transport/kind",
            "/transport/command",
            "/transport/args",
            *(f"/transport/env/{pointer_escape(key)}" for key in transport.env),
        )
        return cls(
            connection_id=identity.connection_id,
            source_owner=identity.source_owner,
            source_revision=identity.source_revision,
            native_name=identity.native_name,
            transport=transport,
            owned_paths=tuple(paths),
        )

    @classmethod
    def streamable_http(
        cls, identity: SourceIdentity, *, url: str
    ) -> "RegistrationDefinition":
        return cls(
            connection_id=identity.connection_id,
            source_owner=identity.source_owner,
            source_revision=identity.source_revision,
            native_name=identity.native_name,
            transport=StreamableHTTPTransport(url=url),
            owned_paths=("/transport/kind", "/transport/url"),
        )

    @classmethod
    def from_server_entry(
        cls, identity: SourceIdentity, entry: Any
    ) -> "RegistrationDefinition":
        return cls.stdio(
            identity,
            command=entry.command,
            args=tuple(entry.args),
            env=dict(entry.env),
        )

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "RegistrationDefinition":
        values = dict(record)
        transport = dict(values["transport"])
        kind = transport.pop("kind")
        if kind == "stdio":
            values["transport"] = StdioTransport(**transport)
        elif kind == "streamable-http":
            values["transport"] = StreamableHTTPTransport(**transport)
        else:
            raise RegistrarError(ReasonCode.UNSUPPORTED_TRANSPORT)
        values["owned_paths"] = tuple(values["owned_paths"])
        result = cls(**values)
        if _canonical(result.to_record()) != record:
            raise ValueError("noncanonical definition")
        return result

    def to_record(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            **self.identity.to_record(),
            "transport": self.transport.to_record(),
            "owned_paths": list(self.owned_paths),
        }

    def to_dict(self) -> dict[str, Any]:
        record = self.to_record()
        transport = record["transport"]
        if transport["kind"] == "stdio":
            transport["env"] = {"keys": sorted(transport["env"])}
        return record

    @property
    def digest(self) -> str:
        return digest_value(self.to_record())

    @property
    def target_origin_digest(self) -> str:
        if isinstance(self.transport, StdioTransport):
            origin = {
                "transport": "stdio",
                "command": self.transport.command,
            }
        elif isinstance(self.transport, StreamableHTTPTransport):
            origin = {
                "transport": "streamable-http",
                "url": self.transport.url,
            }
        else:  # closed by RegistrationDefinition.__post_init__
            raise RegistrarError(ReasonCode.UNSUPPORTED_TRANSPORT)
        return digest_value(origin)


@dataclass(frozen=True, slots=True)
class AuthBinding:
    binding_id: str
    kind: AuthKind
    host: str
    surface: str
    scope: str
    target_origin_digest: str
    account_reference: str | None = field(default=None, repr=False)
    grant_reference: str | None = field(default=None, repr=False)
    allowed_native_fields: tuple[str, ...] = ()
    environment_variable: str | None = None
    schema: str = AUTH_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != AUTH_SCHEMA:
            raise RegistrarError(ReasonCode.UNSUPPORTED_SCHEMA)
        for value in (self.binding_id, self.host, self.surface, self.scope):
            validate_identifier(value)
        validate_hex(self.target_origin_digest)
        object.__setattr__(
            self,
            "allowed_native_fields",
            validate_pointer_set(self.allowed_native_fields)
            if self.allowed_native_fields
            else (),
        )
        if self.kind is AuthKind.NONE:
            if any(
                (
                    self.account_reference,
                    self.grant_reference,
                    self.allowed_native_fields,
                    self.environment_variable,
                )
            ):
                raise ValueError("none auth binding cannot carry references")
        elif self.kind is AuthKind.ENVIRONMENT_REFERENCE:
            if not self.environment_variable or not _ENV_NAME_RE.fullmatch(
                self.environment_variable
            ):
                raise ValueError("environment-reference requires a variable name")
            if not self.allowed_native_fields:
                raise ValueError("environment-reference requires exact native fields")
        elif self.kind is AuthKind.NATIVE_OAUTH:
            if not self.account_reference or not self.grant_reference:
                raise ValueError("native-oauth requires opaque account and grant references")

    @classmethod
    def none(
        cls,
        *,
        binding_id: str,
        host: str,
        surface: str,
        scope: str,
        target_origin_digest: str,
    ) -> "AuthBinding":
        return cls(
            binding_id=binding_id,
            kind=AuthKind.NONE,
            host=host,
            surface=surface,
            scope=scope,
            target_origin_digest=target_origin_digest,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "binding_id": self.binding_id,
            "kind": self.kind.value,
            "host": self.host,
            "surface": self.surface,
            "scope": self.scope,
            "target_origin_digest": self.target_origin_digest,
            "account_reference": self.account_reference,
            "grant_reference": self.grant_reference,
            "allowed_native_fields": list(self.allowed_native_fields),
            "environment_variable": self.environment_variable,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "binding_id": self.binding_id,
            "kind": self.kind.value,
            "host": self.host,
            "surface": self.surface,
            "scope": self.scope,
            "target_origin_digest": self.target_origin_digest,
            "allowed_native_fields": list(self.allowed_native_fields),
            "has_account_reference": self.account_reference is not None,
            "has_grant_reference": self.grant_reference is not None,
            "environment_variable": self.environment_variable,
        }

    @property
    def digest(self) -> str:
        return digest_value(self.to_record())


def versioned_schema(v1: str, context: "RegistrationContext") -> str:
    return v1[:-1] + "2" if context.maintenance_evidence is not None else v1


def maintenance_provenance(context: "RegistrationContext") -> dict[str, str]:
    if context.maintenance_evidence is None:
        return {}
    return {
        "concurrency_claim": "coordinated",
        "writer_window_digest": context.writer_window.digest,
        "maintenance_evidence_digest": context.maintenance_evidence.digest,
    }


def _maintenance_uuid(value: str) -> None:
    if str(uuid.UUID(value)) != value:
        raise ValueError("noncanonical maintenance UUID")


def _bounded_maintenance_id(value: str) -> None:
    validate_identifier(value)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}", value):
        raise ValueError("maintenance identifier exceeds bound")


@dataclass(frozen=True, slots=True)
class KnownWriterEvidence:
    writer_id: str
    kind: str
    prior_state: str
    observed_state: str
    observation_reference: str
    observation_digest: str
    observed_at: datetime
    resume_disposition: str

    def __post_init__(self) -> None:
        _bounded_maintenance_id(self.writer_id)
        _bounded_maintenance_id(self.observation_reference)
        validate_hex(self.observation_digest)
        isoformat(self.observed_at)
        if (self.kind not in {"legacy-mirror", "kit-lifecycle", "native-client", "editor", "server-guard", "management"}
            or self.prior_state not in {"active", "inactive", "not_enrolled"}
            or self.observed_state not in {"paused", "inactive"}
            or self.resume_disposition not in {"restore_prior", "remain_suspended"}):
            raise ValueError("unsupported known-writer evidence")

    def to_record(self) -> dict[str, Any]:
        return _canonical({item.name: getattr(self, item.name) for item in fields(self)})

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "KnownWriterEvidence":
        if set(record) != {item.name for item in fields(cls)}:
            raise ValueError("unknown or missing writer fields")
        return cls(**{**record, "observed_at": parse_iso(record["observed_at"])})


@dataclass(frozen=True, slots=True)
class MaintenanceEvidence:
    maintenance_id: str
    issuer_source_revision: str
    accepted_contract_digest: str
    audience_digest: str
    config_target_id: str
    state_target_id: str
    config_preimage_digest: str
    state_preimage_digest: str
    known_writers: tuple[KnownWriterEvidence, ...]
    consequence_review_digest: str
    legacy_handoff_id: str
    acquired_at: datetime
    expires_at: datetime
    prior_guard_state: str
    prior_guard_lock: str
    predecessor_maintenance_id: str | None
    recovery_of: str | None
    schema: str = "dev/mcp-maintenance-evidence/v1"

    def __post_init__(self) -> None:
        if self.schema != "dev/mcp-maintenance-evidence/v1":
            raise RegistrarError(ReasonCode.UNSUPPORTED_SCHEMA)
        _maintenance_uuid(self.maintenance_id)
        if not re.fullmatch(r"[0-9a-f]{40}", self.issuer_source_revision):
            raise ValueError("exact caller revision required")
        for value in (self.accepted_contract_digest, self.audience_digest,
                      self.config_target_id, self.state_target_id, self.consequence_review_digest):
            validate_hex(value)
        validate_hex(self.config_preimage_digest, allow_absent=True)
        validate_hex(self.state_preimage_digest, allow_absent=True)
        isoformat(self.acquired_at)
        isoformat(self.expires_at)
        if not 0 < (self.expires_at - self.acquired_at).total_seconds() <= MAX_PREVIEW_SECONDS:
            raise ValueError("invalid maintenance interval")
        object.__setattr__(self, "known_writers", tuple(self.known_writers))
        if (not self.known_writers or any(not isinstance(w, KnownWriterEvidence) for w in self.known_writers)
            or len({w.writer_id for w in self.known_writers}) != len(self.known_writers)
            or len(self.known_writers) > 64
            or any(not self.acquired_at - timedelta(seconds=MAX_PREVIEW_SECONDS) <= w.observed_at <= self.expires_at for w in self.known_writers)
            or self.legacy_handoff_id != self.maintenance_id
            or self.prior_guard_state not in {"enabled", "disabled", "not_enrolled"}
            or self.prior_guard_lock not in {"on", "off", "not_applicable"}
            or ((self.prior_guard_state == "not_enrolled") != (self.prior_guard_lock == "not_applicable"))
            or ((self.predecessor_maintenance_id is None) != (self.recovery_of is None))):
            raise ValueError("invalid maintenance evidence")
        if self.predecessor_maintenance_id is not None:
            _maintenance_uuid(self.predecessor_maintenance_id)
            validate_hex(self.recovery_of)
            if self.predecessor_maintenance_id == self.maintenance_id:
                raise ValueError("maintenance lineage cycle")

    def to_record(self) -> dict[str, Any]:
        return _canonical({item.name: ([w.to_record() for w in self.known_writers]
                if item.name == "known_writers" else getattr(self, item.name)) for item in fields(self)})

    @property
    def digest(self) -> str:
        return digest_value(self.to_record())

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "MaintenanceEvidence":
        if set(record) != {item.name for item in fields(cls)} or not isinstance(record["known_writers"], list):
            raise ValueError("unknown or missing maintenance fields")
        return cls(**{**record, "acquired_at": parse_iso(record["acquired_at"]),
                      "expires_at": parse_iso(record["expires_at"]),
                      "known_writers": tuple(KnownWriterEvidence.from_record(w) for w in record["known_writers"])})


@dataclass(frozen=True, slots=True)
class WriterWindow:
    qualification_id: str
    qualification_digest: str
    issuer_owner: str
    issuer_source_revision: str
    mechanism: str
    host: str
    surface: str
    build: str
    mapping_digest: str
    config_target_id: str
    state_target_id: str
    acquisition_reference: str
    acquired_at: datetime
    expires_at: datetime
    release_method: str
    schema: str = WRITER_SCHEMA
    concurrency_claim: str | None = None
    maintenance_evidence_digest: str | None = None

    def __post_init__(self) -> None:
        if self.schema not in {WRITER_SCHEMA, "kp-mcp/writer-window/v2"}:
            raise RegistrarError(ReasonCode.UNSUPPORTED_SCHEMA)
        if self.schema == "kp-mcp/writer-window/v2":
            if (self.mechanism != "coordinated-maintenance" or self.concurrency_claim != "coordinated"
                or self.issuer_owner != "KleinPerkins/dev" or self.release_method != "dev-int014-explicit-handoff/v1"):
                raise RegistrarError(ReasonCode.CONCURRENCY_UNQUALIFIED)
            validate_hex(self.maintenance_evidence_digest)
            _maintenance_uuid(self.acquisition_reference)
        elif self.concurrency_claim is not None or self.maintenance_evidence_digest is not None:
            raise RegistrarError(ReasonCode.UNSUPPORTED_SCHEMA)
        elif self.mechanism not in {
            "fixture-isolation",
            "native-conditional-write",
            "native-exclusive-window",
        }:
            raise RegistrarError(ReasonCode.CONCURRENCY_UNQUALIFIED)
        for digest in (
            self.qualification_digest,
            self.mapping_digest,
            self.config_target_id,
            self.state_target_id,
        ):
            validate_hex(digest)
        if self.expires_at <= self.acquired_at:
            raise ValueError("writer window must expire after acquisition")
        if (self.expires_at - self.acquired_at).total_seconds() > MAX_PREVIEW_SECONDS:
            raise ValueError("writer window exceeds maximum lifetime")

    def to_record(self) -> dict[str, Any]:
        return {
            **({"concurrency_claim": self.concurrency_claim, "maintenance_evidence_digest": self.maintenance_evidence_digest}
               if self.schema == "kp-mcp/writer-window/v2" else {}),
            "schema": self.schema,
            "qualification_id": self.qualification_id,
            "qualification_digest": self.qualification_digest,
            "issuer_owner": self.issuer_owner,
            "issuer_source_revision": self.issuer_source_revision,
            "mechanism": self.mechanism,
            "host": self.host,
            "surface": self.surface,
            "build": self.build,
            "mapping_digest": self.mapping_digest,
            "config_target_id": self.config_target_id,
            "state_target_id": self.state_target_id,
            "acquisition_reference": self.acquisition_reference,
            "acquired_at": self.acquired_at,
            "expires_at": self.expires_at,
            "release_method": self.release_method,
        }

    @property
    def digest(self) -> str:
        return digest_value(self.to_record())


@dataclass(frozen=True, slots=True)
class MigrationEvidence:
    evidence_id: str
    source_owner: str
    connection_id: str
    source_revision: str
    host: str
    scope: str
    native_name: str
    target_id: str
    whole_file_digest: str
    owned_leaf_digests: tuple[tuple[str, str], ...]
    provenance_reference: str
    retiring_writer_handoff: str
    schema: str = MIGRATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != MIGRATION_SCHEMA:
            raise RegistrarError(ReasonCode.UNSUPPORTED_SCHEMA)
        validate_hex(self.target_id)
        validate_hex(self.whole_file_digest, allow_absent=True)
        paths = [path for path, _digest in self.owned_leaf_digests]
        validate_pointer_set(paths)
        for _path, digest in self.owned_leaf_digests:
            validate_hex(digest, allow_absent=True)

    def to_record(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "evidence_id": self.evidence_id,
            "source_owner": self.source_owner,
            "connection_id": self.connection_id,
            "source_revision": self.source_revision,
            "host": self.host,
            "scope": self.scope,
            "native_name": self.native_name,
            "target_id": self.target_id,
            "whole_file_digest": self.whole_file_digest,
            "owned_leaf_digests": dict(self.owned_leaf_digests),
            "provenance_reference": self.provenance_reference,
            "retiring_writer_handoff": self.retiring_writer_handoff,
        }

    @property
    def digest(self) -> str:
        return digest_value(self.to_record())


PolicyValidator = Callable[[Mapping[str, Any], Mapping[str, Any]], ReasonCode | None]


@dataclass(frozen=True, slots=True)
class RegistrationContext:
    source_owner: str
    connection_id: str
    source_revision: str
    definition_digest: str
    host: str
    surface: str
    build: str
    scope: str
    mapping_version: str
    mapping_digest: str
    config_path: Path = field(repr=False)
    state_directory: Path = field(repr=False)
    auth_binding: AuthBinding | None = field(default=None, repr=False)
    writer_window: WriterWindow | None = field(default=None, repr=False)
    migration_evidence: MigrationEvidence | None = field(default=None, repr=False)
    policy_validator_id: str | None = None
    schema: str = CONTEXT_SCHEMA
    maintenance_evidence: MaintenanceEvidence | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.schema not in {CONTEXT_SCHEMA, "kp-mcp/registration-context/v2"}:
            raise RegistrarError(ReasonCode.UNSUPPORTED_SCHEMA)
        if self.schema == CONTEXT_SCHEMA:
            if self.maintenance_evidence is not None or (self.writer_window and self.writer_window.schema != WRITER_SCHEMA):
                raise RegistrarError(ReasonCode.UNSUPPORTED_SCHEMA)
        else:
            evidence, window = self.maintenance_evidence, self.writer_window
            if (not isinstance(evidence, MaintenanceEvidence) or window is None
                or window.schema != "kp-mcp/writer-window/v2"
                or window.maintenance_evidence_digest != evidence.digest
                or window.acquisition_reference != evidence.maintenance_id
                or window.issuer_source_revision != evidence.issuer_source_revision
                or window.config_target_id != evidence.config_target_id
                or window.state_target_id != evidence.state_target_id
                or window.acquired_at != evidence.acquired_at or window.expires_at != evidence.expires_at):
                raise RegistrarError(ReasonCode.CONCURRENCY_UNQUALIFIED)
        for value in (
            self.source_owner,
            self.connection_id,
            self.source_revision,
            self.host,
            self.surface,
            self.build,
            self.scope,
            self.mapping_version,
        ):
            validate_identifier(value)
        validate_hex(self.definition_digest)
        validate_hex(self.mapping_digest)
        if not self.config_path.is_absolute() or not self.state_directory.is_absolute():
            raise ValueError("context paths must be absolute")
        if self.auth_binding and (
            self.auth_binding.host != self.host
            or self.auth_binding.surface != self.surface
            or self.auth_binding.scope != self.scope
        ):
            raise RegistrarError(
                ReasonCode.AUTH_BINDING_CONFLICT,
                target_id=bounded_id(str(self.config_path)),
            )

    @property
    def target_id(self) -> str:
        return bounded_id(str(self.config_path))

    def validate_definition(self, definition: RegistrationDefinition) -> None:
        if (
            self.source_owner != definition.source_owner
            or self.connection_id != definition.connection_id
            or self.source_revision != definition.source_revision
            or self.definition_digest != definition.digest
        ):
            raise RegistrarError(ReasonCode.OWNER_CONFLICT, target_id=self.target_id)
        if (
            self.auth_binding is not None
            and self.auth_binding.target_origin_digest
            != definition.target_origin_digest
        ):
            raise RegistrarError(
                ReasonCode.AUTH_BINDING_CONFLICT, target_id=self.target_id
            )

    def to_record(self) -> dict[str, Any]:
        return {
            **maintenance_provenance(self),
            "schema": self.schema,
            "source_owner": self.source_owner,
            "connection_id": self.connection_id,
            "source_revision": self.source_revision,
            "definition_digest": self.definition_digest,
            "host": self.host,
            "surface": self.surface,
            "build": self.build,
            "scope": self.scope,
            "mapping_version": self.mapping_version,
            "mapping_digest": self.mapping_digest,
            **({"maintenance_evidence": self.maintenance_evidence.to_record()} if self.maintenance_evidence else {}),
            "config_path": str(self.config_path),
            "state_directory": str(self.state_directory),
            "auth_binding": self.auth_binding.to_record() if self.auth_binding else None,
            "writer_window": self.writer_window.to_record() if self.writer_window else None,
            "migration_evidence": (
                self.migration_evidence.to_record() if self.migration_evidence else None
            ),
            "policy_validator_id": self.policy_validator_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **maintenance_provenance(self),
            "schema": self.schema,
            "source_owner": self.source_owner,
            "connection_id": self.connection_id,
            "source_revision": self.source_revision,
            "definition_digest": self.definition_digest,
            "host": self.host,
            "surface": self.surface,
            "build": self.build,
            "scope": self.scope,
            "mapping_version": self.mapping_version,
            "mapping_digest": self.mapping_digest,
            "target_id": self.target_id,
            "auth_binding_digest": (
                self.auth_binding.digest if self.auth_binding else "not_applicable"
            ),
            "writer_window_digest": (
                self.writer_window.digest if self.writer_window else None
            ),
            "migration_evidence_digest": (
                self.migration_evidence.digest if self.migration_evidence else None
            ),
            "policy_validator_id": self.policy_validator_id,
        }


def context_from_record(record: Mapping[str, Any]) -> RegistrationContext:
    """Reconstruct closed data only; runtime validators never come from storage."""
    values = dict(record)
    for name in ("concurrency_claim", "writer_window_digest", "maintenance_evidence_digest"):
        values.pop(name, None)
    values["config_path"] = Path(values["config_path"])
    values["state_directory"] = Path(values["state_directory"])
    if values.get("writer_window") is not None:
        window = dict(values["writer_window"])
        window["acquired_at"] = parse_iso(window["acquired_at"])
        window["expires_at"] = parse_iso(window["expires_at"])
        values["writer_window"] = WriterWindow(**window)
    if values.get("maintenance_evidence") is not None:
        values["maintenance_evidence"] = MaintenanceEvidence.from_record(values["maintenance_evidence"])
    if values.get("auth_binding") is not None:
        auth = dict(values["auth_binding"])
        auth["kind"] = AuthKind(auth["kind"])
        auth["allowed_native_fields"] = tuple(auth["allowed_native_fields"])
        values["auth_binding"] = AuthBinding(**auth)
    if values.get("migration_evidence") is not None:
        migration = dict(values["migration_evidence"])
        migration["owned_leaf_digests"] = tuple(migration["owned_leaf_digests"].items())
        values["migration_evidence"] = MigrationEvidence(**migration)
    context = RegistrationContext(**values)
    if _canonical(context.to_record()) != record:
        raise ValueError("noncanonical or open registration context")
    return context


@dataclass(frozen=True, slots=True)
class Observation:
    status: ObservationStatus
    timestamp: datetime
    host: str
    surface: str
    build: str
    connection_revision: str
    evidence_reference: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "timestamp": isoformat(self.timestamp),
            "host": self.host,
            "surface": self.surface,
            "build": self.build,
            "connection_revision": self.connection_revision,
            "evidence_reference": self.evidence_reference,
        }


@dataclass(frozen=True, slots=True)
class Observations:
    registered: Observation
    enabled: Observation
    authenticated: Observation
    tools_discovered: Observation
    safe_read: Observation

    @classmethod
    def with_registered(
        cls, context: RegistrationContext, status: ObservationStatus
    ) -> "Observations":
        now = utc_now()

        def item(item_status: ObservationStatus) -> Observation:
            return Observation(
                status=item_status,
                timestamp=now,
                host=context.host,
                surface=context.surface,
                build=context.build,
                connection_revision=context.source_revision,
            )

        return cls(
            registered=item(status),
            enabled=item(ObservationStatus.UNKNOWN),
            authenticated=item(ObservationStatus.UNKNOWN),
            tools_discovered=item(ObservationStatus.UNKNOWN),
            safe_read=item(ObservationStatus.UNKNOWN),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "registered": self.registered.to_dict(),
            "enabled": self.enabled.to_dict(),
            "authenticated": self.authenticated.to_dict(),
            "tools_discovered": self.tools_discovered.to_dict(),
            "safe_read": self.safe_read.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class Inspection:
    present: bool
    ownership: OwnershipStatus
    owned_projection_match: bool | None
    reason_codes: tuple[ReasonCode, ...]
    observations: Observations
    schema: str = INSPECTION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "present": self.present,
            "ownership": self.ownership.value,
            "owned_projection_match": self.owned_projection_match,
            "reason_codes": [code.value for code in self.reason_codes],
            "observations": self.observations.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class OwnedLeafAction:
    path: str
    action: str

    def __post_init__(self) -> None:
        validate_pointer_set((self.path,))
        if self.action not in {"add", "retain", "replace", "remove"}:
            raise ValueError("unknown leaf action")

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "action": self.action}


@dataclass(frozen=True, slots=True)
class PreviewPrivate:
    config_preimage: bytes | None = field(repr=False)
    config_postimage: bytes | None = field(repr=False)
    receipt_preimage: bytes | None = field(repr=False)
    receipt_postimage: bytes | None = field(repr=False)
    context: RegistrationContext = field(repr=False)
    definition: RegistrationDefinition | None = field(repr=False)
    logical_path: Path = field(repr=False)
    resolved_path: Path = field(repr=False)
    link_binding: Mapping[str, Any] = field(repr=False)
    original_operation_id: str | None = None
    recovery_disposition: RecoveryDisposition | None = None


@dataclass(frozen=True, slots=True)
class Preview:
    operation_id: str
    action: Action
    definition_digest: str
    source_owner: str
    source_revision: str
    connection_id: str
    adapter_version: str
    mapping_digest: str
    host: str
    surface: str
    build: str
    scope: str
    target_id: str
    config_preimage: str
    receipt_preimage: str
    journal_preimage: str
    desired_config: str
    desired_receipt: str
    owned_leaf_actions: tuple[OwnedLeafAction, ...]
    preserved_paths: tuple[str, ...]
    conflicts: tuple[ReasonCode, ...]
    private_recovery_reference: str | None
    auth_binding_digest: str
    writer_window_digest: str | None
    expires_at: datetime
    preview_digest: str
    config_changed: bool
    state_changed: bool
    _private: PreviewPrivate = field(repr=False)
    schema: str = PREVIEW_SCHEMA

    @property
    def ready(self) -> bool:
        return not self.conflicts

    def digest_payload(self) -> dict[str, Any]:
        return {
            **maintenance_provenance(self._private.context),
            "schema": self.schema,
            "operation_id": self.operation_id,
            "action": self.action.value,
            "definition_digest": self.definition_digest,
            "source_owner": self.source_owner,
            "source_revision": self.source_revision,
            "connection_id": self.connection_id,
            "adapter_version": self.adapter_version,
            "mapping_digest": self.mapping_digest,
            "host": self.host,
            "surface": self.surface,
            "build": self.build,
            "scope": self.scope,
            "target_id": self.target_id,
            "config_preimage": self.config_preimage,
            "receipt_preimage": self.receipt_preimage,
            "journal_preimage": self.journal_preimage,
            "desired_config": self.desired_config,
            "desired_receipt": self.desired_receipt,
            "owned_leaf_actions": [item.to_dict() for item in self.owned_leaf_actions],
            "preserved_paths": list(self.preserved_paths),
            "conflicts": [code.value for code in self.conflicts],
            "private_recovery_reference": self.private_recovery_reference,
            "auth_binding_digest": self.auth_binding_digest,
            "writer_window_digest": self.writer_window_digest,
            "expires_at": self.expires_at,
            "config_changed": self.config_changed,
            "state_changed": self.state_changed,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**_canonical(self.digest_payload()), "preview_digest": self.preview_digest}


@dataclass(frozen=True, slots=True)
class ApprovalAudience:
    source_owner: str
    connection_id: str
    host: str
    scope: str
    target_id: str
    action: Action

    def to_record(self) -> dict[str, str]:
        return {
            "source_owner": self.source_owner,
            "connection_id": self.connection_id,
            "host": self.host,
            "scope": self.scope,
            "target_id": self.target_id,
            "action": self.action.value,
        }


@dataclass(frozen=True, slots=True)
class PreparedOperation:
    record_id: str
    payload_digest: str
    operation_id: str
    action_digest: str
    action: Action
    audience: ApprovalAudience
    state_changed: bool
    config_changed: bool
    expires_at: datetime
    _state_directory: Path = field(repr=False)
    _context: RegistrationContext = field(repr=False)
    _definition: RegistrationDefinition | None = field(repr=False)
    schema: str = PREPARED_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            **maintenance_provenance(self._context),
            "schema": self.schema,
            "record_id": self.record_id,
            "payload_digest": self.payload_digest,
            "operation_id": self.operation_id,
            "action_digest": self.action_digest,
            "action": self.action.value,
            "audience": self.audience.to_record(),
            "state_changed": self.state_changed,
            "config_changed": self.config_changed,
            "expires_at": isoformat(self.expires_at),
        }


@dataclass(frozen=True, slots=True)
class Approval:
    audience: ApprovalAudience
    operation_id: str
    action_digest: str
    prepared_payload_digest: str
    issuer_authority: str
    issuer_reference: str
    issued_at: datetime
    expires_at: datetime
    choice: str = "apply"
    schema: str = APPROVAL_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != APPROVAL_SCHEMA:
            raise RegistrarError(ReasonCode.UNSUPPORTED_SCHEMA)

    def to_record(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "audience": self.audience.to_record(),
            "operation_id": self.operation_id,
            "action_digest": self.action_digest,
            "prepared_payload_digest": self.prepared_payload_digest,
            "issuer_authority": self.issuer_authority,
            "issuer_reference": self.issuer_reference,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "choice": self.choice,
        }

    def to_dict(self) -> dict[str, Any]:
        return _canonical(self.to_record())


@dataclass(frozen=True, slots=True)
class Result:
    operation_id: str
    action_digest: str
    action: Action
    outcome: Outcome
    config_changed: bool
    state_changed: bool
    verified_postimage: str | None
    receipt_id: str | None
    recovery_id: str | None
    reason_codes: tuple[ReasonCode, ...]
    conflicts: tuple[ReasonCode, ...]
    next_action: str
    observations: Observations
    schema: str = RESULT_SCHEMA
    concurrency_claim: str | None = None
    writer_window_digest: str | None = None
    maintenance_evidence_digest: str | None = None

    def __post_init__(self) -> None:
        if self.schema == RESULT_SCHEMA:
            if any(v is not None for v in (self.concurrency_claim, self.writer_window_digest, self.maintenance_evidence_digest)):
                raise RegistrarError(ReasonCode.UNSUPPORTED_SCHEMA)
        elif self.schema == "kp-mcp/registrar-result/v2" and self.concurrency_claim == "coordinated":
            validate_hex(self.writer_window_digest)
            validate_hex(self.maintenance_evidence_digest)
        else:
            raise RegistrarError(ReasonCode.UNSUPPORTED_SCHEMA)

    def to_dict(self) -> dict[str, Any]:
        return {
            **({"concurrency_claim": self.concurrency_claim, "writer_window_digest": self.writer_window_digest,
                "maintenance_evidence_digest": self.maintenance_evidence_digest} if self.schema.endswith("/v2") else {}),
            "schema": self.schema,
            "operation_id": self.operation_id,
            "action_digest": self.action_digest,
            "action": self.action.value,
            "outcome": self.outcome.value,
            "config_changed": self.config_changed,
            "state_changed": self.state_changed,
            "verified_postimage": self.verified_postimage,
            "receipt_id": self.receipt_id,
            "recovery_id": self.recovery_id,
            "reason_codes": [code.value for code in self.reason_codes],
            "conflicts": [code.value for code in self.conflicts],
            "next_action": self.next_action,
            "observations": self.observations.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class OperationRef:
    kind: OperationRefKind
    operation_id: str
    target_id: str
    _state_directory: Path = field(repr=False)

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "operation_id": self.operation_id,
            "target_id": self.target_id,
        }


@dataclass(frozen=True, slots=True)
class FixtureRegistration:
    root: Path
    config_path: Path
    state_directory: Path
    context: RegistrationContext


@dataclass(frozen=True, slots=True)
class BatchPreviewRequest:
    registrar: Any = field(repr=False)
    path: Path
    definition: RegistrationDefinition
    context: RegistrationContext


@dataclass(frozen=True, slots=True)
class BatchPreflight:
    previews: tuple[Preview, ...]
    ready: bool


@dataclass(frozen=True, slots=True)
class BatchApplyRequest:
    registrar: Any = field(repr=False)
    path: Path
    definition: RegistrationDefinition | None
    context: RegistrationContext
    prepared: PreparedOperation
    approval: Approval
    action: Action = Action.REGISTER


def new_operation_id() -> str:
    return str(uuid.uuid4())


def iter_mapping_leaves(value: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, Mapping):
        if not value:
            yield prefix, {}
            return
        for key in sorted(value):
            child = f"{prefix}/{pointer_escape(str(key))}"
            yield from iter_mapping_leaves(value[key], child)
        return
    yield prefix, value
