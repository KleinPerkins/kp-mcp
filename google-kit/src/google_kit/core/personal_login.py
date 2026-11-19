"""Explicit fresh personal login; memory staging precedes create-only persistence.

Personal ownership/consent are operator prerequisites, not inferred from names,
downloaded JSON or successful diagnostics. A partial create stays held; this
module never updates/deletes existing credentials or retries an OAuth flow.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import stat

from kp_mcp_bootstrap.oauth import LoopbackPKCEFlow
from .personal_authz import read_authorizations
from .personal_preflight import (
    CLIENT, EMAIL, PROFILE, SUBJECT, SCOPE, GoogleReadTransport, Refused,
    _json_body, _unique_object, inspect_profile, inventory_digest,
)

KEYS = ('client_id', 'client_secret', 'refresh_token', 'access_token')
LOGIN_REASONS = frozenset((
    'personal_login_options_required', 'personal_profile_required',
    'personal_scope_override_refused', 'reviewed_scopes_required',
    'client_file_unsafe', 'client_file_changed', 'client_file_corrupt',
    'client_binding_mismatch', 'profile_not_empty', 'create_only_store_required',
    'token_exchange_invalid', 'scope_grant_mismatch', 'staged_credentials_changed',
    'credentials_changed', 'credential_commit_unavailable', 'personal_login_unavailable',
))


class LoginRefused(Refused):
    REASONS = Refused.REASONS | LOGIN_REASONS


def refuse(reason):
    raise LoginRefused(reason) from None


def _identity(s):
    return (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_nlink,
            s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def read_client_file(path, digest, expected_client, expected_project, *, snapshot=None):
    """Read only one explicitly reviewed owner-private installed-client JSON."""
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        refuse('personal_login_options_required')
    if not isinstance(path, (str, Path)):
        refuse('personal_login_options_required')
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or path == Path('/'):
        refuse('client_file_unsafe')
    descriptors = []; chain = []
    try:
        parent = Path('/'); fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(fd)
        for part in path.parts[1:-1]:
            parent = parent / part
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            descriptors.append(fd); chain.append((fd, parent, os.fstat(fd)))
        leaf = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        descriptors.append(leaf); before = os.fstat(leaf)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or before.st_nlink != 1 or before.st_mode & 0o077 or before.st_size > 65536):
            refuse('client_file_unsafe')
        if snapshot is not None and list(_identity(before)) != snapshot['file_identity']:
            refuse('client_file_changed')
        raw = b''
        while True:
            chunk = os.read(leaf, min(8192, 65537 - len(raw)))
            if not chunk: break
            raw += chunk
            if len(raw) > 65536: refuse('client_file_unsafe')
        if _identity(before) != _identity(os.fstat(leaf)) or _identity(before) != _identity(path.lstat()):
            refuse('client_file_changed')
        for directory, name, original in chain:
            fields = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_nlink)
            if fields(original) != fields(os.fstat(directory)) or fields(original) != fields(name.lstat()):
                refuse('client_file_changed')
        if hashlib.sha256(raw).hexdigest() != digest: refuse('client_file_changed')
        try:
            data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object,
                              parse_constant=lambda _: refuse('client_file_corrupt'))
        except (ValueError, UnicodeError, RecursionError, Refused):
            refuse('client_file_corrupt')
        if type(data) is not dict or set(data) != {'installed'} or type(data['installed']) is not dict:
            refuse('client_file_corrupt')
        info = data['installed']
        allowed = {'client_id', 'client_secret', 'project_id', 'auth_uri', 'token_uri',
                   'auth_provider_x509_cert_url', 'redirect_uris'}
        required = {'client_id', 'client_secret', 'project_id', 'auth_uri', 'token_uri'}
        if not required <= set(info) or set(info) - allowed: refuse('client_file_corrupt')
        if info['client_id'] != expected_client or info['project_id'] != expected_project:
            refuse('client_binding_mismatch')
        if (info['auth_uri'] != 'https://accounts.google.com/o/oauth2/v2/auth'
                or info['token_uri'] != 'https://oauth2.googleapis.com/token'):
            refuse('client_binding_mismatch')
        secret = info['client_secret']
        if not isinstance(secret, str) or not 1 <= len(secret) <= 16384 or any(ord(c) < 33 or ord(c) > 126 for c in secret):
            refuse('client_file_corrupt')
        if 'auth_provider_x509_cert_url' in info and info['auth_provider_x509_cert_url'] != 'https://www.googleapis.com/oauth2/v1/certs':
            refuse('client_binding_mismatch')
        if 'redirect_uris' in info:
            redirects = info['redirect_uris']
            if (type(redirects) is not list or not redirects or any(
                u not in ('http://localhost', 'http://localhost/', 'http://127.0.0.1', 'http://127.0.0.1/')
                for u in redirects)):
                refuse('client_binding_mismatch')
        receipt = {'file_sha256': digest, 'file_identity': list(_identity(before))}
        if snapshot is not None and receipt != snapshot: refuse('client_file_changed')
        if _identity(before) != _identity(os.fstat(leaf)) or _identity(before) != _identity(path.lstat()):
            refuse('client_file_changed')
        for directory, name, original in chain:
            fields = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_nlink)
            if fields(original) != fields(os.fstat(directory)) or fields(original) != fields(name.lstat()):
                refuse('client_file_changed')
        return {'client_id': expected_client, 'client_secret': secret}, receipt
    except OSError:
        refuse('client_file_unsafe')
    finally:
        for descriptor in reversed(descriptors): os.close(descriptor)


class MemoryStage:
    def __init__(self, profile, credentials):
        self.profile = profile; self.values = dict(credentials)

    def get(self, key):
        return self.values[key]

    def has(self, key):
        return key in self.values

    def set(self, key, value):
        if key not in ('access_token', 'refresh_token'): refuse('staged_credentials_changed')
        self.values[key] = value

    def delete(self, key):
        refuse('staged_credentials_changed')


class PersonalGoogleTransport(GoogleReadTransport):
    def exchange_token(self, body):
        """One fixed TLS POST; no ambient proxy, redirect, body logging or retry."""
        connection = None
        try:
            factory = self._connection_factory or http.client.HTTPSConnection
            connection = factory('oauth2.googleapis.com', timeout=10, context=ssl.create_default_context())
            connection.set_debuglevel(0)
            connection.request('POST', '/token', body=body, headers={
                'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded',
                'Cache-Control': 'no-store'})
            response = connection.getresponse()
            if response.status != 200: refuse('provider_refused')
            if response.getheader('Content-Type', '').split(';', 1)[0].strip().lower() != 'application/json':
                refuse('invalid_provider_response')
            return _json_body(response.read(32769))
        except Refused:
            raise
        except Exception:
            refuse('provider_unavailable')
        finally:
            if connection is not None:
                try: connection.close()
                except Exception: pass


class PersonalLoopbackFlow(LoopbackPKCEFlow):
    def __init__(self, store, client_id, *, expected_email, transport, headless=False):
        super().__init__(store, 'https://accounts.google.com/o/oauth2/v2/auth',
                         'https://oauth2.googleapis.com/token', client_id, headless=headless,
                         authorization_params={'login_hint': expected_email,
                                               'prompt': 'consent select_account',
                                               'include_granted_scopes': 'false'})
        self._transport = transport

    def _post_token(self, body):
        return self._transport.exchange_token(body)


def login_personal(*, profile, expected_email, expected_subject, expected_client_id,
                   expected_project_id, client_file, client_file_sha256, config_dir,
                   expected_inventory_digest, operations, requested_scopes, store_factory,
                   flow_factory=None, transport_factory=None, headless=False):
    """Verify the account before creating four absent items; never overwrite.

    Keychain has no multi-item atomic transaction here. Interrupted/failed writes
    remain explicitly incomplete, with no automatic deletion or namespace reuse.
    No config, grant, registration, refresh or client-file write is performed.
    """
    stage = None; created = []; attempted = None
    try:
        if not isinstance(profile, str) or not PROFILE.fullmatch(profile) or profile == 'default':
            refuse('personal_profile_required')
        if (not isinstance(expected_email, str) or not EMAIL.fullmatch(expected_email)
                or not isinstance(expected_subject, str) or not SUBJECT.fullmatch(expected_subject)
                or not isinstance(expected_client_id, str) or not CLIENT.fullmatch(expected_client_id)
                or not isinstance(expected_project_id, str) or not re.fullmatch('[a-z][a-z0-9-]{4,61}[a-z0-9]', expected_project_id)):
            refuse('personal_login_options_required')
        if (type(requested_scopes) is not list or not requested_scopes
                or any(type(s) is not str or (s not in ('openid', 'email', 'profile') and not SCOPE.fullmatch(s)) for s in requested_scopes)
                or len(requested_scopes) != len(set(requested_scopes))):
            refuse('reviewed_scopes_required')
        scopes = tuple(sorted(requested_scopes))
        encoded_operations = json.dumps(operations, allow_nan=False)
        if len(encoded_operations) > 524288: refuse('invalid_inventory')
        operations = json.loads(encoded_operations)
        if inventory_digest(operations) != expected_inventory_digest: refuse('inventory_changed')
        before = read_authorizations(config_dir=config_dir, profile=profile, operations=operations,
                                     expected_inventory_digest=expected_inventory_digest)
        store = store_factory(profile)
        if store.profile != profile: refuse('store_profile_mismatch')
        if not all(callable(getattr(store, key, None)) for key in ('create', 'validate_create', 'get', 'has')):
            refuse('create_only_store_required')
        if any(store.has(key) for key in KEYS): refuse('profile_not_empty')
        credentials, client_snapshot = read_client_file(client_file, client_file_sha256,
                                                       expected_client_id, expected_project_id)
        for key, value in credentials.items(): store.validate_create(key, value)
        stage = MemoryStage(profile, credentials)
        transport = (transport_factory or PersonalGoogleTransport)()
        factory = flow_factory or PersonalLoopbackFlow
        flow = factory(stage, expected_client_id, expected_email=expected_email,
                       transport=transport, headless=headless)
        code = flow.authorize(list(scopes))
        tokens = flow.exchange(code)
        if type(tokens) is not dict or tokens.get('token_type') != 'Bearer':
            refuse('token_exchange_invalid')
        for key in ('access_token', 'refresh_token'):
            value = tokens.get(key)
            if (not isinstance(value, str) or not 1 <= len(value) <= 16384
                    or any(ord(c) < 33 or ord(c) > 126 for c in value)
                    or stage.values.get(key) != value):
                refuse('token_exchange_invalid')
        if any(stage.values.get(key) != value for key, value in credentials.items()) or set(stage.values) != set(KEYS):
            refuse('staged_credentials_changed')
        values = dict(stage.values)
        diagnostic_stage = MemoryStage(profile, values)
        report = inspect_profile(profile=profile, expected_email=expected_email,
                                 expected_subject=expected_subject, expected_client_id=expected_client_id,
                                 store=diagnostic_stage, transport=transport, operations=operations,
                                 expected_inventory_digest=expected_inventory_digest)
        diagnostic_stage.values.clear()
        if stage.values != values: refuse('staged_credentials_changed')
        if report['observed_token_scopes'] != list(scopes): refuse('scope_grant_mismatch')
        if 'scope' in tokens and (not isinstance(tokens['scope'], str) or sorted(tokens['scope'].split()) != list(scopes)):
            refuse('scope_grant_mismatch')
        read_client_file(client_file, client_file_sha256, expected_client_id, expected_project_id,
                         snapshot=client_snapshot)
        after = read_authorizations(config_dir=config_dir, profile=profile, operations=operations,
                                    expected_inventory_digest=expected_inventory_digest)
        if before != after: refuse('authorization_changed')
        for key in KEYS: store.validate_create(key, values[key])
        for key in KEYS:
            if any(store.get(old) != values[old] for old in created): refuse('credentials_changed')
            if any(store.has(new) for new in KEYS if new not in created): refuse('profile_not_empty')
            attempted = key
            store.create(key, values[key])
            created.append(key); attempted = None
            if store.get(key) != values[key]: refuse('credentials_changed')
        if any(store.get(key) != values[key] for key in KEYS): refuse('credentials_changed')
        read_client_file(client_file, client_file_sha256, expected_client_id, expected_project_id,
                         snapshot=client_snapshot)
        final = read_authorizations(config_dir=config_dir, profile=profile, operations=operations,
                                    expected_inventory_digest=expected_inventory_digest)
        if final != before: refuse('authorization_changed')
        return {'schema':'google-kit/personal-login-result/v1','status':'verified_credentials_created',
                'profile':profile,'expected_email':expected_email,'expected_subject':expected_subject,
                'client_id_sha256':hashlib.sha256(expected_client_id.encode()).hexdigest(),
                'client_file_snapshot':client_snapshot,'requested_and_observed_scopes':list(scopes),
                'inventory_sha256':expected_inventory_digest,'operation_count':len(operations),
                'created_keys':list(created),'account_verified_before_any_credential_persistence':True,
                'authorization_snapshot':final,'operation_grants_changed':False,
                'native_registration_or_full_connection_accepted':False,'execution_authorized':False}
    except Exception as exc:
        reason = exc.reason if type(exc) in (Refused, LoginRefused) else 'personal_login_unavailable'
        if reason not in Refused.REASONS | LOGIN_REASONS: reason = 'personal_login_unavailable'
        return {'schema':'google-kit/personal-login-result/v1','status':'held','reason':reason,
                'created_keys':list(created),'uncertain_create_key':attempted,
                'partial_profile_requires_review':bool(created) or attempted is not None,
                'automatic_retry_rollback_delete_or_overwrite_performed':False,
                'native_registration_or_full_connection_accepted':False,'execution_authorized':False}
    finally:
        if stage is not None: stage.values.clear()
