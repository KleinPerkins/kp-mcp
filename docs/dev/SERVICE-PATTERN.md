# Service Authoring Pattern

Recipe for a fan-out workpacket adding one service. Every file listed is
owned by the service workpacket; no shared file needs editing.

## Directory layout

```
google-kit/src/google_kit/services/<svc>/
    __init__.py      # registers OpSpecs on import
    models.py        # pydantic input/output models
    core.py          # typed core functions
google-kit/tests/
    test_<svc>.py    # mock-read + mutation-request parity tests
google-kit/fixtures/golden/<svc>/
    <op>_response.json       # canned API response (read ops)
    <op>_expected.json       # expected normalized output (read ops)
    <op>_expected_body.json  # expected request body (write ops)
```

The auto-loader (`google_kit/services/__init__.py`) discovers your package
via `pkgutil.iter_modules` — no edits to any shared file required.

## Core function signature

```python
from typing import Any
from google_kit.core.client import execute_api_call
from google_kit.core.normalize import Meta, OutputEnvelope
from .models import MySvcFooInput, MySvcFooData

def mysvc_foo(
    inp: MySvcFooInput,
    *,
    service: Any = None,        # test injection only; None -> real Keychain auth in CLI/MCP
) -> OutputEnvelope[MySvcFooData]:
    """One-line docstring (appears in MCP schema description).

    Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
    """
    raw = execute_api_call(
        lambda: service.things().list(param=inp.param).execute(),
        op="mysvc.foo",
        posture="read",          # or "write" / "destructive"
    )
    items = (raw or {}).get("items", [])
    data = MySvcFooData(count=len(items), items=[...])
    return OutputEnvelope(data=data, meta=Meta(op="mysvc.foo"))
```

Rules:
- No `argparse`, no `print`. Log to stderr via `observe_op` (handled inside `execute_api_call`).
- `service` is the only parameter injected by tests.  Default `None` means
  real auth via Keychain (Phase 5 wires this).
- `execute_api_call` wraps retry / classify / observe / audit automatically.
- For GET-then-PUT write ops, call `execute_api_call` twice: first with
  `posture="read"` for the GET, then `posture="write"` for the PUT.

## OpSpec registration

```python
# google_kit/services/mysvc/__init__.py
from google_kit.registry import OpSpec, register
from .core import mysvc_foo
from .models import MySvcFooInput, MySvcFooOutput

register(OpSpec(
    name="mysvc.foo",
    fn=mysvc_foo,
    input_model=MySvcFooInput,
    output_model=MySvcFooOutput,
    posture="read",
    scopes=["https://www.googleapis.com/auth/..."],
    perf={"api": "MyAPI v1", "method": "things.list", "quota": "500 req/day"},
    batching={"supported": False},
    formatting={"default": "normalized-json"},
    examples=[{
        "description": "List things",
        "input": {"param": "value"},
        "cli": "google-kit mysvc foo --param value",
    }],
))
```

**`output_model` and `OutputEnvelope` explained:**
`MySvcFooOutput` is a type alias for `OutputEnvelope[MySvcFooData]`, defined in `models.py`
as `MySvcFooOutput = OutputEnvelope[MySvcFooData]`.  `OutputEnvelope` is the uniform
envelope (`{data, page, warnings, meta}`) — `MySvcFooData` is the operation-specific payload
inside `data`.  The OpSpec `output_model` is the full envelope type
(`OutputEnvelope[MySvcFooData]`); docgen and MCP schema generation call
`output_model.model_json_schema()` to emit the complete output schema including `data`.

## Mock-read parity test

```python
from kp_mcp_testkit.mock_google import MockGoogleService
from kp_mcp_testkit.parity import compare

def test_mock_read_parity():
    response = load_fixture(FIXTURES / "foo_response.json")
    expected = load_fixture(FIXTURES / "foo_expected.json")

    svc = MockGoogleService(responses={("things", "list"): response})
    result = mysvc_foo(MySvcFooInput(), service=svc)

    parity = compare("normalized-json", expected, result.data.model_dump())
    assert parity.match, parity.diff
```

Golden fixture pair:
- `foo_response.json` — raw Google API response dict.
- `foo_expected.json` — expected `result.data.model_dump()`.

## Mutation-request parity test

```python
def test_mutation_request_parity():
    expected_body = load_fixture(FIXTURES / "create_expected_body.json")
    svc = MockGoogleService(responses={("things", "insert"): {"id": "x", ...}})

    mysvc_create(MySvcCreateInput(title="t"), service=svc)

    actual_body = svc.last_request_body()
    parity = compare("mutation-request", expected_body, actual_body)
    assert parity.match, parity.diff
```

For GET-then-PUT ops, use `svc.requests_for("things", "update")[0].body`.

Golden fixture: `create_expected_body.json` — the exact request body the
legacy script would have sent.  Derive it by reading the legacy script and
tracing input → body dict.

## Parity status convention

Every op's docstring and test module docstring must state:

```
Parity: mock-read DONE; sandbox-e2e DEFERRED(P6)
```
or:
```
Parity: mutation-request DONE; sandbox-e2e DEFERRED(P6)
```

Phase 6 provisions a sandbox account and runs the sandbox-e2e leg.

## Generate the doc card

```bash
uv run python -m google_kit.docgen_gen
```

Writes all cards to `google-kit/docs/cards/` and regenerates `google-kit/docs/INDEX.md`. Re-running is deterministic (no diff if nothing changed).

## Verify before committing

```bash
uv sync
uv run python -c "import google_kit, google_kit.services; from google_kit.core import client; print('ok')"
uv run python -c "from google_kit.registry import all_specs; print(sorted(s.name for s in all_specs()))"
uv run pytest -q
uv run python -m google_kit.schema_gen
uv run python -m kp_mcp_testkit.editorial docs/ google-kit kp-mcp-bootstrap kp-mcp-testkit CONVENTIONS.md
```
