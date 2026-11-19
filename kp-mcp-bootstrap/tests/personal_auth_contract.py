"""Required stdlib-only personal-auth contract; all inputs/stores are synthetic.

This exercises the real core and helper boundaries. Package registry/CLI,
excluded cross-kit and native Keychain qualification remain separate evidence.
"""
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'google-kit/src'),str(ROOT/'kp-mcp-bootstrap/src')]
# Load the actual stdlib source components under an isolated namespace. The
# normal google_kit initializer eagerly imports all service SDKs; actual package
# initialization/registry/CLI are covered by the separate package qualification.
# No source implementation, registry or dependency is replaced by a stub here.
components=types.ModuleType('_owner_personal_auth_components')
components.__path__=[str(ROOT/'google-kit/src/google_kit/core')]
sys.modules[components.__name__]=components
login=importlib.import_module(components.__name__+'.personal_login')
inventory_digest=login.inventory_digest
from kp_mcp_bootstrap import _keychain_write as native
from kp_mcp_bootstrap import _keychain_access as native_access
from kp_mcp_bootstrap.secrets import KeychainSecretStore,_run_security

PROFILE='personal-fixture';CLIENT='fixture.apps.googleusercontent.com';PROJECT='fixture-project'
EMAIL='owner@example.net';SUBJECT='1234567890';SECRET='SYNTHETIC_CLIENT_SECRET'
ACCESS='SYNTHETIC_ACCESS_TOKEN';REFRESH='SYNTHETIC_REFRESH_TOKEN'

class Store:
    profile=PROFILE
    def __init__(self):self.data={};self.creates=[];self.fail=None
    def has(self,key):return key in self.data
    def get(self,key):return self.data[key]
    def validate_create(self,key,value):KeychainSecretStore(PROFILE).validate_create(key,value)
    def create(self,key,value):
        if key in self.data:raise RuntimeError('duplicate')
        self.data[key]=value;self.creates.append(key)
        if key==self.fail:raise RuntimeError(SECRET)
    def set(self,*args):raise AssertionError('overwrite')
    def delete(self,*args):raise AssertionError('delete')

class Transport:
    def __init__(self,store):
        self.store=store;self.callback=None
        self.info={'aud':CLIENT,'azp':CLIENT,'sub':SUBJECT,'email':EMAIL,'email_verified':True,
                   'expires_in':'3500','scope':'email openid'}
    def token_info(self,token):
        if token!=ACCESS or self.store.creates:raise AssertionError('premature persistence')
        if self.callback:self.callback()
        return self.info
    def drive_identity(self,token):raise AssertionError('unnecessary API')

class Flow:
    def __init__(self,stage):self.stage=stage;self.calls=[]
    def authorize(self,scopes):self.calls.append('authorize');return 'synthetic-code'
    def exchange(self,code):
        self.calls.append('exchange');tokens={'access_token':ACCESS,'refresh_token':REFRESH,
                                            'token_type':'Bearer','scope':'email openid'}
        self.stage.set('access_token',ACCESS);self.stage.set('refresh_token',REFRESH);return tokens

class NativeFixture:
    def __init__(self,status):self.status=status;self.events=[]
    def copy_default(self):self.events.append('default');return 0,101
    def add(self,keychain,service,account,value):self.events.append(('add',value));return self.status
    def find(self,keychain,service,account):self.events.append('find-no-password-data');return 0,202
    def modify(self,item,value):self.events.append(('modify',item,value));return 0
    def release(self,ref):self.events.append(('release',ref))

class PersonalAuthContract(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='personal-auth-contract-')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()  # macOS temp aliases must not bypass the no-symlink product guard.
        self.config=self.root/'config';self.config.mkdir(mode=0o700)
        self.client=self.root/'client.json';self.client.write_text(json.dumps({'installed':{
            'client_id':CLIENT,'client_secret':SECRET,'project_id':PROJECT,
            'auth_uri':'https://accounts.google.com/o/oauth2/v2/auth','token_uri':'https://oauth2.googleapis.com/token'}}));self.client.chmod(0o600)
        self.ops=json.loads((ROOT/'google-kit/tests/canonical-inventory.json').read_text())
        self.assertEqual(len(self.ops),106)
        self.store=Store();self.transport=Transport(self.store);self.flows=[]
        def factory(stage,*a,**kw):f=Flow(stage);self.flows.append(f);return f
        self.args=dict(profile=PROFILE,expected_email=EMAIL,expected_subject=SUBJECT,
            expected_client_id=CLIENT,expected_project_id=PROJECT,client_file=str(self.client),
            client_file_sha256=hashlib.sha256(self.client.read_bytes()).hexdigest(),
            config_dir=str(self.config),expected_inventory_digest=inventory_digest(self.ops),
            operations=self.ops,requested_scopes=['openid','email'],store_factory=lambda _:self.store,
            flow_factory=factory,transport_factory=lambda:self.transport)
    def run_login(self):return login.login_personal(**self.args)
    def assert_redacted(self,result):
        raw=json.dumps(result)
        for value in (CLIENT,SECRET,ACCESS,REFRESH):self.assertNotIn(value,raw)
    def test_complete_core_verifies_identity_then_creates_access_last(self):
        result=self.run_login();self.assertEqual(result['status'],'verified_credentials_created')
        self.assertEqual(self.store.creates,list(login.KEYS));self.assertEqual(self.flows[0].stage.values,{})
        self.assertFalse(result['execution_authorized']);self.assert_redacted(result)
    def test_wrong_account_client_email_expiry_and_scope_never_persist(self):
        for field,value in [('sub','999'),('aud','foreign'),('azp','foreign'),('email','other@example.net'),
                            ('email_verified',False),('expires_in','1'),('scope','email openid https://www.googleapis.com/auth/drive')]:
            with self.subTest(field=field):
                before=self.transport.info.copy();self.transport.info[field]=value
                result=self.run_login();self.assertEqual(result['status'],'held')
                self.assertEqual(self.store.creates,[]);self.assert_redacted(result);self.transport.info=before
    def test_existing_profile_is_preserved_without_flow(self):
        self.store.data['client_id']='FOREIGN';result=self.run_login()
        self.assertEqual(result['reason'],'profile_not_empty');self.assertEqual(self.flows,[])
        self.assertEqual(self.store.data,{'client_id':'FOREIGN'})
    def test_inventory_drift_refuses_before_store(self):
        self.args['expected_inventory_digest']='0'*64
        self.args['store_factory']=lambda _:self.fail('unexpected store')
        self.assertEqual(self.run_login()['reason'],'inventory_changed')
    def test_client_file_change_during_browser_flow_prevents_persistence(self):
        self.transport.callback=lambda:self.client.write_text('{"foreign":true}')
        result=self.run_login();self.assertEqual(result['reason'],'client_file_changed')
        self.assertEqual(self.store.creates,[]);self.assertEqual(self.client.read_text(),'{"foreign":true}')
    def test_failure_is_held_with_unknown_last_create_and_no_retry_delete_or_update(self):
        self.store.fail='client_secret';result=self.run_login()
        self.assertEqual(result['status'],'held');self.assertEqual(result['uncertain_create_key'],'client_secret')
        self.assertTrue(result['partial_profile_requires_review']);self.assertNotIn('access_token',self.store.data)
        second=self.run_login();self.assertEqual(second['reason'],'profile_not_empty');self.assertEqual(len(self.flows),1)
        self.assert_redacted(result)
    def test_native_create_duplicate_cannot_reach_update_or_password_read(self):
        api=NativeFixture(native.DUPLICATE_ITEM)
        self.assertFalse(native.apply({'service':'google-kit','account':'p:k','value':SECRET,'update':False},api))
        self.assertEqual(api.events,['default',('add',SECRET.encode()),('release',101)])
    def test_native_update_preserves_full_unicode_and_multiline_bytes(self):
        value='✓'*5000+'\n'+SECRET;api=NativeFixture(native.DUPLICATE_ITEM)
        self.assertTrue(native.apply({'service':'google-kit','account':'p:k','value':value,'update':True},api))
        self.assertIn(('modify',202,value.encode()),api.events)
        self.assertEqual(api.events[-2:],[('release',202),('release',101)])
    def test_native_invalid_fields_refuse_before_any_keychain_lookup(self):
        api=NativeFixture(0)
        with self.assertRaises(ValueError):native.apply({'service':'google-kit','account':'p:k','value':SECRET,'update':1},api)
        self.assertEqual(api.events,[])
    def test_process_boundary_keeps_complete_secret_out_of_argv(self):
        value='✓'*5000+'\n'+SECRET
        with patch('subprocess.run',return_value=subprocess.CompletedProcess([],0,'','')) as run:
            _run_security(['add-generic-password','-s','google-kit','-a','p:k','-w',value,'-U'])
        self.assertNotIn(value,repr(run.call_args.args));self.assertEqual(json.loads(run.call_args.kwargs['input'])['value'],value)
        self.assertEqual(run.call_args.args[0][1:4],['-I','-S','-B'])

    def test_native_read_process_preserves_all_unicode_and_trailing_lines(self):
        value='✓'*5000+'\r\n'+SECRET+'\n\n'
        with patch('sys.platform','darwin'),patch('subprocess.run',return_value=subprocess.CompletedProcess([],0,json.dumps({'value':value}),'')) as run:
            self.assertEqual(KeychainSecretStore(PROFILE).get('fixture'),value)
        self.assertEqual(run.call_args.args[0][1:4],['-I','-S','-B'])
        self.assertTrue(run.call_args.args[0][-1].endswith('/_keychain_access.py'))
        self.assertEqual(json.loads(run.call_args.kwargs['input']),{'operation':'get','service':'google-kit','account':PROFILE+':fixture'})
        self.assertNotIn(PROFILE,repr(run.call_args.args));self.assertEqual(run.call_args.kwargs['timeout'],15)

    def test_native_presence_and_delete_never_read_password_data(self):
        class AccessFixture:
            def __init__(self):self.events=[]
            def copy_default(self):self.events.append('default');return 0,101
            def find(self,*args):self.events.append('find');return 0,202
            def read(self,*args):raise AssertionError('password read')
            def delete(self,item):self.events.append(('delete',item));return 0
            def release(self,ref):self.events.append(('release',ref))
        for operation in ('has','delete'):
            api=AccessFixture();self.assertEqual(native_access.apply({'operation':operation,'service':'google-kit','account':'p:k'},api),(0,None))
            self.assertEqual(api.events[-2:],[('release',202),('release',101)])
            self.assertEqual(sum(type(e) is tuple and e[0]=='delete' for e in api.events),int(operation=='delete'))

    def test_native_read_invalid_request_refuses_before_lookup(self):
        api=NativeFixture(0)
        with self.assertRaises(ValueError):native_access.apply({'operation':'update','service':'google-kit','account':'p:k'},api)
        self.assertEqual(api.events,[])

    def test_native_read_bad_frame_has_no_plaintext_or_cli_fallback(self):
        with patch('sys.platform','darwin'),patch('subprocess.run',return_value=subprocess.CompletedProcess([],0,SECRET,'')) as run:
            with self.assertRaises(Exception) as error:KeychainSecretStore(PROFILE).get('fixture')
        self.assertNotIn(SECRET,str(error.exception));self.assertEqual(run.call_count,1)

    def test_native_missing_item_is_distinct_from_native_failure(self):
        class AccessFixture:
            def __init__(self,status):self.status=status;self.events=[]
            def copy_default(self):return 0,101
            def find(self,*args):return self.status,None
            def release(self,ref):self.events.append(ref)
        for status,expected in ((native_access.NOT_FOUND,44),(-1,1)):
            api=AccessFixture(status)
            self.assertEqual(native_access.apply({'operation':'get','service':'google-kit','account':'p:k'},api),(expected,None))
            self.assertEqual(api.events,[101])

    def test_native_read_retains_handles_until_value_read_and_releases_on_error(self):
        class AccessFixture:
            def __init__(self):self.events=[]
            def copy_default(self):return 0,101
            def find(self,*args):return 0,202
            def read(self,item):self.events.append(('read',item));raise RuntimeError('synthetic failure')
            def release(self,ref):self.events.append(('release',ref))
        api=AccessFixture()
        with self.assertRaises(RuntimeError):native_access.apply({'operation':'get','service':'google-kit','account':'p:k'},api)
        self.assertEqual(api.events,[('read',202),('release',202),('release',101)])


# This required stdlib gate exercises the real consumer storage/context primitives.
# Signed refresh, actual registry/CLI/MCP/SDK paths remain separate package tests.
consumer=importlib.import_module(components.__name__+'.personal_runtime')

class PersonalConsumerStorageContract(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='personal-consumer-contract-')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()  # macOS temp aliases must not bypass the no-symlink product guard.
        self.root.chmod(0o700)
    def test_owned_directory_survives_its_own_regular_file_creation(self):
        directory=consumer.Directory(self.root);self.addCleanup(directory.close)
        directory.private();(self.root/'synthetic').write_text('fixture');directory.check()
    def test_foreign_directory_replacement_is_held(self):
        directory=consumer.Directory(self.root);self.addCleanup(directory.close)
        original=self.root.with_name(self.root.name+'-original')
        self.root.rename(original);self.root.mkdir(mode=0o700)
        self.addCleanup(lambda:original.rmdir())
        with self.assertRaises(consumer.PersonalRuntimeError):directory.check()
    def test_exclusive_journal_creation_never_adopts_foreign_bytes(self):
        directory=consumer.Directory(self.root);self.addCleanup(directory.close)
        (self.root/'journal').write_text('foreign');(self.root/'journal').chmod(0o600)
        with self.assertRaises(consumer.PersonalRuntimeError):directory.replace('journal',{'state':'pending'},None)
        self.assertEqual((self.root/'journal').read_text(),'foreign')
    def test_journal_updates_require_exact_preimage_and_readback(self):
        directory=consumer.Directory(self.root);self.addCleanup(directory.close)
        first=directory.replace('journal',{'state':'pending'},None)
        second=directory.replace('journal',{'state':'committed'},first)
        self.assertEqual(json.loads(second[0]),{'state':'committed'})
        with self.assertRaises(consumer.PersonalRuntimeError):directory.replace('journal',{'state':'pending'},first)
        self.assertEqual(json.loads((self.root/'journal').read_text()),{'state':'committed'})
    def test_symlink_file_cannot_be_read_as_context_or_journal(self):
        directory=consumer.Directory(self.root);self.addCleanup(directory.close)
        target=self.root/'target';target.write_text('synthetic');target.chmod(0o600)
        (self.root/'alias').symlink_to(target)
        with self.assertRaises(consumer.PersonalRuntimeError):directory.read('alias')
    def test_hardlink_and_public_file_are_refused(self):
        import os
        directory=consumer.Directory(self.root);self.addCleanup(directory.close)
        target=self.root/'target';target.write_text('synthetic');target.chmod(0o600)
        os.link(target,self.root/'hardlink')
        with self.assertRaises(consumer.PersonalRuntimeError):directory.read('hardlink')
        public=self.root/'public';public.write_text('synthetic');public.chmod(0o644)
        with self.assertRaises(consumer.PersonalRuntimeError):directory.read('public')
    def test_scope_aliases_are_exact_and_duplicate_equivalence_refuses(self):
        self.assertEqual(consumer.canonical_scopes(['openid','email']),consumer.canonical_scopes(['openid','https://www.googleapis.com/auth/userinfo.email']))
        with self.assertRaises(consumer.PersonalRuntimeError):consumer.canonical_scopes(['email','https://www.googleapis.com/auth/userinfo.email'])
    def test_duplicate_context_json_and_changed_digest_are_refused(self):
        with self.assertRaises(consumer.PersonalRuntimeError):consumer._json(b'{"schema":1,"schema":2}')
        path=self.root/'context';path.write_text('{}');path.chmod(0o600)
        with self.assertRaises(consumer.PersonalRuntimeError):consumer.Context(path,'0'*64,[])

if __name__=='__main__':unittest.main(verbosity=2)
