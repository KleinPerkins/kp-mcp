"""Target identity, durable preflight, and writer-race contracts."""

from __future__ import annotations

import getpass
import json
import multiprocessing
import os
import stat
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import kp_mcp_bootstrap.registrars.state as registrar_state
import pytest

from kp_mcp_bootstrap.registrars import (
    Action,
    BatchApplyRequest,
    CursorRegistrar,
    Outcome,
    ReasonCode,
    RecoveryDisposition,
    RegistrarError,
    RegistrationDefinition,
    SourceIdentity,
    apply_batch,
    fixture_approval,
    fixture_context,
    operation_ref,
    preflight_apply_batch,
)
from kp_mcp_bootstrap.registrars.contracts import canonical_json_bytes, digest_value
from kp_mcp_bootstrap.registrars.state import StateStore


def _definition(name: str = "txn-fixture") -> RegistrationDefinition:
    return RegistrationDefinition.stdio(
        SourceIdentity(
            source_owner="KleinPerkins/kp-mcp",
            connection_id=f"kp-mcp:{name}",
            source_revision="d" * 40,
            native_name=name,
        ),
        command=f"/opt/fixtures/{name}",
        args=("mcp",),
    )


def _child_apply(registrar, prepared, approval, queue) -> None:
    try:
        registrar.apply(prepared, approval)
    except RegistrarError as error:
        queue.put(error.code.value)
    else:
        queue.put("unexpected-success")


def test_mode_and_stable_leaf_symlink_are_preserved(tmp_path: Path) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        real = fixture.root / "real.json"
        real.write_text(json.dumps({"mcpServers": {"sibling": {"command": "/x"}}}))
        real.chmod(0o640)
        fixture.config_path.symlink_to(real)
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        result = registrar.apply(prepared, fixture_approval(prepared))
        assert result.config_changed
        assert fixture.config_path.is_symlink()
        assert real.stat().st_mode & 0o777 == 0o640
        assert "sibling" in json.loads(real.read_text())["mcpServers"]


def test_retargeted_or_dangling_leaf_symlink_refuses(tmp_path: Path) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        first = fixture.root / "first.json"
        second = fixture.root / "second.json"
        initial = json.dumps({"mcpServers": {}})
        first.write_text(initial)
        second.write_text(initial)
        fixture.config_path.symlink_to(first)
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        fixture.config_path.unlink()
        fixture.config_path.symlink_to(second)
        with pytest.raises(RegistrarError) as caught:
            registrar.apply(prepared, fixture_approval(prepared))
        assert caught.value.code is ReasonCode.TARGET_CHANGED
        assert first.read_text() == initial
        assert second.read_text() == initial
        fixture.config_path.unlink()
        fixture.config_path.symlink_to(fixture.root / "missing.json")
        with pytest.raises(RegistrarError) as caught:
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        assert caught.value.code is ReasonCode.TARGET_CHANGED


def test_leaf_symlink_binds_resolved_target_ancestor_identity(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        resolved_parent = fixture.root / "resolved"
        resolved_parent.mkdir()
        target = resolved_parent / "real.json"
        original = json.dumps({"mcpServers": {}})
        target.write_text(original)
        fixture.config_path.symlink_to(Path("resolved") / "real.json")
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )

        old_parent = fixture.root / "old-resolved"
        resolved_parent.rename(old_parent)
        resolved_parent.mkdir()
        (old_parent / "real.json").rename(target)
        old_parent.rmdir()

        with pytest.raises(RegistrarError) as caught:
            registrar.apply(prepared, fixture_approval(prepared))
        assert caught.value.code is ReasonCode.TARGET_CHANGED
        assert target.read_text() == original


def test_fixture_leaf_symlink_cannot_escape_disposable_root(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    external = tmp_path / "outside-active-fixture.json"
    original = json.dumps({"mcpServers": {"external": {"command": "/keep"}}})
    external.write_text(original)
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        fixture.config_path.symlink_to(external)
        preview = registrar.preview(
            fixture.config_path, definition, context=fixture.context
        )
        with pytest.raises(RegistrarError) as caught:
            registrar.prepare(preview)
        assert caught.value.code is ReasonCode.CONCURRENCY_UNQUALIFIED
        assert external.read_text() == original


def test_hardlinked_target_and_private_state_file_refuse(tmp_path: Path) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        fixture.config_path.write_text(json.dumps({"mcpServers": {}}))
        alias = fixture.root / "alias.json"
        os.link(fixture.config_path, alias)
        with pytest.raises(RegistrarError) as caught:
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        assert caught.value.code is ReasonCode.TARGET_CHANGED
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        record = fixture.state_directory / f"prepared-{prepared.record_id}.json"
        os.link(record, fixture.state_directory / "record-hardlink.json")
        with pytest.raises(RegistrarError) as caught:
            registrar.apply(prepared, fixture_approval(prepared))
        assert caught.value.code is ReasonCode.STATE_INVALID
        assert not fixture.config_path.exists()


def test_wrong_mode_or_git_contained_state_refuses(tmp_path: Path) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        fixture.state_directory.chmod(0o755)
        with pytest.raises(RegistrarError) as caught:
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        assert caught.value.code in {
            ReasonCode.STATE_INVALID,
            ReasonCode.PERMISSION_DENIED,
        }
    git_base = tmp_path / "git-contained"
    git_base.mkdir(mode=0o700)
    (git_base / ".git").mkdir()
    with pytest.raises(RegistrarError) as caught:
        with fixture_context(registrar, definition, fixture_root=git_base):
            pass
    assert caught.value.code is ReasonCode.STATE_INVALID


def test_wrong_uid_state_root_refuses_via_safe_stat_injection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        original_lstat = Path.lstat

        def wrong_owner(path: Path):
            observed = original_lstat(path)
            if path.absolute() == fixture.state_directory.absolute():
                return SimpleNamespace(
                    st_mode=observed.st_mode,
                    st_uid=observed.st_uid + 1,
                )
            return observed

        with monkeypatch.context() as patch:
            patch.setattr(Path, "lstat", wrong_owner)
            with pytest.raises(RegistrarError) as caught:
                StateStore(fixture.context)
        assert caught.value.code is ReasonCode.STATE_INVALID
        assert not fixture.config_path.exists()


def test_state_root_symlink_refuses_before_config_write(tmp_path: Path) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        real_state = fixture.root / "state-real"
        fixture.state_directory.rename(real_state)
        fixture.state_directory.symlink_to(real_state.name)
        with pytest.raises(RegistrarError) as caught:
            StateStore(fixture.context)
        assert caught.value.code is ReasonCode.TARGET_CHANGED
        assert not fixture.config_path.exists()


def test_forked_writer_cannot_reuse_fixture_qualification(tmp_path: Path) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        approval = fixture_approval(prepared)
        fork = multiprocessing.get_context("fork")
        queue = fork.Queue()
        process = fork.Process(
            target=_child_apply,
            args=(registrar, prepared, approval, queue),
        )
        process.start()
        process.join(10)
        assert process.exitcode == 0
        assert queue.get(timeout=2) == ReasonCode.CONCURRENCY_UNQUALIFIED.value
        assert not fixture.config_path.exists()


def test_two_names_sharing_file_cannot_apply_stale_second_preimage(
    tmp_path: Path,
) -> None:
    first_registrar = CursorRegistrar()
    second_registrar = CursorRegistrar()
    first = _definition("first")
    second = _definition("second")
    with fixture_context(
        first_registrar, first, fixture_root=tmp_path
    ) as first_fixture:
        second_context = replace(
            first_fixture.context,
            connection_id=second.connection_id,
            source_revision=second.source_revision,
            definition_digest=second.digest,
        )
        first_prepared = first_registrar.prepare(
            first_registrar.preview(
                first_fixture.config_path, first, context=first_fixture.context
            )
        )
        second_prepared = second_registrar.prepare(
            second_registrar.preview(
                first_fixture.config_path, second, context=second_context
            )
        )
        assert first_registrar.apply(
            first_prepared, fixture_approval(first_prepared)
        ).config_changed
        with pytest.raises(RegistrarError) as caught:
            second_registrar.apply(
                second_prepared, fixture_approval(second_prepared)
            )
        assert caught.value.code in {
            ReasonCode.PREIMAGE_CHANGED,
            ReasonCode.TARGET_CHANGED,
        }
        data = json.loads(first_fixture.config_path.read_text())
        assert set(data["mcpServers"]) == {"first"}


@pytest.mark.parametrize("tamper", ["target", "target-and-operation"])
@pytest.mark.parametrize("entrypoint", ["preview", "inspect", "apply"])
def test_journal_identity_tampering_cannot_hide_unresolved_target_operation(
    tamper: str,
    entrypoint: str,
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        original = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        fresh_preview = registrar.preview(
            fixture.config_path, definition, context=fixture.context
        )
        fresh_prepared = registrar.prepare(fresh_preview)
        fresh_approval = fixture_approval(fresh_prepared)

        def interrupt(step: str) -> None:
            if step == "journal_prepared":
                raise RuntimeError("fixture durable-step interruption")

        registrar._fault = interrupt  # type: ignore[method-assign]
        assert registrar.apply(
            original, fixture_approval(original)
        ).outcome is Outcome.RECOVERY_REQUIRED
        registrar._fault = lambda _step: None  # type: ignore[method-assign]

        journal_path = StateStore(fixture.context).journal_path(
            original.operation_id
        )
        journal = json.loads(journal_path.read_bytes())
        journal["target_id"] = "0" * 64
        if tamper == "target-and-operation":
            journal["operation_id"] = "00000000-0000-4000-8000-000000000000"
        journal_path.write_bytes(canonical_json_bytes(journal))
        journal_path.chmod(0o600)
        before = {
            str(path.relative_to(fixture.root)): path.read_bytes()
            for path in fixture.root.rglob("*")
            if path.is_file()
        }
        calls = {
            "preview": lambda: registrar.preview(
                fixture.config_path, definition, context=fixture.context
            ),
            "inspect": lambda: registrar.inspect_registration(
                fixture.config_path, context=fixture.context
            ),
            "apply": lambda: registrar.apply(fresh_prepared, fresh_approval),
        }
        with pytest.raises(RegistrarError) as caught:
            calls[entrypoint]()
        assert caught.value.code is ReasonCode.JOURNAL_INVALID
        after = {
            str(path.relative_to(fixture.root)): path.read_bytes()
            for path in fixture.root.rglob("*")
            if path.is_file()
        }
        assert after == before


def test_terminal_replay_is_zero_change_and_refuses_divergent_target(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        approval = fixture_approval(prepared)
        first = registrar.apply(prepared, approval)
        assert first.outcome is Outcome.APPLIED
        replay = registrar.apply(prepared, approval)
        assert replay.outcome is Outcome.NO_CHANGE
        assert replay.config_changed is False
        assert replay.state_changed is False
        data = json.loads(fixture.config_path.read_text())
        data["mcpServers"][definition.native_name]["disabled"] = True
        fixture.config_path.write_text(json.dumps(data))
        before = fixture.config_path.read_bytes()
        with pytest.raises(RegistrarError) as caught:
            registrar.apply(prepared, approval)
        assert caught.value.code in {
            ReasonCode.PREIMAGE_CHANGED,
            ReasonCode.TARGET_CHANGED,
        }
        assert fixture.config_path.read_bytes() == before


@pytest.mark.parametrize("corruption", ["unknown-root", "forged-result"])
def test_terminal_replay_rejects_closed_schema_and_identity_corruption(
    corruption: str, tmp_path: Path
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        approval = fixture_approval(prepared)
        registrar.apply(prepared, approval)
        before = fixture.config_path.read_bytes()
        terminal_path = (
            fixture.state_directory / f"terminal-{prepared.operation_id}.json"
        )
        terminal = json.loads(terminal_path.read_bytes())
        if corruption == "unknown-root":
            terminal["unknown"] = True
        else:
            terminal["result"]["operation_id"] = "forged-operation"
        payload = dict(terminal)
        payload.pop("terminal_digest")
        terminal["terminal_digest"] = digest_value(payload)
        terminal_path.write_bytes(canonical_json_bytes(terminal))
        with pytest.raises(RegistrarError) as caught:
            registrar.apply(prepared, approval)
        assert caught.value.code is ReasonCode.STATE_INVALID
        assert fixture.config_path.read_bytes() == before


@pytest.mark.parametrize("entrypoint", ["preview", "operation-ref"])
@pytest.mark.parametrize(
    "corruption",
    [
        "result-flags",
        "observation",
        "target-binding",
        "phase-outcome",
        "receipt-id",
        "empty-terminal",
    ],
)
def test_terminal_admission_reuses_closed_replay_validation(
    corruption: str,
    entrypoint: str,
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        assert registrar.apply(
            prepared, fixture_approval(prepared)
        ).outcome is Outcome.APPLIED
        store = StateStore(fixture.context)
        terminal_path = store.terminal_path(prepared.operation_id)
        terminal = json.loads(terminal_path.read_bytes())
        if corruption == "result-flags":
            terminal["result"]["config_changed"] = "yes"
        elif corruption == "observation":
            terminal["result"]["observations"]["registered"]["host"] = (
                "forged-host"
            )
        elif corruption == "target-binding":
            terminal["target_binding"] = {
                "target_id": prepared.audience.target_id
            }
        elif corruption == "phase-outcome":
            terminal["result"]["outcome"] = "cancelled"
        elif corruption == "receipt-id":
            terminal["result"]["receipt_id"] = "0" * 64
        else:
            terminal = {}
        if terminal:
            payload = dict(terminal)
            payload.pop("terminal_digest")
            terminal["terminal_digest"] = digest_value(payload)
        terminal_path.write_bytes(canonical_json_bytes(terminal))
        terminal_path.chmod(0o600)
        before = {
            str(path.relative_to(fixture.root)): path.read_bytes()
            for path in fixture.root.rglob("*")
            if path.is_file()
        }
        calls = {
            "preview": lambda: registrar.preview(
                fixture.config_path, definition, context=fixture.context
            ),
            "operation-ref": lambda: operation_ref(prepared),
        }
        with pytest.raises(RegistrarError) as caught:
            calls[entrypoint]()
        assert caught.value.code is ReasonCode.STATE_INVALID
        after = {
            str(path.relative_to(fixture.root)): path.read_bytes()
            for path in fixture.root.rglob("*")
            if path.is_file()
        }
        assert after == before


def test_lock_symlink_never_changes_external_file_metadata(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    external = tmp_path / "external-lock-target"
    external.write_bytes(b"external")
    external.chmod(0o644)
    before = (external.read_bytes(), stat.S_IMODE(external.stat().st_mode))
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        lock_path = StateStore(fixture.context).lock_path(prepared.audience.target_id)
        lock_path.unlink()
        lock_path.symlink_to(external)
        with pytest.raises(RegistrarError) as caught:
            registrar.apply(prepared, fixture_approval(prepared))
        assert caught.value.code is ReasonCode.STATE_INVALID
        assert not fixture.config_path.exists()
    assert (external.read_bytes(), stat.S_IMODE(external.stat().st_mode)) == before


@pytest.mark.parametrize("kind", ["directory", "hardlink", "fifo"])
def test_lock_special_files_refuse_without_blocking_or_writing(
    kind: str, tmp_path: Path
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        lock_path = StateStore(fixture.context).lock_path(prepared.audience.target_id)
        lock_path.unlink()
        if kind == "directory":
            lock_path.mkdir()
        elif kind == "hardlink":
            external = fixture.root / "external-lock"
            external.write_bytes(b"")
            external.chmod(0o600)
            os.link(external, lock_path)
        else:
            os.mkfifo(lock_path, 0o600)
        with pytest.raises(RegistrarError) as caught:
            registrar.apply(prepared, fixture_approval(prepared))
        assert caught.value.code is ReasonCode.STATE_INVALID
        assert not fixture.config_path.exists()


def test_apply_batch_bounds_lock_race_and_skips_later_targets(
    tmp_path: Path,
) -> None:
    first_registrar = CursorRegistrar()
    second_registrar = CursorRegistrar()
    first_definition = _definition("batch-first")
    second_definition = _definition("batch-second")
    with fixture_context(
        first_registrar, first_definition, fixture_root=tmp_path
    ) as first_fixture:
        with fixture_context(
            second_registrar, second_definition, fixture_root=tmp_path
        ) as second_fixture:
            first_prepared = first_registrar.prepare(
                first_registrar.preview(
                    first_fixture.config_path,
                    first_definition,
                    context=first_fixture.context,
                )
            )
            second_prepared = second_registrar.prepare(
                second_registrar.preview(
                    second_fixture.config_path,
                    second_definition,
                    context=second_fixture.context,
                )
            )
            requests = (
                BatchApplyRequest(
                    registrar=first_registrar,
                    path=first_fixture.config_path,
                    definition=first_definition,
                    context=first_fixture.context,
                    prepared=first_prepared,
                    approval=fixture_approval(first_prepared),
                    action=Action.REGISTER,
                ),
                BatchApplyRequest(
                    registrar=second_registrar,
                    path=second_fixture.config_path,
                    definition=second_definition,
                    context=second_fixture.context,
                    prepared=second_prepared,
                    approval=fixture_approval(second_prepared),
                    action=Action.REGISTER,
                ),
            )
            preflight_apply_batch(requests)
            first_lock = StateStore(first_fixture.context).lock_path(
                first_prepared.audience.target_id
            )
            first_lock.unlink()
            first_lock.mkdir()
            results = apply_batch(requests)
            assert results[0].outcome is Outcome.FAILED
            assert results[0].reason_codes == (ReasonCode.STATE_INVALID,)
            assert results[1].outcome is Outcome.FAILED
            assert results[1].reason_codes == (ReasonCode.BATCH_NOT_STARTED,)
            assert not first_fixture.config_path.exists()
            assert not second_fixture.config_path.exists()


def test_flock_acquire_failure_is_bounded_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )

        def fail_flock(_descriptor: int, _operation: int) -> None:
            raise OSError("synthetic flock failure with private path")

        monkeypatch.setattr(registrar_state.fcntl, "flock", fail_flock)
        with pytest.raises(RegistrarError) as caught:
            registrar.apply(prepared, fixture_approval(prepared))
        assert caught.value.code is ReasonCode.STATE_INVALID
        assert "synthetic" not in str(caught.value)
        assert not fixture.config_path.exists()


def test_apply_batch_bounds_flock_acquire_failure_and_skips_later_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registrars = (CursorRegistrar(), CursorRegistrar())
    definitions = (_definition("flock-first"), _definition("flock-second"))
    with fixture_context(
        registrars[0], definitions[0], fixture_root=tmp_path
    ) as first:
        with fixture_context(
            registrars[1], definitions[1], fixture_root=tmp_path
        ) as second:
            fixtures = (first, second)
            prepared = tuple(
                registrar.prepare(
                    registrar.preview(
                        fixture.config_path,
                        definition,
                        context=fixture.context,
                    )
                )
                for registrar, definition, fixture in zip(
                    registrars, definitions, fixtures, strict=True
                )
            )
            requests = tuple(
                BatchApplyRequest(
                    registrar=registrar,
                    path=fixture.config_path,
                    definition=definition,
                    context=fixture.context,
                    prepared=operation,
                    approval=fixture_approval(operation),
                    action=Action.REGISTER,
                )
                for registrar, definition, fixture, operation in zip(
                    registrars, definitions, fixtures, prepared, strict=True
                )
            )

            def fail_flock(_descriptor: int, _operation: int) -> None:
                raise OSError("synthetic flock failure with private path")

            monkeypatch.setattr(registrar_state.fcntl, "flock", fail_flock)
            results = apply_batch(requests)
            assert results[0].outcome is Outcome.FAILED
            assert results[0].reason_codes == (ReasonCode.STATE_INVALID,)
            assert results[1].outcome is Outcome.FAILED
            assert results[1].reason_codes == (ReasonCode.BATCH_NOT_STARTED,)
            assert not first.config_path.exists()
            assert not second.config_path.exists()


def test_flock_release_failure_preserves_observed_partial_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        original_flock = registrar_state.fcntl.flock

        def fail_unlock(descriptor: int, operation: int) -> None:
            if operation == registrar_state.fcntl.LOCK_UN:
                raise OSError("synthetic unlock failure with private path")
            original_flock(descriptor, operation)

        monkeypatch.setattr(registrar_state.fcntl, "flock", fail_unlock)
        result = registrar.apply(prepared, fixture_approval(prepared))
        assert result.outcome is Outcome.RECOVERY_REQUIRED
        assert result.reason_codes == (ReasonCode.WRITER_RELEASE_FAILED,)
        assert result.config_changed is True
        assert result.state_changed is True
        assert fixture.config_path.exists()


def test_post_replace_fsync_failure_reports_observed_config_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        preview = registrar.preview(
            fixture.config_path, definition, context=fixture.context
        )
        desired = preview._private.config_postimage
        prepared = registrar.prepare(preview)
        original_fsync = registrar_state._fsync_directory

        def fail_target_parent(path: Path) -> None:
            if path == fixture.config_path.parent:
                raise OSError("fixture fsync failure")
            original_fsync(path)

        monkeypatch.setattr(registrar_state, "_fsync_directory", fail_target_parent)
        result = registrar.apply(prepared, fixture_approval(prepared))
        assert result.outcome is Outcome.RECOVERY_REQUIRED
        assert result.config_changed is True
        assert fixture.config_path.read_bytes() == desired


def test_prepare_state_fsync_failure_is_bounded_without_config_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        preview = registrar.preview(
            fixture.config_path, definition, context=fixture.context
        )
        original_fsync = registrar_state._fsync_directory

        def fail_state_root(path: Path) -> None:
            if path == fixture.state_directory:
                raise OSError("synthetic state fsync failure with private path")
            original_fsync(path)

        monkeypatch.setattr(registrar_state, "_fsync_directory", fail_state_root)
        with pytest.raises(RegistrarError) as caught:
            registrar.prepare(preview)
        assert caught.value.code is ReasonCode.WRITE_FAILED
        assert "synthetic" not in str(caught.value)
        assert not fixture.config_path.exists()


def test_visible_journal_after_state_fsync_failure_requires_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        original_fsync = registrar_state._fsync_directory
        failed = False

        def fail_first_state_root(path: Path) -> None:
            nonlocal failed
            if path == fixture.state_directory and not failed:
                failed = True
                raise OSError("synthetic journal fsync failure with private path")
            original_fsync(path)

        monkeypatch.setattr(
            registrar_state, "_fsync_directory", fail_first_state_root
        )
        result = registrar.apply(prepared, fixture_approval(prepared))
        assert result.outcome is Outcome.RECOVERY_REQUIRED
        assert result.config_changed is False
        assert result.state_changed is True
        assert not fixture.config_path.exists()
        assert StateStore(fixture.context).journal_path(
            prepared.operation_id
        ).exists()
        recovery = registrar.prepare_recovery(
            prepared, RecoveryDisposition.COMPLETE
        )
        recovered = registrar.recover(
            recovery,
            RecoveryDisposition.COMPLETE,
            fixture_approval(recovery),
        )
        assert recovered.outcome is Outcome.RECOVERED
        assert recovered.config_changed is True


@pytest.mark.parametrize(
    ("record_kind", "timing"),
    [
        ("receipt", "before"),
        ("receipt", "after"),
        ("verified-journal", "before"),
        ("verified-journal", "after"),
    ],
)
def test_receipt_and_verified_journal_replacement_faults_are_recoverable(
    record_kind: str,
    timing: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        original_replace = StateStore.replace
        triggered = False

        def fault_selected_replace(
            store: StateStore, path: Path, data: bytes
        ) -> None:
            nonlocal triggered
            selected = path.name.startswith("receipt-")
            if path.name.startswith("journal-"):
                selected = (
                    record_kind == "verified-journal"
                    and json.loads(data)["phase"] == "verified"
                )
            else:
                selected = record_kind == "receipt" and selected
            if selected and not triggered:
                triggered = True
                if timing == "before":
                    raise OSError("synthetic pre-replacement fault")
                original_replace(store, path, data)
                raise OSError("synthetic post-replacement fault")
            original_replace(store, path, data)

        with monkeypatch.context() as patch:
            patch.setattr(StateStore, "replace", fault_selected_replace)
            interrupted = registrar.apply(
                prepared, fixture_approval(prepared)
            )
        assert triggered
        assert interrupted.outcome is Outcome.RECOVERY_REQUIRED
        assert interrupted.reason_codes == (ReasonCode.WRITE_FAILED,)
        assert interrupted.config_changed is True
        assert interrupted.state_changed is True
        assert fixture.config_path.exists()

        store = StateStore(fixture.context)
        receipt_exists = store.receipt_path(prepared.audience.target_id).exists()
        journal = json.loads(
            store.journal_path(prepared.operation_id).read_bytes()
        )
        if record_kind == "receipt" and timing == "before":
            assert receipt_exists is False
        else:
            assert receipt_exists is True
        if record_kind == "verified-journal" and timing == "after":
            assert journal["phase"] == "verified"
        else:
            assert journal["phase"] == "config_replaced"

        recovery = registrar.prepare_recovery(
            prepared, RecoveryDisposition.COMPLETE
        )
        recovered = registrar.recover(
            recovery,
            RecoveryDisposition.COMPLETE,
            fixture_approval(recovery),
        )
        assert recovered.outcome is Outcome.RECOVERED
        assert recovered.config_changed is False
        assert recovered.state_changed is True


def test_fault_after_durable_terminal_returns_exact_first_result(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )

        def fail_after_terminal(step: str) -> None:
            if step == "committed":
                raise RuntimeError("synthetic post-terminal failure")

        registrar._fault = fail_after_terminal  # type: ignore[method-assign]
        result = registrar.apply(prepared, fixture_approval(prepared))
        assert result.outcome is Outcome.APPLIED
        assert result.config_changed is True
        assert result.state_changed is True
        registrar._fault = lambda _step: None  # type: ignore[method-assign]
        replay = registrar.apply(prepared, fixture_approval(prepared))
        assert replay.outcome is Outcome.NO_CHANGE
        assert replay.config_changed is False
        assert replay.state_changed is False


@pytest.mark.parametrize("kind", ["register", "rollback"])
@pytest.mark.parametrize("timing", ["before", "after"])
def test_terminal_write_boundary_remains_explicitly_recoverable(
    kind: str,
    timing: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        original = registrar.prepare(
            registrar.preview(
                fixture.config_path, definition, context=fixture.context
            )
        )
        if kind == "register":
            prepared = original
        else:
            assert registrar.apply(
                original, fixture_approval(original)
            ).outcome is Outcome.APPLIED
            prepared = registrar.prepare(
                registrar.rollback(operation_ref(original), context=fixture.context)
            )
        approval = fixture_approval(prepared)
        store = StateStore(fixture.context)
        terminal_path = store.terminal_path(prepared.operation_id)
        original_write = StateStore.write
        triggered = False

        def fault_terminal_write(
            active_store: StateStore, path: Path, data: bytes
        ) -> None:
            nonlocal triggered
            if path == terminal_path and not triggered:
                triggered = True
                if timing == "after":
                    original_write(active_store, path, data)
                raise OSError("synthetic terminal write boundary")
            original_write(active_store, path, data)

        with monkeypatch.context() as patch:
            patch.setattr(StateStore, "write", fault_terminal_write)
            interrupted = registrar.apply(prepared, approval)
        assert triggered
        assert interrupted.outcome is Outcome.RECOVERY_REQUIRED
        assert json.loads(store.journal_path(prepared.operation_id).read_bytes())[
            "phase"
        ] == "committed"
        if timing == "before":
            assert not terminal_path.exists()
            recovery = registrar.prepare_recovery(
                prepared, RecoveryDisposition.COMPLETE
            )
            completed = registrar.apply(recovery, fixture_approval(recovery))
            assert completed.outcome is Outcome.RECOVERED
        else:
            assert terminal_path.exists()
            replay = registrar.recover(
                prepared, RecoveryDisposition.COMPLETE, approval
            )
            assert replay.outcome is Outcome.NO_CHANGE
            assert replay.config_changed is False
            assert replay.state_changed is False


@pytest.mark.skipif(
    sys.platform != "darwin" or not Path("/usr/bin/xattr").exists(),
    reason="macOS xattr contract",
)
def test_existing_target_xattrs_group_and_mode_are_preserved(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    first_definition = _definition()
    with fixture_context(
        registrar, first_definition, fixture_root=tmp_path
    ) as fixture:
        first = registrar.prepare(
            registrar.preview(
                fixture.config_path, first_definition, context=fixture.context
            )
        )
        registrar.apply(first, fixture_approval(first))
        fixture.config_path.chmod(0o640)
        subprocess.run(
            [
                "/usr/bin/xattr",
                "-w",
                "com.kp.registrar-test",
                "preserve-me",
                str(fixture.config_path),
            ],
            check=True,
        )
        before = fixture.config_path.stat()
        updated = RegistrationDefinition.stdio(
            SourceIdentity(
                source_owner=first_definition.source_owner,
                connection_id=first_definition.connection_id,
                source_revision="7" * 40,
                native_name=first_definition.native_name,
            ),
            command="/opt/fixtures/updated",
            args=("mcp",),
        )
        updated_context = replace(
            fixture.context,
            source_revision=updated.source_revision,
            definition_digest=updated.digest,
        )
        prepared = registrar.prepare(
            registrar.preview(
                fixture.config_path, updated, context=updated_context
            )
        )
        result = registrar.apply(prepared, fixture_approval(prepared))
        assert result.outcome is Outcome.APPLIED
        after = fixture.config_path.stat()
        assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode)
        assert after.st_gid == before.st_gid
        value = subprocess.check_output(
            [
                "/usr/bin/xattr",
                "-p",
                "com.kp.registrar-test",
                str(fixture.config_path),
            ],
            text=True,
        ).strip()
        assert value == "preserve-me"


@pytest.mark.skipif(
    not hasattr(os, "chflags") or not hasattr(stat, "UF_NODUMP"),
    reason="file flags unavailable",
)
def test_existing_target_flags_refuse_before_state_or_config_change(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        fixture.config_path.write_text(json.dumps({"mcpServers": {}}))
        os.chflags(fixture.config_path, stat.UF_NODUMP)
        before = fixture.config_path.read_bytes()
        state_before = set(fixture.state_directory.iterdir())
        try:
            with pytest.raises(RegistrarError) as caught:
                registrar.preview(
                    fixture.config_path, definition, context=fixture.context
                )
            assert caught.value.code is ReasonCode.PERMISSION_DENIED
            assert fixture.config_path.read_bytes() == before
            assert set(fixture.state_directory.iterdir()) == state_before
        finally:
            os.chflags(fixture.config_path, 0)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS ACL contract")
def test_existing_target_acl_refuses_before_state_or_config_change(
    tmp_path: Path,
) -> None:
    registrar = CursorRegistrar()
    definition = _definition()
    with fixture_context(registrar, definition, fixture_root=tmp_path) as fixture:
        fixture.config_path.write_text(json.dumps({"mcpServers": {}}))
        acl = f"user:{getpass.getuser()} allow read"
        added = subprocess.run(
            ["/bin/chmod", "+a", acl, str(fixture.config_path)],
            capture_output=True,
            text=True,
        )
        if added.returncode:
            pytest.skip("fixture filesystem rejected an extended ACL")
        before = fixture.config_path.read_bytes()
        state_before = set(fixture.state_directory.iterdir())
        try:
            with pytest.raises(RegistrarError) as caught:
                registrar.preview(
                    fixture.config_path, definition, context=fixture.context
                )
            assert caught.value.code is ReasonCode.PERMISSION_DENIED
            assert fixture.config_path.read_bytes() == before
            assert set(fixture.state_directory.iterdir()) == state_before
        finally:
            subprocess.run(
                ["/bin/chmod", "-N", str(fixture.config_path)], check=True
            )
