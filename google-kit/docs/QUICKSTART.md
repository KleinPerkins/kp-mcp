# google-kit Quickstart

Install, authenticate, and run your first command.

## 1. Install

```bash
git clone https://github.com/KleinPerkins/mcp.git ~/KleinPerkins/mcp
cd ~/KleinPerkins/mcp
uv sync
```

## 2. Registration authority

Bootstrap 0.3.0 requires an explicit registration context, an exact prepared
operation and operation-bound approval from the owner workflow. The CLI has no
live writer qualification and refuses registration with a bounded reason code;
it does not create or repair style profiles. `bootstrap --dry-run` never writes
and reports missing context when no owner context is supplied. `--remove`
(alias `--unregister`) cannot delete an existing unowned entry.

The Python API supports separate preview, prepare and apply stages. Only isolated
disposable fixtures qualify for writes in this source version. Existing entries
need a matching receipt or separately approved adoption; equal launch bytes do
not establish ownership. Registration success reports configuration only, with
enablement, authentication, discovery and safe-read states still unknown.

Existing native host connectors have a separate bounded
[document-style provider route](../../docs/runbooks/native-doc-style-provider.md).
It does not register this server, qualify its registrar writer, or establish
equivalence for the full Google Kit connection.

## 3. Import OAuth credentials into the Keychain

Download `client_secret.json` from [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials → your OAuth 2.0 client ID → Download JSON.

Run (substitute your values from the JSON file):

```bash
security add-generic-password -s google-kit -a default:client_id     -w "<YOUR_CLIENT_ID>"
security add-generic-password -s google-kit -a default:client_secret  -w "<YOUR_CLIENT_SECRET>"
```

`-s google-kit` = service name. `-a default:client_id` = account (profile:key). Credentials are stored in the macOS login Keychain, never written to disk.

## 4. Authenticate

```bash
google-kit auth login
```

Opens your browser for Google OAuth consent. Tokens are stored in the macOS Keychain. No token file is written to disk.

Success stdout:

```
Login successful for profile 'default'. Keys present: client_id, client_secret, access_token, refresh_token.
```

**Headless server (no browser):**

```bash
google-kit auth login --headless
```

Prints the auth URL to stderr. Open it on any browser, complete consent, then paste the redirect URL or code when prompted.

**Force re-consent** (e.g. to add scopes or replace `refresh_google_oauth.py --force`):

```bash
google-kit auth login --force
```

**Request extra scopes for a single login** (opt-in; does *not* change the shared
`GOOGLE_KIT_SCOPES` union, so other profiles are unaffected). Use the `--scopes`
flag or the `GOOGLE_KIT_EXTRA_SCOPES` env var (comma/space separated, unioned with
`GOOGLE_KIT_SCOPES`). This is how a sandbox profile consents to new-API scopes —
see [`../../docs/dev/LIVE-E2E-NEW-APIS.md`](../../docs/dev/LIVE-E2E-NEW-APIS.md) §1c:

```bash
google-kit auth login --force \
  --scopes "https://www.googleapis.com/auth/directory.readonly,https://www.googleapis.com/auth/contacts.readonly"
```

### Scopes & least privilege

`google-kit auth login` requests one shared consent set — `GOOGLE_KIT_SCOPES` in
`google_kit/core/auth.py` (10 scopes, the proven cutover-minimum). Individual
read ops declare the tighter `.readonly` scope variant (e.g. `sheets.read` →
`spreadsheets.readonly`), surfaced in each op's doc card and observability
`scopes_used`. This is per-op least privilege; it does **not** change the consent
grant: the same services' write ops need the read-write scope, and a read-write
scope already covers reads. **No re-consent is required** for the gate-(c)
read-scope tightening (2026-06-17) — your existing token keeps working. You only
need `--force` re-consent when `GOOGLE_KIT_SCOPES` itself changes (e.g. enabling
a new API such as Gmail-write, which is declared but not yet granted).

## 5. Verify authentication

```bash
google-kit auth status
```

Output (logged in):

```
Profile: default
  client_id: present
  client_secret: present
  access_token: present
  refresh_token: present
```

Exit 0 = logged in. Exit 1 = not logged in (hint printed).

## 6. Log out

```bash
google-kit auth logout          # removes access_token and refresh_token only
google-kit auth logout --all    # also removes client_id and client_secret
```

## 7. Run a command

```bash
google-kit drive fetch --url-or-id "https://docs.google.com/document/d/<id>/edit"
google-kit gmail list --max-results 10
google-kit calendar list --days 7
```

All output is JSON with shape `{status, op, data, meta}`.

## 8. Start the MCP server manually

```bash
google-kit mcp
# or equivalently:
python -m google_kit.mcp
```

Both commands start the stdio MCP server. Use `google-kit mcp` in MCP config entries; `python -m google_kit.mcp` works when the CLI entry point is not on `$PATH`.

## Profiles

The default profile is `default`. To use a named profile:

```bash
GOOGLE_KIT_PROFILE=work google-kit auth login
GOOGLE_KIT_PROFILE=work google-kit gmail list
```

Keychain keys are stored as `<profile>:client_id`, `<profile>:access_token`, etc.

## Config directory

`GOOGLE_KIT_CONFIG_DIR` > `CHAOS_LABS_ROOT/data/google-kit/` > `~/Library/Application Support/google-kit/`

## macOS Keychain note

google-kit uses the **login keychain, non-biometric**. Authenticated operations fail on non-macOS. Unauthenticated commands (`google-kit --help`, `google-kit <svc> --help`) work on any platform.

## Next steps

- Capability index: [`INDEX.md`](INDEX.md)
- Adding a capability: [`../docs/dev/SERVICE-PATTERN.md`](../../docs/dev/SERVICE-PATTERN.md)
- Error triage: [`../docs/dev/TRIAGE.md`](../../docs/dev/TRIAGE.md)
- Escalation policy: [`../docs/dev/ESCALATION.md`](../../docs/dev/ESCALATION.md)
- Safety rule (MCP agents): [`rules/google-kit-mcp-safety.mdc`](../rules/google-kit-mcp-safety.mdc)

## Google Sites prerequisites

`drive.fetch` routes `https://sites.google.com/…` URLs to a browser-based fetch path. This path requires:

1. **Chrome** installed and accessible to Playwright.
2. **`browser_cookie3`** — reads Chrome session cookies: `uv add browser_cookie3`.
3. **`playwright`** + Chromium: `uv add playwright && uv run playwright install chromium`.

Once installed, pass the Sites URL as `url_or_id` — no other config needed.

> If these dependencies are absent, `drive.fetch` raises `NotImplementedError` with a setup hint. No Sites-specific op exists; Sites is a routing behaviour within `drive.fetch`.
