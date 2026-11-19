"""Offline full consumer-path regressions; all credentials/accounts are synthetic."""
from __future__ import annotations

import base64
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import time
from unittest.mock import patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from google.auth import crypt, jwt

import google_kit
from google_kit.registry import all_specs, get
from google_kit.core import personal_runtime as p

CLIENT = 'synthetic-client.apps.googleusercontent.com'
EMAIL = 'owner@example.invalid'
SUBJECT = '1234567890'
ACCESS = 'SYNTHETIC_NEW_ACCESS_TOKEN_NEVER_A_CREDENTIAL'
REFRESH = 'SYNTHETIC_NEW_REFRESH_TOKEN_NEVER_A_CREDENTIAL'
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
NAME = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'synthetic-fixture.invalid')])
NOW = dt.datetime.now(dt.timezone.utc)
CERT = x509.CertificateBuilder().subject_name(NAME).issuer_name(NAME).public_key(KEY.public_key()).serial_number(1001).not_valid_before(NOW-dt.timedelta(days=1)).not_valid_after(NOW+dt.timedelta(days=1)).sign(KEY, hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode()
SIGNER = crypt.RSASigner.from_string(PEM, key_id='fixture-key')


def encoded(value): return json.dumps(value, sort_keys=True).encode()
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


class Store:
    profile = 'personal-fixture'
    def __init__(self):
        self.values = dict(client_id=CLIENT, client_secret='SYNTHETIC_CLIENT_SECRET',
            access_token='SYNTHETIC_OLD_ACCESS', refresh_token='SYNTHETIC_OLD_REFRESH')
        self.reads = []; self.writes = []; self.on_set = None
    def get(self, key): self.reads.append(key); return self.values[key]
    def set(self, key, value):
        self.writes.append(key)
        if self.on_set: self.on_set(key, value)
        self.values[key] = value


class Transport(p.PersonalTransport):
    def __init__(self):
        super().__init__(); self.calls = []; self.patch_response = {}; self.patch_claims = {}
        self.on_exchange = None; self.bad_signature = False
    def request(self, host, path, method, body=None):
        assert (host, path, method, body) == ('www.googleapis.com', '/oauth2/v1/certs', 'GET', None)
        self.calls.append('certificates')
        return encoded({'fixture-key': CERT})
    def exchange(self, before, scopes):
        assert before['client_id'] == CLIENT
        self.calls.append('refresh')
        claims = dict(iss='https://accounts.google.com', aud=CLIENT, azp=CLIENT, sub=SUBJECT,
            email=EMAIL, email_verified=True, iat=int(time.time()), exp=int(time.time())+3600,
            at_hash=base64.urlsafe_b64encode(hashlib.sha256(ACCESS.encode()).digest()[:16]).rstrip(b'=').decode())
        claims.update(self.patch_claims)
        token = jwt.encode(SIGNER, claims).decode()
        if self.bad_signature:
            parts = token.split('.'); parts[2] = ('A' if parts[2][0] != 'A' else 'B')+parts[2][1:]; token='.'.join(parts)
        out = dict(access_token=ACCESS, refresh_token=REFRESH, token_type='Bearer',
            expires_in=3600, scope=' '.join(scopes), id_token=token)
        out.update(self.patch_response)
        if self.on_exchange: self.on_exchange()
        return out


class Service:
    def __init__(self): self.calls = []
    def tasklists(self): self.calls.append('tasklists'); return self
    def list(self, **kwargs): self.calls.append(('list', kwargs)); return self
    def execute(self): return {'items': [{'id': 'synthetic-list', 'title': 'Synthetic seeds'}]}


class Harness:
    def __init__(self, root):
        self.root = root; self.config = root/'config'; self.config.mkdir(mode=0o700)
        self.authorizations = self.config/'authorizations'; self.authorizations.mkdir(mode=0o700)
        self.auth_file = self.authorizations/'personal-fixture.json'
        self.ops = [dict(name=s.name, scopes=list(s.scopes), posture=s.posture, flag=s.flag) for s in all_specs()]
        self.grants = {s.name: 1 for s in all_specs() if s.flag}
        self.write_auth()
        scopes = sorted({x for s in all_specs() for x in s.scopes}|{'openid', 'email'})
        self.data = dict(schema='google-kit/personal-runtime-context/v1', profile='personal-fixture',
            expected_email=EMAIL, expected_subject=SUBJECT, expected_client_id=CLIENT,
            expected_project_id='personal-fixture-project', config_dir=str(self.config),
            scopes=scopes, inventory_sha256=p.inventory_digest(self.ops),
            allowed_operations=[s.name for s in all_specs()], authorization_file_sha256=digest(self.auth_file), extra_flags=[])
        self.context_file = root/'context.json'; self.write_context()
        self.store = Store(); self.transport = Transport(); self.builds = []; self.service = Service()
    def write_auth(self): self.auth_file.write_bytes(encoded(dict(schema=1, tools=self.grants))); self.auth_file.chmod(0o600)
    def write_context(self): self.context_file.write_bytes(encoded(self.data)); self.context_file.chmod(0o600); self.sha = digest(self.context_file)
    def build(self, api, version, **kwargs): self.builds.append((api, version, kwargs)); return self.service
    def activate(self):
        return p.activate(self.context_file, self.sha, store_factory=lambda profile: self.store,
                          transport=self.transport, build_fn=self.build)
    @property
    def journal(self): return self.config/'.personal-refresh-personal-fixture.json'
    def call(self, op='tasks.list_lists'):
        from google_kit.core.auth import build_service_for_op
        with self.activate() as runtime:
            with p.operation(get(op)):
                service = build_service_for_op(op)
                assert service is self.service
            return runtime


@pytest.fixture
def h(tmp_path): return Harness(tmp_path)


def test_complete_signed_refresh_service_and_persistence(h):
    old = (os.environ.get('HOME'), os.environ.get('CODEX_HOME'))
    h.call()
    assert h.transport.calls == ['refresh', 'certificates']
    assert h.store.writes == ['refresh_token', 'access_token']
    assert h.store.values['access_token'] == ACCESS and h.store.values['refresh_token'] == REFRESH
    assert json.loads(h.journal.read_text())['state'] == 'committed'
    assert h.builds[0][:2] == ('tasks', 'v1')
    assert p.current() is None and (os.environ.get('HOME'), os.environ.get('CODEX_HOME')) == old


@pytest.mark.parametrize('field,value', [
    ('sub', '9999999'), ('aud', 'wrong.apps.googleusercontent.com'),
    ('azp', 'wrong.apps.googleusercontent.com'), ('iss', 'https://wrong.invalid'),
    ('email', 'wrong@example.invalid'), ('email_verified', False), ('email_verified', 'true'),
    ('iat', int(time.time())+7200), ('exp', int(time.time())-60),
    ('at_hash', 'wrong-access-binding'), ('sub', None), ('aud', [CLIENT]),
])
def test_identity_mismatch_never_persists_and_requires_recovery(h, field, value):
    h.transport.patch_claims[field] = value
    with pytest.raises(p.PersonalRuntimeError): h.call()
    assert not h.store.writes and json.loads(h.journal.read_text())['state'] == 'pending'
    calls = len(h.transport.calls)
    h.transport.patch_claims.clear()
    with pytest.raises(p.PersonalRuntimeError, match='refresh_recovery_required'): h.call()
    assert len(h.transport.calls) == calls


def test_bad_signature_cannot_persist(h):
    h.transport.bad_signature = True
    with pytest.raises(p.PersonalRuntimeError, match='id_token_verification_failed'): h.call()
    assert not h.store.writes and h.transport.calls == ['refresh', 'certificates']


@pytest.mark.parametrize('field,value', [
    ('token_type', 'MAC'), ('expires_in', True), ('expires_in', 30), ('expires_in', 999999),
    ('scope', 'openid email'), ('scope', None), ('access_token', ''), ('id_token', None),
    ('refresh_token', ''), ('access_token', 'bad\nvalue'), ('scope', 'openid openid'),
])
def test_invalid_refresh_response_never_persists(h, field, value):
    h.transport.patch_response[field] = value
    with pytest.raises(p.PersonalRuntimeError): h.call()
    assert not h.store.writes and json.loads(h.journal.read_text())['state'] == 'pending'


def test_absent_id_token_is_held_without_diagnostic_fallback(h):
    h.transport.patch_response['id_token'] = ''
    with pytest.raises(p.PersonalRuntimeError): h.call()
    assert h.transport.calls == ['refresh'] and not h.store.writes


def test_no_rotation_retains_current_refresh(h):
    original = h.transport.exchange
    def exchange(before, scopes):
        out = original(before, scopes); del out['refresh_token']; return out
    h.transport.exchange = exchange
    h.call()
    assert h.store.writes == ['access_token'] and h.store.values['refresh_token'] == 'SYNTHETIC_OLD_REFRESH'


def test_two_serial_refreshes_reread_rotated_token(h):
    seen = []; original = h.transport.exchange
    def exchange(before, scopes): seen.append(before['refresh_token']); return original(before, scopes)
    h.transport.exchange = exchange
    h.call(); h.call()
    assert seen == ['SYNTHETIC_OLD_REFRESH', REFRESH]


def test_changed_credentials_after_exchange_are_preserved(h):
    h.transport.on_exchange = lambda: h.store.values.update(client_secret='SYNTHETIC_FOREIGN_SECRET')
    with pytest.raises(p.PersonalRuntimeError, match='credentials_changed'): h.call()
    assert not h.store.writes and h.store.values['client_secret'] == 'SYNTHETIC_FOREIGN_SECRET'


def test_changed_context_after_exchange_cannot_persist(h):
    h.transport.on_exchange = lambda: h.context_file.write_bytes(b'{"foreign":true}')
    with pytest.raises(p.PersonalRuntimeError, match='context_changed'): h.call()
    assert not h.store.writes and h.context_file.read_bytes() == b'{"foreign":true}'


def test_partial_access_write_is_held_and_never_retried(h):
    def failed(key, value):
        if key == 'access_token': raise RuntimeError('SYNTHETIC failure not to expose')
    h.store.on_set = failed
    with pytest.raises(p.PersonalRuntimeError, match='refresh_outcome_uncertain'): h.call()
    assert h.store.values['refresh_token'] == REFRESH
    assert h.store.values['access_token'] == 'SYNTHETIC_OLD_ACCESS'
    assert json.loads(h.journal.read_text())['state'] == 'pending'
    h.store.on_set = None; calls = len(h.transport.calls)
    with pytest.raises(p.PersonalRuntimeError, match='refresh_recovery_required'): h.call()
    assert len(h.transport.calls) == calls


@pytest.mark.parametrize('setting', ['GOOGLE_API_USE_CLIENT_CERTIFICATE','GOOGLE_API_USE_MTLS_ENDPOINT',
    'GOOGLE_CLOUD_UNIVERSE_DOMAIN','GOOGLE_APPLICATION_CREDENTIALS','GOOGLE_CLOUD_QUOTA_PROJECT'])
def test_ambient_sdk_input_refused_before_credentials_or_network(h, monkeypatch, setting):
    monkeypatch.setenv(setting, 'SYNTHETIC_UNREVIEWED')
    with pytest.raises(p.PersonalRuntimeError, match='ambient_SDK_configuration_refused'): h.call()
    assert not h.store.reads and not h.transport.calls and not h.journal.exists()


def test_poisoned_legacy_environment_cannot_select_store_config_flags_or_telemetry(h, monkeypatch):
    for key in ('GOOGLE_KIT_PROFILE','GOOGLE_KIT_CONFIG_DIR','CHAOS_LABS_ROOT',
                'GOOGLE_KIT_AUDIT_FILE','GOOGLE_KIT_OTLP_ENDPOINT','HTTPS_PROXY'):
        monkeypatch.setenv(key, 'SYNTHETIC_FORBIDDEN_LEGACY_INPUT')
    monkeypatch.setenv('GOOGLE_KIT_ENABLE_WRITES','1')
    from kp_mcp_bootstrap.config import load_config
    from google_kit.core.observability import _get_otel_tracer
    with patch('kp_mcp_bootstrap.config.load_config', side_effect=AssertionError('legacy config consulted')):
        with h.activate():
            with p.operation(get('tasks.list_lists')):
                from google_kit.core.auth import build_service_for_op
                assert build_service_for_op('tasks.list_lists') is h.service
                assert _get_otel_tracer() is None
    assert h.store.writes == ['refresh_token', 'access_token']


def test_env_write_override_cannot_bypass_personal_grant(h, monkeypatch):
    h.grants['tasks.create'] = 0; h.write_auth(); h.data['authorization_file_sha256'] = digest(h.auth_file); h.write_context()
    monkeypatch.setenv('GOOGLE_KIT_ENABLE_WRITES','1'); monkeypatch.setenv('GOOGLE_KIT_ENABLE_TASKS_WRITE','1')
    with h.activate():
        with pytest.raises(p.PersonalRuntimeError, match='operation_grant_missing'):
            with p.operation(get('tasks.create')): pass
    assert not h.store.reads and not h.transport.calls


def test_changed_grant_file_cannot_execute(h):
    h.auth_file.write_bytes(encoded(dict(schema=1,tools={})))
    with pytest.raises(p.PersonalRuntimeError, match='authorization_changed'): h.call()
    assert not h.store.reads


@pytest.mark.parametrize('field,value', [('profile','default'),('inventory_sha256','0'*64),
    ('expected_subject','not-a-subject'),('scopes',['openid','email']),('allowed_operations',['tasks.fake']),
    ('extra_flags',['GOOGLE_KIT_ENABLE_WRITES'])])
def test_invalid_or_unavailable_context_denies_before_credentials(h, field, value):
    h.data[field] = value; h.write_context()
    with pytest.raises(p.PersonalRuntimeError): h.call()
    assert not h.store.reads and not h.transport.calls


def test_context_digest_mismatch_and_symlink_denied(h):
    with pytest.raises(p.PersonalRuntimeError, match='context_digest_mismatch'):
        with p.activate(h.context_file, '0'*64): pass
    real = h.root/'original-context'; h.context_file.rename(real); h.context_file.symlink_to(real)
    with pytest.raises(p.PersonalRuntimeError):
        with h.activate(): pass
    assert not h.store.reads


def test_foreign_pending_or_linked_journal_is_never_adopted(h):
    h.journal.write_bytes(b'{"foreign":true}'); h.journal.chmod(0o600)
    with pytest.raises(p.PersonalRuntimeError, match='refresh_recovery_required'): h.call()
    assert h.journal.read_bytes() == b'{"foreign":true}' and not h.transport.calls


def test_legacy_builder_and_grant_mutators_refused_in_personal_context(h):
    from google_kit.core.client import build_authorized_service
    from google_kit.core.authz import seed_profile, set_authorization
    with h.activate():
        with pytest.raises(p.PersonalRuntimeError, match='legacy_service_builder_refused'):
            build_authorized_service('tasks','v1',h.store,client_id=CLIENT)
        for call in (lambda: seed_profile(h.store.profile), lambda: set_authorization(h.store.profile,'tasks.create',1)):
            with pytest.raises(p.PersonalRuntimeError, match='personal_grant_mutation_refused'): call()
    assert not h.store.reads and not h.store.writes


def test_all_106_authorization_and_service_injection_shapes_preserved(h):
    from google_kit.cli import _service_kwargs as cli_kwargs
    from google_kit.mcp import _service_kwargs as mcp_kwargs
    names = []
    def factory(name, **kwargs): names.append(name); return h.service
    with h.activate() as runtime:
        for spec in all_specs():
            with p.operation(spec):
                runtime.authorize(spec)
                left = cli_kwargs(spec,factory,spec.name,h.store.profile)
                right = mcp_kwargs(spec,factory)
                assert set(left) == set(right)
                if spec.name.startswith('recipes.'):
                    assert left['service']('docs') is h.service and right['service']('drive') is h.service
    assert len(list(all_specs())) == 106 and names and not h.transport.calls


def test_actual_cli_consumer_routes_to_verified_service(h):
    from google_kit.cli import main
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(['tasks','list-lists','--personal-context',str(h.context_file),'--personal-context-sha256',h.sha],
            _personal_store_factory=lambda profile:h.store,_personal_transport=h.transport,_personal_build_fn=h.build)
    result = json.loads(out.getvalue())
    assert result and h.service.calls and h.builds[0][:2] == ('tasks','v1')
    assert h.store.writes == ['refresh_token','access_token'] and p.current() is None


def test_actual_mcp_consumer_routes_to_verified_service_and_thread_context(h):
    import asyncio
    from google_kit.mcp import _invoke_tool_sync, _default_service_factory
    async def run():
        return await asyncio.to_thread(_invoke_tool_sync,get('tasks.list_lists'),{},_default_service_factory)
    with h.activate(): result = json.loads(asyncio.run(run()))
    assert result and h.builds and h.store.writes == ['refresh_token','access_token']


def test_personal_audit_and_telemetry_are_bound_to_explicit_context(h, monkeypatch):
    from google_kit.core.client import execute_api_call
    from google_kit.core.observability import _get_otel_tracer
    monkeypatch.setenv('GOOGLE_KIT_AUDIT_FILE',str(h.root/'foreign-audit'))
    monkeypatch.setenv('GOOGLE_KIT_OTLP_ENDPOINT','https://synthetic-forbidden.invalid')
    with h.activate():
        with p.operation(get('tasks.create')):
            assert _get_otel_tracer() is None
            assert execute_api_call(lambda:{'id':'synthetic-task'},op='tasks.create',posture='write') == {'id':'synthetic-task'}
    record = json.loads((h.config/'personal-audit.jsonl').read_text())
    assert record['actor'] == h.store.profile and record['op'] == 'tasks.create'
    assert not (h.root/'foreign-audit').exists() and not h.transport.calls


def test_extra_public_share_flag_needs_explicit_review(h, monkeypatch):
    from google_kit.core.flags import is_flag_enabled
    monkeypatch.setenv('GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE','1')
    with h.activate():
        with p.operation(get('drive.permissions')):
            assert not is_flag_enabled('GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE')
    h.data['extra_flags'] = ['GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE']; h.write_context()
    with h.activate():
        with p.operation(get('drive.permissions')): assert is_flag_enabled('GOOGLE_KIT_ENABLE_DRIVE_PUBLIC_SHARE')


def test_wrong_profile_and_operation_context_refuse_before_store_access(h):
    from google_kit.core.auth import build_service_for_op
    with h.activate():
        with pytest.raises(p.PersonalRuntimeError,match='operation_context_required'): build_service_for_op('tasks.list_lists')
        with pytest.raises(p.PersonalRuntimeError,match='profile_override_refused'):
            with p.operation(get('tasks.list_lists'),'default'): pass
    assert not h.store.reads


def test_aliases_are_exact_declared_equivalence_without_scope_union():
    assert p.canonical_scopes(['openid','email']) == p.canonical_scopes(['openid','https://www.googleapis.com/auth/userinfo.email'])
    with pytest.raises(p.PersonalRuntimeError,match='duplicate_scope'):
        p.canonical_scopes(['email','https://www.googleapis.com/auth/userinfo.email'])


def test_fixed_token_transport_no_proxy_redirect_retry_or_unbounded_body(h):
    calls = []
    class Response:
        status = 302
        def getheader(self,*args):return 'application/json'
        def read(self,*args):raise AssertionError('redirect body read')
    class Connection:
        def __init__(self,host,**kwargs):calls.append(('host',host,kwargs['timeout']))
        def set_debuglevel(self,level):assert level==0
        def request(self,method,path,body=None,headers=None):calls.append((method,path))
        def getresponse(self):return Response()
        def close(self):calls.append('closed')
    transport = p.PersonalTransport(_connection_factory=Connection)
    with pytest.raises(p.PersonalRuntimeError,match='provider_refused'):
        transport.exchange(h.store.values,('openid',))
    assert calls == [('host','oauth2.googleapis.com',10),('POST','/token'),'closed']


def test_wrong_client_is_refused_before_other_credential_reads(h):
    h.store.values['client_id'] = 'wrong.apps.googleusercontent.com'
    with pytest.raises(p.PersonalRuntimeError,match='client_identity_mismatch'): h.call()
    assert h.store.reads == ['client_id'] and not h.transport.calls and not h.journal.exists()


def test_directory_replacement_after_exchange_preserves_foreign_root(h):
    moved = h.root/'original-config'
    def replace():
        h.config.rename(moved); h.config.mkdir(mode=0o700)
        (h.config/'foreign').write_text('synthetic foreign edit\n')
    h.transport.on_exchange = replace
    with pytest.raises(p.PersonalRuntimeError): h.call()
    assert not h.store.writes and (h.config/'foreign').read_text() == 'synthetic foreign edit\n'
    assert json.loads((moved/h.journal.name).read_text())['state'] == 'pending'


@pytest.mark.parametrize('kind',['symlink','hardlink','fifo','public-mode'])
def test_unsafe_context_leaf_is_refused_without_reading_credentials(h, kind):
    saved = h.root/'saved-context'; h.context_file.rename(saved)
    if kind == 'symlink': h.context_file.symlink_to(saved)
    elif kind == 'hardlink': os.link(saved,h.context_file)
    elif kind == 'fifo': os.mkfifo(h.context_file,0o600)
    else: h.context_file.write_bytes(saved.read_bytes()); h.context_file.chmod(0o644)
    with pytest.raises(p.PersonalRuntimeError):
        with h.activate(): pass
    assert not h.store.reads and not h.transport.calls


@pytest.mark.parametrize('kind',['symlink','hardlink','public-mode','nonempty'])
def test_unsafe_lock_is_refused_without_token_request(h, kind):
    target = h.root/'foreign-lock'; target.write_bytes(b''); target.chmod(0o600)
    lock = h.config/'.personal-refresh-personal-fixture.lock'
    if kind == 'symlink': lock.symlink_to(target)
    elif kind == 'hardlink': os.link(target,lock)
    else:
        lock.write_bytes(b'foreign' if kind == 'nonempty' else b''); lock.chmod(0o644 if kind == 'public-mode' else 0o600)
    with pytest.raises(p.PersonalRuntimeError): h.call()
    assert not h.transport.calls and not h.store.writes and target.read_bytes() == b''


def test_reviewed_context_cannot_be_mutated_in_memory(h):
    with h.activate() as runtime:
        with pytest.raises(TypeError): runtime.data['profile'] = 'default'
        assert type(runtime.data['allowed_operations']) is tuple


def test_actual_sdk_static_service_build_and_http_boundary(h):
    from google_kit.core.auth import build_service_for_op, _SERVICE_API_MAP
    with p.activate(h.context_file,h.sha,store_factory=lambda profile:h.store,transport=h.transport):
        with p.operation(get('tasks.list_lists')):
            for prefix in _SERVICE_API_MAP:
                service = build_service_for_op(prefix+'._svc')
                assert service._http.http.follow_redirects is False
                assert service._http.http.proxy_info is None
            service = build_service_for_op('tasks.list_lists')
            for uri in ('http://www.googleapis.com/', 'https://evilgoogleapis.com/',
                        'https://www.googleapis.com.evil.invalid/', 'https://user@www.googleapis.com/',
                        'https://www.googleapis.com:444/', 'https://www.googleapis.com:bad/'):
                with pytest.raises(p.PersonalRuntimeError,match='API_endpoint_refused'):
                    service._http.request(uri)
    assert h.transport.calls == ['refresh','certificates']


def test_context_cli_forbids_legacy_auth_and_unpaired_flags(h):
    from google_kit.cli import main
    for argv in (["auth","status","--personal-context",str(h.context_file),"--personal-context-sha256",h.sha],
                 ["help","read a document","--personal-context",str(h.context_file)]):
        with pytest.raises(SystemExit) as result: main(argv)
        assert result.value.code != 0
    assert not h.store.reads and not h.transport.calls


def test_actual_sdk_expiry_callback_uses_bound_refresh_and_headers(h):
    from google.auth import _helpers
    from google_kit.core.auth import build_service_for_op
    with h.activate():
        with p.operation(get('tasks.list_lists')):
            build_service_for_op('tasks.list_lists')
            credentials = h.builds[0][2]['credentials']
            credentials.expiry = _helpers.utcnow()-dt.timedelta(seconds=1)
            headers = {}
            def forbidden(*args, **kwargs): raise AssertionError('ambient SDK refresh transport')
            credentials.before_request(forbidden,'GET','https://tasks.googleapis.com/tasks/v1/users/@me/lists',headers)
            assert headers['authorization'] == 'Bearer '+ACCESS
    assert h.transport.calls == ['refresh','certificates','refresh','certificates']
    assert h.store.writes == ['refresh_token','access_token','access_token']
    assert json.loads(h.journal.read_text())['state'] == 'committed'


def test_read_consumer_with_absent_grants_never_creates_authorizations(h):
    h.auth_file.unlink();h.authorizations.rmdir()
    h.data.update(authorization_file_sha256=None,allowed_operations=['tasks.list_lists'],
                  scopes=['openid','email','https://www.googleapis.com/auth/tasks.readonly'])
    h.write_context();h.call()
    assert not h.authorizations.exists() and h.store.writes == ['refresh_token','access_token']


def test_consumer_reads_bound_grant_bytes_without_diagnostic_authority(h):
    with patch('google_kit.core.personal_authz.read_authorizations',side_effect=AssertionError('diagnostic reader is not an execution gateway')):
        h.call()
    assert h.store.writes == ['refresh_token','access_token']


@pytest.mark.parametrize('kind',['symlink','public-mode','boolean-grant','unknown-operation'])
def test_consumer_grant_file_safety_and_closed_schema(h, kind):
    if kind == 'symlink':
        target=h.root/'foreign-grants';h.auth_file.rename(target);h.auth_file.symlink_to(target)
    elif kind == 'public-mode':h.auth_file.chmod(0o644)
    else:
        tools={'tasks.create':True} if kind=='boolean-grant' else {'tasks.fake':1}
        h.auth_file.write_bytes(encoded(dict(schema=1,tools=tools)))
        h.data['authorization_file_sha256']=digest(h.auth_file);h.write_context()
    with pytest.raises(p.PersonalRuntimeError):h.call()
    assert not h.store.reads and not h.transport.calls
