"""Fixture-only writer-window qualification.

No live Cursor, Codex, or Claude writer mechanism is qualified in registrar-v1.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from kp_mcp_bootstrap.errors import ReasonCode, RegistrarError

from .contracts import (
    FixtureRegistration,
    MAX_PREVIEW_SECONDS,
    RegistrationContext,
    RegistrationDefinition,
    WriterWindow,
    bounded_id,
    digest_value,
    utc_now,
)


FIXTURE_QUALIFICATION_ID = "kp-mcp/fixture-isolation/v1"
FIXTURE_QUALIFICATION_DIGEST = digest_value(
    {
        "qualification_id": FIXTURE_QUALIFICATION_ID,
        "mechanism": "fixture-isolation",
        "admission": "owned-os-temp-child-no-host-discovery-exact-targets",
    }
)


@dataclass(frozen=True, slots=True)
class _ActiveFixture:
    pid: int
    root: Path
    host: str
    surface: str
    build: str
    scope: str
    config_target_id: str
    state_target_id: str
    registrar_mapping_digest: str
    writer_window_digest: str


_ACTIVE_FIXTURES: dict[str, _ActiveFixture] = {}


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _assert_private_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError:
        raise RegistrarError(ReasonCode.PERMISSION_DENIED) from None
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RegistrarError(ReasonCode.PERMISSION_DENIED)
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise RegistrarError(ReasonCode.PERMISSION_DENIED)


def _assert_no_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current = current / component
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise RegistrarError(ReasonCode.PERMISSION_DENIED) from None
        if stat.S_ISLNK(info.st_mode):
            raise RegistrarError(ReasonCode.TARGET_CHANGED)


def _contains_git_marker(path: Path) -> bool:
    current = path
    while True:
        if (current / ".git").exists() or (current / ".git").is_symlink():
            return True
        if current == current.parent:
            return False
        current = current.parent


def _validate_fixture_base(base: Path) -> Path:
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        resolved = base.resolve(strict=True)
    except OSError:
        raise RegistrarError(ReasonCode.PERMISSION_DENIED) from None
    if not _is_relative_to(resolved, temp_root):
        raise RegistrarError(ReasonCode.CONCURRENCY_UNQUALIFIED)
    _assert_no_symlink_components(resolved)
    _assert_private_directory(resolved)
    if _contains_git_marker(resolved):
        raise RegistrarError(ReasonCode.STATE_INVALID)
    return resolved


@contextmanager
def fixture_context(
    registrar: Any,
    definition: RegistrationDefinition,
    *,
    fixture_root: Path | None = None,
    config_name: str | None = None,
    scope: str = "user",
    auth_binding: Any = None,
    expires_in: int = MAX_PREVIEW_SECONDS,
) -> Iterator[FixtureRegistration]:
    """Create an owned, unexposed disposable fixture and exact bound context."""

    if expires_in <= 0 or expires_in > MAX_PREVIEW_SECONDS:
        raise ValueError("fixture writer lifetime must be between 1 and 600 seconds")
    base = (
        _validate_fixture_base(Path(fixture_root))
        if fixture_root is not None
        else _validate_fixture_base(Path(tempfile.gettempdir()))
    )
    child = Path(tempfile.mkdtemp(prefix="kp-mcp-registrar-", dir=base))
    try:
        child.chmod(0o700)
        _assert_private_directory(child)
        if _contains_git_marker(child):
            raise RegistrarError(ReasonCode.STATE_INVALID)
        state_directory = child / "state"
        state_directory.mkdir(mode=0o700)
        config_path = child / (config_name or registrar.FIXTURE_CONFIG_NAME)
        _assert_no_symlink_components(config_path.parent)
        config_target_id = bounded_id(str(config_path))
        state_target_id = bounded_id(str(state_directory))
        acquisition_reference = str(uuid.uuid4())
        now = utc_now()
        window = WriterWindow(
            qualification_id=FIXTURE_QUALIFICATION_ID,
            qualification_digest=FIXTURE_QUALIFICATION_DIGEST,
            issuer_owner="KleinPerkins/kp-mcp",
            issuer_source_revision=definition.source_revision,
            mechanism="fixture-isolation",
            host="fixture",
            surface=registrar.SURFACE,
            build=registrar.FIXTURE_BUILD,
            mapping_digest=registrar.mapping_digest,
            config_target_id=config_target_id,
            state_target_id=state_target_id,
            acquisition_reference=acquisition_reference,
            acquired_at=now,
            expires_at=now + timedelta(seconds=expires_in),
            release_method="fixture-context-exit",
        )
        _ACTIVE_FIXTURES[acquisition_reference] = _ActiveFixture(
            pid=os.getpid(),
            root=child,
            host="fixture",
            surface=registrar.SURFACE,
            build=registrar.FIXTURE_BUILD,
            scope=scope,
            config_target_id=config_target_id,
            state_target_id=state_target_id,
            registrar_mapping_digest=registrar.mapping_digest,
            writer_window_digest=window.digest,
        )
        context = RegistrationContext(
            source_owner=definition.source_owner,
            connection_id=definition.connection_id,
            source_revision=definition.source_revision,
            definition_digest=definition.digest,
            host="fixture",
            surface=registrar.SURFACE,
            build=registrar.FIXTURE_BUILD,
            scope=scope,
            mapping_version=registrar.MAPPING_VERSION,
            mapping_digest=registrar.mapping_digest,
            config_path=config_path,
            state_directory=state_directory,
            auth_binding=auth_binding,
            writer_window=window,
            policy_validator_id=registrar.policy_validator_id,
        )
        yield FixtureRegistration(
            root=child,
            config_path=config_path,
            state_directory=state_directory,
            context=context,
        )
    finally:
        _ACTIVE_FIXTURES.pop(locals().get("acquisition_reference", ""), None)
        if child.exists():
            try:
                shutil.rmtree(child)
            except OSError:
                raise RegistrarError(ReasonCode.WRITER_RELEASE_FAILED) from None


def renew_fixture_context(
    context: RegistrationContext,
    *,
    expires_in: int = MAX_PREVIEW_SECONDS,
) -> RegistrationContext:
    """Reissue writer evidence for the same still-active disposable fixture."""

    if expires_in <= 0 or expires_in > MAX_PREVIEW_SECONDS:
        raise ValueError("fixture writer lifetime must be between 1 and 600 seconds")
    window = context.writer_window
    if (
        window is None
        or window.mechanism != "fixture-isolation"
        or window.qualification_id != FIXTURE_QUALIFICATION_ID
        or window.qualification_digest != FIXTURE_QUALIFICATION_DIGEST
    ):
        raise RegistrarError(
            ReasonCode.CONCURRENCY_UNQUALIFIED, target_id=context.target_id
        )
    active = _ACTIVE_FIXTURES.get(window.acquisition_reference)
    if (
        active is None
        or active.pid != os.getpid()
        or window.digest != active.writer_window_digest
        or active.host != context.host
        or active.surface != context.surface
        or active.build != context.build
        or active.scope != context.scope
        or window.host != context.host
        or window.surface != context.surface
        or window.build != context.build
        or active.config_target_id != window.config_target_id
        or active.state_target_id != window.state_target_id
        or active.registrar_mapping_digest != window.mapping_digest
        or window.mapping_digest != context.mapping_digest
        or window.config_target_id != bounded_id(str(context.config_path))
        or window.state_target_id != bounded_id(str(context.state_directory))
    ):
        raise RegistrarError(
            ReasonCode.CONCURRENCY_UNQUALIFIED, target_id=context.target_id
        )
    try:
        root = active.root.resolve(strict=True)
    except OSError:
        raise RegistrarError(
            ReasonCode.CONCURRENCY_UNQUALIFIED, target_id=context.target_id
        ) from None
    config = context.config_path.absolute()
    state = context.state_directory.absolute()
    if not _is_relative_to(config, root) or not _is_relative_to(state, root):
        raise RegistrarError(
            ReasonCode.CONCURRENCY_UNQUALIFIED, target_id=context.target_id
        )
    _assert_private_directory(root)
    _assert_private_directory(state)
    _assert_no_symlink_components(config.parent)
    _assert_no_symlink_components(state)
    if _contains_git_marker(root):
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=context.target_id)
    now = utc_now()
    renewed = replace(
        window,
        acquired_at=now,
        expires_at=now + timedelta(seconds=expires_in),
    )
    _ACTIVE_FIXTURES[window.acquisition_reference] = replace(
        active, writer_window_digest=renewed.digest
    )
    return replace(context, writer_window=renewed)


def validate_writer_window(
    context: RegistrationContext,
    *,
    resolved_target: Path | None = None,
    checked_at: datetime | None = None,
    maintenance_validator: object | None = None,
) -> None:
    """Reject every live or fabricated writer window."""

    if context.maintenance_evidence is not None:
        from .maintenance import validate_runtime
        validate_runtime(context, maintenance_validator, checked_at=checked_at)
        return
    window = context.writer_window
    if (
        window is None
        or window.mechanism != "fixture-isolation"
        or window.qualification_id != FIXTURE_QUALIFICATION_ID
        or window.qualification_digest != FIXTURE_QUALIFICATION_DIGEST
    ):
        raise RegistrarError(
            ReasonCode.CONCURRENCY_UNQUALIFIED, target_id=context.target_id
        )
    active = _ACTIVE_FIXTURES.get(window.acquisition_reference)
    if (
        active is None
        or active.pid != os.getpid()
        or active.host != context.host
        or active.surface != context.surface
        or active.build != context.build
        or active.scope != context.scope
        or window.host != context.host
        or window.surface != context.surface
        or window.build != context.build
        or window.digest != active.writer_window_digest
        or active.config_target_id != window.config_target_id
        or active.state_target_id != window.state_target_id
        or active.registrar_mapping_digest != window.mapping_digest
        or window.mapping_digest != context.mapping_digest
        or window.config_target_id != bounded_id(str(context.config_path))
        or window.state_target_id != bounded_id(str(context.state_directory))
        or (checked_at or utc_now()) > window.expires_at
    ):
        raise RegistrarError(
            ReasonCode.CONCURRENCY_UNQUALIFIED, target_id=context.target_id
        )
    try:
        root = active.root.resolve(strict=True)
    except OSError:
        raise RegistrarError(
            ReasonCode.CONCURRENCY_UNQUALIFIED, target_id=context.target_id
        ) from None
    config = context.config_path.absolute()
    state = context.state_directory.absolute()
    if not _is_relative_to(config, root) or not _is_relative_to(state, root):
        raise RegistrarError(
            ReasonCode.CONCURRENCY_UNQUALIFIED, target_id=context.target_id
        )
    if resolved_target is not None:
        try:
            resolved = resolved_target.resolve(strict=resolved_target.exists())
        except OSError:
            raise RegistrarError(
                ReasonCode.CONCURRENCY_UNQUALIFIED, target_id=context.target_id
            ) from None
        if not _is_relative_to(resolved, root):
            raise RegistrarError(
                ReasonCode.CONCURRENCY_UNQUALIFIED, target_id=context.target_id
            )
        _assert_no_symlink_components(resolved)
    _assert_private_directory(root)
    _assert_private_directory(state)
    _assert_no_symlink_components(config.parent)
    _assert_no_symlink_components(state)
    if _contains_git_marker(root):
        raise RegistrarError(ReasonCode.STATE_INVALID, target_id=context.target_id)
