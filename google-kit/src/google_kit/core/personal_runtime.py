"""Explicit personal consumer context; never resolves a legacy profile or config.

The reviewed context file and its digest are inputs, not proof of human consent,
Cloud-project ownership, source acceptance or destination admission. Those are
operator prerequisites. No discovery, login, grant, registration or repair lives
here. Interrupted refresh journals require owner recovery; no automatic retry.
"""
from __future__ import annotations

import base64
import contextlib
import contextvars
import datetime
import fcntl
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import stat
import threading
import time
import uuid
from types import MappingProxyType
from urllib.parse import urlencode, urlsplit

from .errors import GoogleKitError
from .personal_preflight import CLIENT, EMAIL, PROFILE, SUBJECT, SCOPE, inventory_digest

_CURRENT = contextvars.ContextVar('google_kit_personal_runtime', default=None)
_OPERATION = contextvars.ContextVar('google_kit_personal_operation', default=None)
_THREAD_LOCK = threading.RLock()
_KEYS = ('client_id', 'client_secret', 'refresh_token', 'access_token')
_CERT_URL = 'https://www.googleapis.com/oauth2/v1/certs'
_ALIASES = {'email': 'https://www.googleapis.com/auth/userinfo.email',
            'profile': 'https://www.googleapis.com/auth/userinfo.profile'}


class PersonalRuntimeError(GoogleKitError):
    """Fixed reason only; provider values, tokens and paths never enter errors."""
    def __init__(self, reason):
        super().__init__('personal runtime held: ' + reason, op='personal-runtime')


def held(reason):
    raise PersonalRuntimeError(reason) from None


def current():
    return _CURRENT.get()


def _unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out: held('duplicate_json_key')
        out[key] = value
    return out


def _json(raw):
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique,
                           parse_constant=lambda _: held('invalid_json'))
        if type(value) is not dict: held('invalid_json')
        return value
    except PersonalRuntimeError: raise
    except Exception: held('invalid_json')


def _identity(s, content=False):
    value = (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_nlink, getattr(s, 'st_flags', 0))
    return value + (s.st_size, s.st_mtime_ns, s.st_ctime_ns) if content else value


def _directory_identity(s):
    # APFS directory nlink changes when our regular journal/lock files are
    # created. Retain directory inode/mode/owner/flags, not its entry count.
    return (s.st_dev, s.st_ino, s.st_mode, s.st_uid, getattr(s, 'st_flags', 0))


class Directory:
    """Retain no-follow directory FDs; cooperative drift protection, not CAS."""
    def __init__(self, path):
        self.fds = []; self.chain = []
        if not isinstance(path, (str, Path)): held('explicit_path_required')
        path = Path(path)
        if not path.is_absolute() or path == Path('/') or '..' in path.parts:
            held('explicit_path_required')
        self.path = path
        try:
            fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self.fds.append(fd); parent = Path('/')
            for part in path.parts[1:]:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                parent = parent / part; self.fds.append(fd)
                self.chain.append((fd, parent, _directory_identity(os.fstat(fd))))
            self.fd = fd
        except Exception:
            self.close(); held('directory_unavailable')

    def private(self):
        s = os.fstat(self.fd)
        if s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o700:
            held('private_config_required')

    def check(self):
        try:
            for fd, path, before in self.chain:
                if _directory_identity(os.fstat(fd)) != before or _directory_identity(path.lstat()) != before:
                    held('directory_changed')
        except PersonalRuntimeError: raise
        except Exception: held('directory_changed')

    def read(self, name, *, absent=False):
        self.check()
        try: fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        except FileNotFoundError:
            if absent: self.check(); return None
            held('file_unavailable')
        except OSError: held('file_unavailable')
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                    or before.st_nlink != 1 or before.st_mode & 0o077 or before.st_size > 65536):
                held('private_regular_file_required')
            raw = b''
            while b := os.read(fd, 8192):
                raw += b
                if len(raw) > 65536: held('file_too_large')
            if (_identity(before, True) != _identity(os.fstat(fd), True)
                    or _identity(before, True) != _identity(os.stat(name, dir_fd=self.fd, follow_symlinks=False), True)):
                held('file_changed')
            self.check()
            return raw, _identity(before, True)
        finally: os.close(fd)

    def replace(self, name, value, expected):
        """Exact preimage checked under our flock; no hostile-writer CAS claim."""
        raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
        self.check()
        if self.read(name, absent=True) != expected: held('journal_changed')
        staging = '.personal-stage-' + uuid.uuid4().hex
        fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        try:
            with os.fdopen(fd, 'wb', closefd=False) as f: f.write(raw); f.flush(); os.fsync(fd)
            ident = _identity(os.fstat(fd), True)
            self.check()
            if self.read(name, absent=True) != expected: held('journal_changed')
            if _identity(os.stat(staging, dir_fd=self.fd, follow_symlinks=False), True) != ident:
                held('staging_changed')
            if expected is None:
                # Exclusive publication: a foreign creation is never replaced.
                os.link(staging, name, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)
                os.unlink(staging, dir_fd=self.fd)
            else:
                os.replace(staging, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            os.fsync(self.fd)
            observed = self.read(name)
            if observed[0] != raw: held('journal_readback')
            return observed
        except PersonalRuntimeError: raise
        except Exception: held('journal_write_uncertain')
        finally: os.close(fd)

    def close(self):
        for fd in reversed(self.fds): os.close(fd)
        self.fds = []


def canonical_scopes(values):
    if type(values) is not list or not values or len(values) > 128:
        held('reviewed_scopes_required')
    if any(type(s) is not str or (s not in ('openid', 'email', 'profile') and not SCOPE.fullmatch(s)) for s in values):
        held('invalid_scope')
    normalized = [_ALIASES.get(s, s) for s in values]
    if len(normalized) != len(set(normalized)): held('duplicate_scope')
    return tuple(sorted(normalized))


class Context:
    def __init__(self, path, digest, operations):
        if type(digest) is not str or not re.fullmatch('[0-9a-f]{64}', digest):
            held('context_digest_required')
        path = Path(path) if isinstance(path, (str, Path)) else None
        if path is None or not path.is_absolute() or '..' in path.parts:
            held('explicit_context_required')
        directory = Directory(path.parent)
        try:
            observed = directory.read(path.name)
            raw = observed[0]
            if hashlib.sha256(raw).hexdigest() != digest: held('context_digest_mismatch')
            data = _json(raw)
        finally: directory.close()
        fields = {'schema', 'profile', 'expected_email', 'expected_subject', 'expected_client_id',
                  'expected_project_id', 'config_dir', 'scopes', 'inventory_sha256', 'allowed_operations',
                  'authorization_file_sha256', 'extra_flags'}
        if set(data) != fields or data['schema'] != 'google-kit/personal-runtime-context/v1': held('context_schema')
        checks = [('profile', PROFILE), ('expected_email', EMAIL), ('expected_subject', SUBJECT), ('expected_client_id', CLIENT)]
        if any(type(data[k]) is not str or not pattern.fullmatch(data[k]) for k, pattern in checks): held('context_identity')
        if data['profile'] == 'default': held('explicit_personal_profile_required')
        if type(data['expected_project_id']) is not str or not re.fullmatch('[a-z][a-z0-9-]{4,61}[a-z0-9]', data['expected_project_id']): held('context_project')
        self.operations = json.loads(json.dumps(operations, allow_nan=False))
        if inventory_digest(self.operations) != data['inventory_sha256']: held('inventory_changed')
        names = {op['name'] for op in self.operations}
        if (type(data['allowed_operations']) is not list or not data['allowed_operations']
                or any(type(x) is not str for x in data['allowed_operations'])
                or len(set(data['allowed_operations'])) != len(data['allowed_operations'])
                or set(data['allowed_operations']) - names): held('operation_set_invalid')
        if (type(data['extra_flags']) is not list or any(type(x) is not str for x in data['extra_flags'])
                or len(data['extra_flags']) != len(set(data['extra_flags']))
                or any(x not in ('GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE',) for x in data['extra_flags'])): held('extra_flags_invalid')
        expected_authz = data['authorization_file_sha256']
        if expected_authz is not None and (type(expected_authz) is not str or not re.fullmatch('[0-9a-f]{64}', expected_authz)): held('authorization_digest_invalid')
        self.scopes = canonical_scopes(data['scopes'])
        if not {'openid', _ALIASES['email']} <= set(self.scopes): held('verified_identity_scopes_required')
        self.path, self.digest, self.original = path, digest, observed
        for key in ('scopes', 'allowed_operations', 'extra_flags'):
            data[key] = tuple(data[key])
        self.data = MappingProxyType(data)

    def check(self):
        directory = Directory(self.path.parent)
        try:
            if directory.read(self.path.name) != self.original: held('context_changed')
        finally: directory.close()
        from google_kit.registry import all_specs
        live = [dict(name=s.name, scopes=list(s.scopes), posture=s.posture, flag=s.flag) for s in all_specs()]
        if inventory_digest(live) != self.data['inventory_sha256']: held('inventory_changed')


class PersonalTransport:
    """Fixed bounded TLS token/certificate endpoints; no proxy/redirect/retry."""
    def __init__(self, *, _connection_factory=None): self._factory = _connection_factory

    def request(self, host, path, method, body=None):
        connection = None
        try:
            import certifi
            context = ssl.create_default_context(cafile=certifi.where())
            factory = self._factory or http.client.HTTPSConnection
            connection = factory(host, timeout=10, context=context); connection.set_debuglevel(0)
            headers = {'Accept': 'application/json', 'Cache-Control': 'no-store'}
            if body is not None: headers['Content-Type'] = 'application/x-www-form-urlencoded'
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            if response.status != 200 or response.getheader('Content-Type', '').split(';')[0].strip().lower() != 'application/json': held('provider_refused')
            raw = response.read(65537)
            if len(raw) > 65536: held('provider_response_too_large')
            _json(raw)
            return raw
        except PersonalRuntimeError: raise
        except Exception: held('provider_unavailable')
        finally:
            if connection is not None:
                try: connection.close()
                except Exception: pass

    def exchange(self, values, scopes):
        body = urlencode(dict(grant_type='refresh_token', refresh_token=values['refresh_token'],
            client_id=values['client_id'], client_secret=values['client_secret'], scope=' '.join(scopes))).encode('ascii')
        return _json(self.request('oauth2.googleapis.com', '/token', 'POST', body))

    def verify_identity(self, token, client):
        from google.oauth2.id_token import verify_oauth2_token
        def request(url, method='GET', **kwargs):
            if url != _CERT_URL or method != 'GET' or kwargs.get('body') is not None: held('certificate_endpoint_refused')
            raw = self.request('www.googleapis.com', '/oauth2/v1/certs', 'GET')
            values = _json(raw)
            # Pin the X509 map shape, preventing an SDK JWKS alternate fetch.
            if not values or len(values) > 32 or any(type(k) is not str or type(v) is not str or 'BEGIN CERTIFICATE' not in v for k, v in values.items()): held('certificate_response_invalid')
            class Response:
                status = 200
                data = raw
                headers = {'content-type': 'application/json'}
            return Response()
        try: return verify_oauth2_token(token, request, audience=client, clock_skew_in_seconds=0)
        except PersonalRuntimeError: raise
        except Exception: held('id_token_verification_failed')


def _secret(value):
    return type(value) is str and 1 <= len(value) <= 16384 and all(33 <= ord(c) <= 126 for c in value)


def _jwt_object(segment):
    try:
        if not re.fullmatch('[A-Za-z0-9_-]+', segment): held('id_token_invalid')
        raw = base64.b64decode(segment + '=' * (-len(segment) % 4), altchars=b'-_', validate=True)
        if len(raw) > 32768: held('id_token_invalid')
        return _json(raw)
    except PersonalRuntimeError: raise
    except Exception: held('id_token_invalid')


class Runtime:
    def __init__(self, context, *, store_factory=None, transport=None, build_fn=None):
        self.context = context; self.data = context.data
        self.directory = Directory(self.data['config_dir'])
        try: self.directory.private()
        except BaseException: self.directory.close(); raise
        self.store_factory = store_factory; self.transport = transport or PersonalTransport()
        self.build_fn = build_fn; self.credentials = None; self.dead = False; self.closed = False
        self.profile = self.data['profile']

    def check(self):
        if self.dead or self.closed: held('runtime_unusable')
        forbidden = ('GOOGLE_API_USE_CLIENT_CERTIFICATE', 'GOOGLE_API_USE_MTLS_ENDPOINT',
                     'GOOGLE_CLOUD_UNIVERSE_DOMAIN', 'GOOGLE_APPLICATION_CREDENTIALS',
                     'GOOGLE_CLOUD_QUOTA_PROJECT')
        if any(os.environ.get(k) for k in forbidden): held('ambient_SDK_configuration_refused')
        self.context.check(); self.directory.check(); self.directory.private()

    def authorization_tools(self):
        self.check()
        directory = None
        try:
            # Consume actual bound grant bytes, not a diagnostic's observation
            # booleans. Directory identity excludes unrelated ancestor entries.
            try:
                fd = os.open('authorizations', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=self.directory.fd)
            except FileNotFoundError:
                if self.data['authorization_file_sha256'] is not None: held('authorization_changed')
                self.directory.check()
                return {}
            try: identity = _directory_identity(os.fstat(fd))
            finally: os.close(fd)
            directory = Directory(self.directory.path / 'authorizations'); directory.private()
            if _directory_identity(os.fstat(directory.fd)) != identity: held('authorization_changed')
            observed = directory.read(self.profile + '.json', absent=True)
            actual = hashlib.sha256(observed[0]).hexdigest() if observed is not None else None
            if actual != self.data['authorization_file_sha256']: held('authorization_changed')
            if observed is None: return {}
            data = _json(observed[0])
            gated = {op['name'] for op in self.context.operations if op['flag']}
            if (set(data) != {'schema', 'tools'} or type(data['schema']) is not int or data['schema'] != 1
                    or type(data['tools']) is not dict or set(data['tools']) - gated
                    or any(type(value) is not int or value not in (0, 1) for value in data['tools'].values())):
                held('authorization_schema_invalid')
            directory.check(); self.directory.check()
            return data['tools']
        except PersonalRuntimeError: raise
        except Exception: held('authorization_unavailable')
        finally:
            if directory is not None: directory.close()

    def authorize(self, spec, profile=None):
        self.check()
        if profile is not None and profile != self.profile: held('profile_override_refused')
        if spec.name not in self.data['allowed_operations']: held('operation_not_reviewed')
        required = set(canonical_scopes(list(spec.scopes)))
        if not required <= set(self.context.scopes): held('operation_scope_unavailable')
        grants = self.authorization_tools()
        if spec.flag:
            if grants.get(spec.name) != 1: held('operation_grant_missing')

    @contextlib.contextmanager
    def operation(self, spec, profile=None):
        self.authorize(spec, profile)
        token = _OPERATION.set(spec)
        try: yield
        finally: _OPERATION.reset(token)

    def active(self):
        spec = _OPERATION.get()
        if current() is not self or spec is None: held('operation_context_required')
        self.authorize(spec)
        return spec

    @contextlib.contextmanager
    def lock(self):
        deadline = time.monotonic() + 10
        if not _THREAD_LOCK.acquire(timeout=10): held('refresh_lock_timeout')
        fd = None; entered = False
        try:
            self.check(); name = '.personal-refresh-' + self.profile + '.lock'
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=self.directory.fd)
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600 or before.st_size != 0: held('refresh_lock_unsafe')
            while True:
                try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); break
                except BlockingIOError:
                    if time.monotonic() >= deadline: held('refresh_lock_timeout')
                    time.sleep(0.02)
            self.directory.check()
            if _identity(os.fstat(fd)) != _identity(before) or _identity(os.stat(name, dir_fd=self.directory.fd, follow_symlinks=False)) != _identity(before): held('refresh_lock_changed')
            entered = True
            yield
            self.directory.check()
            if _identity(os.stat(name, dir_fd=self.directory.fd, follow_symlinks=False)) != _identity(before): held('refresh_lock_changed')
        except PersonalRuntimeError: raise
        except Exception:
            # Preserve a body failure so refresh classifies an uncertain token
            # write as uncertain, rather than misreporting lock acquisition.
            if entered: raise
            held('refresh_lock_unavailable')
        finally:
            if fd is not None: os.close(fd)
            _THREAD_LOCK.release()

    def store(self):
        if self.store_factory is None:
            from kp_mcp_bootstrap.secrets import KeychainSecretStore
            store = KeychainSecretStore(profile=self.profile)
        else: store = self.store_factory(self.profile)
        if store.profile != self.profile: held('store_profile_mismatch')
        return store

    def values(self, store):
        try:
            client = store.get('client_id')
            if client != self.data['expected_client_id']: held('client_identity_mismatch')
            values = dict(client_id=client)
            for key in _KEYS[1:]:
                values[key] = store.get(key)
                if not _secret(values[key]): held('credential_invalid')
            return values
        except PersonalRuntimeError: raise
        except Exception: held('credential_unavailable')

    def refresh(self, credentials):
        self.active()
        try:
            with self.lock():
                name = '.personal-refresh-' + self.profile + '.json'
                previous = self.directory.read(name, absent=True)
                if previous is not None:
                    old = _json(previous[0])
                    if set(old) != {'schema', 'context_sha256', 'attempt', 'state'} or old['schema'] != 1 or old['context_sha256'] != self.context.digest or old['state'] != 'committed' or type(old['attempt']) is not str or not re.fullmatch('[0-9a-f]{32}', old['attempt']): held('refresh_recovery_required')
                store = self.store(); before = self.values(store)
                attempt = dict(schema=1, context_sha256=self.context.digest, attempt=uuid.uuid4().hex, state='pending')
                owned = self.directory.replace(name, attempt, previous)
                response = self.transport.exchange(before, self.context.scopes)
                if type(response) is not dict or response.get('token_type') != 'Bearer': held('token_response_invalid')
                token = response.get('access_token'); identity = response.get('id_token')
                lifetime = response.get('expires_in')
                if not _secret(token) or not _secret(identity) or type(lifetime) is not int or not 30 < lifetime <= 86400: held('token_response_invalid')
                if type(response.get('scope')) is not str or canonical_scopes(response['scope'].split()) != self.context.scopes: held('scope_grant_mismatch')
                parts = identity.split('.')
                if len(parts) != 3: held('id_token_invalid')
                header = _jwt_object(parts[0]); claims = _jwt_object(parts[1])
                if header.get('alg') != 'RS256' or type(header.get('kid')) is not str or not header['kid'] or set(header) - {'alg', 'kid', 'typ'} or header.get('typ', 'JWT') != 'JWT': held('id_token_invalid')
                verified = self.transport.verify_identity(identity, self.data['expected_client_id'])
                if verified != claims: held('id_token_claims_changed')
                now = int(time.time())
                if (claims.get('iss') not in ('https://accounts.google.com', 'accounts.google.com')
                        or claims.get('aud') != self.data['expected_client_id']
                        or claims.get('azp', self.data['expected_client_id']) != self.data['expected_client_id']
                        or claims.get('sub') != self.data['expected_subject']
                        or type(claims.get('email')) is not str or claims['email'].casefold() != self.data['expected_email'].casefold()
                        or claims.get('email_verified') is not True
                        or type(claims.get('iat')) is not int or type(claims.get('exp')) is not int
                        or claims['iat'] > now or claims['exp'] <= now + 30 or claims['exp'] <= claims['iat']): held('account_identity_mismatch')
                if 'at_hash' in claims:
                    expected = base64.urlsafe_b64encode(hashlib.sha256(token.encode('ascii')).digest()[:16]).rstrip(b'=').decode()
                    if type(claims['at_hash']) is not str or not hmac.compare_digest(claims['at_hash'], expected): held('access_token_binding_mismatch')
                refresh = response.get('refresh_token', before['refresh_token'])
                if not _secret(refresh): held('token_response_invalid')
                self.active()
                if self.values(store) != before: held('credentials_changed')
                expected_values = dict(before)
                if refresh != before['refresh_token']:
                    store.set('refresh_token', refresh); expected_values['refresh_token'] = refresh
                    if self.values(store) != expected_values: held('refresh_write_readback')
                store.set('access_token', token); expected_values['access_token'] = token
                if self.values(store) != expected_values: held('access_write_readback')
                self.active()
                self.directory.replace(name, dict(attempt, state='committed'), owned)
                from google.auth import _helpers
                credentials.token = token
                credentials.expiry = _helpers.utcnow() + datetime.timedelta(seconds=min(lifetime, claims['exp'] - int(time.time())))
        except PersonalRuntimeError:
            self.dead = True; raise
        except Exception:
            self.dead = True; held('refresh_outcome_uncertain')

    def service(self, op_name, profile=None):
        spec = self.active()
        if profile is not None and profile != self.profile: held('profile_override_refused')
        from .auth import _SERVICE_API_MAP
        prefix = op_name.split('.')[0]
        if prefix not in _SERVICE_API_MAP: held('service_not_mapped')
        if self.credentials is None:
            from google.oauth2.credentials import Credentials
            runtime = self
            class BoundCredentials(Credentials):
                def refresh(self, request): runtime.refresh(self)
            credentials = BoundCredentials(token=None, scopes=list(self.context.scopes))
            self.refresh(credentials)
            self.credentials = credentials
        api, version = _SERVICE_API_MAP[prefix]
        if self.build_fn is not None: return self.build_fn(api, version, credentials=self.credentials)
        import certifi
        import httplib2
        from google_auth_httplib2 import AuthorizedHttp
        from googleapiclient.discovery import build
        runtime = self
        class PersonalHttp(httplib2.Http):
            def request(self, uri, *args, **kwargs):
                runtime.active()
                try:
                    u = urlsplit(uri)
                    valid = u.scheme == 'https' and u.hostname and (u.hostname == 'googleapis.com' or u.hostname.endswith('.googleapis.com')) and u.username is None and u.password is None and u.port in (None, 443)
                except Exception: valid = False
                if not valid: held('API_endpoint_refused')
                kwargs['redirections'] = 0
                return super().request(uri, *args, **kwargs)
        # The SDK must not consult ambient mTLS, credential, quota or universe
        # settings, even when a caller supplied an explicit HTTP instance.
        http = PersonalHttp(proxy_info=None, timeout=10, ca_certs=certifi.where())
        http.follow_redirects = False
        authorized = AuthorizedHttp(self.credentials, http=http)
        try: return build(api, version, http=authorized, cache_discovery=False, static_discovery=True)
        except PersonalRuntimeError: raise
        except Exception: held('service_build_unavailable')

    def flag(self, flag):
        if not flag: return True
        spec = self.active()
        return flag == spec.flag or flag in self.data['extra_flags']

    def append_audit(self, record):
        self.active(); name = 'personal-audit.jsonl'; self.directory.check()
        try: fd = os.open(name, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=self.directory.fd)
        except OSError: held('audit_path_unavailable')
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600: held('audit_path_unsafe')
            raw = (json.dumps(record, sort_keys=True) + '\n').encode()
            if len(raw) > 1048576: held('audit_record_too_large')
            if os.write(fd, raw) != len(raw): held('audit_write_uncertain')
            os.fsync(fd); self.directory.check()
            if _identity(os.fstat(fd)) != _identity(os.stat(name, dir_fd=self.directory.fd, follow_symlinks=False)): held('audit_path_changed')
        except PersonalRuntimeError: raise
        except Exception: held('audit_write_uncertain')
        finally: os.close(fd)

    def close(self):
        self.closed = True; self.credentials = None; self.directory.close()


@contextlib.contextmanager
def activate(path, digest, *, profile=None, store_factory=None, transport=None, build_fn=None):
    if current() is not None: held('nested_context_refused')
    from google_kit.registry import all_specs
    operations = [dict(name=s.name, scopes=list(s.scopes), posture=s.posture, flag=s.flag) for s in all_specs()]
    context = Context(path, digest, operations)
    if profile is not None and profile != context.data['profile']: held('profile_override_refused')
    runtime = Runtime(context, store_factory=store_factory, transport=transport, build_fn=build_fn)
    token = _CURRENT.set(runtime)
    try: yield runtime
    finally: _CURRENT.reset(token); runtime.close()


@contextlib.contextmanager
def operation(spec, profile=None):
    runtime = current()
    if runtime is None: yield; return
    with runtime.operation(spec, profile): yield
