# Registrar maintenance API

This describes the source interface implementing [ADR0002](../adr/0002-coordinated-maintenance-for-source-owned-mcp-registration.md).
It grants no live-operation authority. The production caller revision allowlist
is empty; maintenance admission refuses until the actual reviewed dev adapter
implementation is bound. An ADR publication revision is not that binding.

## Caller boundary

Construct a registrar with `maintenance_validator=validator`. The separate
Snow `policy_validator` remains in force. The dev validator supplies:

```python
validator_id = "dev/int014-maintenance-validator/v1"
issuer_source_revision = "<exact reviewed 40-hex caller revision>"

def validate(request: MaintenanceValidationRequest) -> None:
    # Resolve current private lifecycle, writer/consequence observations,
    # exact approval and nonsecret eligibility; raise on failure.
    ...
```

The caller must hold its dev cooperative barrier across the complete registrar
call using `with validator.operation():`. Acquisition and lifecycle transitions
use the exclusive side of that barrier. D1 does not acquire or release the dev
barrier, pause processes, change lifecycle state, or resume writers.

`MaintenanceValidationRequest` is a frozen, private in-memory object:

| Field | Meaning |
|---|---|
| `context`, `checked_at`, `phase` | Exact typed context, current UTC validation time and named boundary. |
| `audience`, `operation_id`, `action_digest`, `prepared_payload_digest` | Exact operation binding. Admission/inspection requests may omit these; preparation precedes final action approval. |
| `expected_config_digest`, `expected_state_digest` | Phase-correct expected config and selected ownership-receipt images. Absent bytes use the existing `"absent"` sentinel. These are not whole-directory digests. |
| `original_operation_reference`, `approval` | Digest-bound predecessor-operation snapshot and exact approval when applicable. Approval checks use `dev/int014-operation-approval/v1`. |
| `durable_material` | Private tuple of config/receipt pre/postimage bytes. The reviewed observer must establish nonsecret eligibility for every byte before persistence; a selected entry or hash alone cannot do so. |

The request is never serialized. The validator must return `None` only after
resolving current supported evidence; booleans, persisted validation flags,
opaque references and PID lists are insufficient. Exceptions refuse admission
without exposing observer details. Unknown and noncooperating writers remain
the explicitly accepted residual race risk.

Current request phases are `inspection`, `admission`, `approval`, `prepare`,
`prepare_locked`, `journal_prepared`, `config_replace`,
`journal_config_replaced`, `receipt_replace`, `journal_verified`,
`original_journal`, `original_terminal`, `cancel_staging_remove`,
`journal_committed`, and `terminal_commit`. Mutation requests carry expected
images and durable material. The dev observer must reject unsupported requests
or unavailable observations.

## Records and recovery

`KnownWriterEvidence` and `MaintenanceEvidence` emit JSON-ready closed records.
Writer observations can precede acquisition by at most 600 seconds; future
observations refuse at validation. The window itself lasts at most 600 seconds,
and current writer conditions are re-observed on every mutation boundary.

`RegistrationContext` and `WriterWindow` default to their existing v1 schemas.
Maintenance requires explicit v2 schemas and matching embedded evidence.
Unknown fields, mixed modes and missing evidence refuse. Context, preview,
prepared record, journal, terminal and result bind the coordinated claim,
writer-window digest and maintenance-evidence digest. Ownership receipts retain
their existing v1 meaning.

Preparation and reload recompute the exact desired config, receipt and reported
leaf changes through the existing source-owned projection. A recomputed hash
does not make a contradictory prepared record valid. Stable leaf symlinks retain
their existing support: the operation audience binds the resolved target while
the context and maintenance window retain the logical config-path binding.
The active registrar must retain the exact consumer policy binding for prepare,
reload and apply. Maintenance unregister requires an existing validated ownership
receipt to bind the selected native name; an absent receipt refuses even when
the target entry appears absent. Strict v1 behavior is unchanged.

For a fresh process, reconstruct the reviewed dev validator and typed context,
then call `registrar.load_prepared(record_id, *, context, definition)`. This
loads and checks exact persisted bytes; it does not infer authority from them.
Supply the exact source definition, or `None` for an operation prepared without
one. For an expired original operation, supply a fresh approved child context
with its predecessor UUID and digest-bound original-operation reference.
Original operation authority is preserved independently of current child
authority. Maintenance cannot replay a v1 operation under weaker protection.
Child recovery and rollback retain the original source revision and client build;
a changed source or build requires a separate operation. Root registration,
adoption and unregister operations cannot carry child-recovery authority.

`operation_ref(prepared, *, pending=False, maintenance_validator=None)` has one
additive keyword-only argument for maintenance callers. `prepare_recovery`,
`prepare_cancel`, `recover`, and `rollback` use the registrar's injected binding.
No callable or arbitrary module selector is recovered from a file.

## Compatibility and delivery

These public signatures remain unchanged:

```text
inspect_registration(path: 'Path', *, context: 'RegistrationContext') -> 'Inspection'
preview(path: 'Path', definition: 'RegistrationDefinition', *, context: 'RegistrationContext') -> 'Preview'
```

The existing fixture preview remains nonwriting and uses v1 authority.
Registrar `prepare` and `apply` keep their signatures. Google, Snow, Widget and
scaffold registrar factories and registration-only wrappers accept the optional
binding. Profile setup/repair and command-line calls do not manufacture it.

The D1 source versions are bootstrap 0.4.0, Google 0.3.0, Snow 0.4.0 and Widget
0.3.0; consumers and the scaffold pin bootstrap exactly. Final delivery evidence
must bind source commit/tree, package tree, wheel SHA-256, API signatures and
adapter mapping digests. A build or synthetic test is not release, installation,
native qualification, authenticated service access, or baseline-handoff proof.
