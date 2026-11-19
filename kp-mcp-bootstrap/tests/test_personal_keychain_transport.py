"""Keychain write transport is exercised through mocked OS process boundaries."""
import subprocess
import os
import json
from unittest.mock import patch
import pytest
from kp_mcp_bootstrap import secrets as s
from kp_mcp_bootstrap.errors import SecretStoreError
from kp_mcp_bootstrap import _keychain_write as native

SECRET='SYNTHETIC_SECRET_$(never_execute)_"_quote_\\_end'

def test_actual_write_subprocess_argv_and_error_never_contain_secret():
    with patch.object(s.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','')) as run:
        s._run_security(['add-generic-password','-s','google-kit','-a','personal-fixture:access_token','-w',SECRET])
    args,kw=run.call_args
    assert args[0][1:4]==['-I','-S','-B'] and args[0][-1].endswith('/_keychain_write.py') and SECRET not in repr(args)
    assert json.loads(kw['input'])['value']==SECRET
    assert 'shell' not in kw and kw['timeout']==15 and kw['capture_output'] and kw['encoding']=='utf-8'

@pytest.mark.parametrize('value',['bad\0next','A'*(native.MAX_VALUE_BYTES+1),'\ud800'],ids=['nul','over-bound','invalid-unicode'])
def test_unrepresentable_write_is_refused_before_any_process(value):
    with patch.object(s.subprocess,'run',side_effect=AssertionError('unexpected process')):
        with pytest.raises(SecretStoreError) as e:s._run_security(['add-generic-password','-s','google-kit','-a','p:k','-w',value])
    assert value not in str(e.value)

def test_create_has_no_update_or_predelete_path_and_refuses_duplicate():
    with patch.object(s.sys,'platform','darwin'),patch.object(s,'_run_security',return_value=subprocess.CompletedProcess([],45,'','duplicate '+SECRET)) as run:
        with pytest.raises(SecretStoreError) as e:s.KeychainSecretStore('personal-fixture').create('access_token',SECRET)
    assert run.call_count==1 and '-U' not in run.call_args.args[0] and run.call_args.args[0][0]=='add-generic-password'
    assert SECRET not in str(e.value)

@pytest.mark.parametrize('method',['set','create'])
def test_helper_error_stderr_is_a_refusal_even_with_zero_process_exit(method):
    with patch.object(s.sys,'platform','darwin'),patch.object(s,'_run_security',return_value=subprocess.CompletedProcess([],0,'',SECRET)):
        with pytest.raises(SecretStoreError) as e:getattr(s.KeychainSecretStore('personal-fixture'),method)('access_token',SECRET)
    assert SECRET not in str(e.value)

def test_prevalidate_all_create_fields_never_accesses_OS_store():
    with patch.object(s,'_run_security',side_effect=AssertionError('unexpected process')):
        s.KeychainSecretStore('personal-fixture').validate_create('client_secret',SECRET)

def test_write_child_has_no_loader_proxy_or_python_injection_environment(monkeypatch):
    before={k:os.environ.get(k) for k in ('HOME','CODEX_HOME')}
    for key in ('DYLD_INSERT_LIBRARIES','DYLD_LIBRARY_PATH','PYTHONPATH','HTTP_PROXY','HTTPS_PROXY','SSH_AUTH_SOCK'):
        monkeypatch.setenv(key,'synthetic-injection-value')
    with patch.object(s.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','')) as run:
        s._run_security(['add-generic-password','-s','google-kit','-a','p:k','-w',SECRET])
    env=run.call_args.kwargs['env']
    assert not any(key in env for key in ('DYLD_INSERT_LIBRARIES','DYLD_LIBRARY_PATH','PYTHONPATH','HTTP_PROXY','HTTPS_PROXY','SSH_AUTH_SOCK'))
    assert {k:env.get(k) for k in ('HOME','CODEX_HOME')}==before
    assert all((k in env)==(k in os.environ) for k in ('HOME','CODEX_HOME'))

class API:
    def __init__(self,status=0):self.events=[];self.status=status;self.find_status=0;self.modify_status=0
    def copy_default(self):self.events.append(('default',));return 0,101
    def add(self,keychain,service,account,value):self.events.append(('add',keychain,service,account,value));return self.status
    def find(self,keychain,service,account):self.events.append(('find',keychain,service,account));return self.find_status,202
    def modify(self,item,value):self.events.append(('modify',item,value));return self.modify_status
    def release(self,ref):self.events.append(('release',ref))

def payload(value=SECRET,update=False):return {'service':'google-kit','account':'personal-fixture:access_token','value':value,'update':update}

@pytest.mark.parametrize('value',['✓'*5000,'line1\nline2\rline3',SECRET,''])
def test_native_boundary_preserves_entire_utf8_value_without_argument_parser(value):
    api=API();text,fields=native.encode_payload(payload(value));decoded=json.loads(text)
    assert native.apply(decoded,api)
    assert api.events==[('default',),('add',101,b'google-kit',b'personal-fixture:access_token',value.encode()),('release',101)]

def test_duplicate_create_never_searches_modifies_or_deletes_existing_item():
    api=API(native.DUPLICATE_ITEM);assert not native.apply(payload(),api)
    assert [e[0] for e in api.events]==['default','add','release']

def test_legacy_update_modifies_only_returned_item_without_reading_password_data():
    api=API(native.DUPLICATE_ITEM);assert native.apply(payload(update=True),api)
    assert api.events[-3:]==[('modify',202,SECRET.encode()),('release',202),('release',101)]

@pytest.mark.parametrize('which',['find','modify'])
def test_native_update_error_releases_all_retained_handles_without_retry(which):
    api=API(native.DUPLICATE_ITEM);setattr(api,which+'_status',-1)
    assert not native.apply(payload(update=True),api)
    assert api.events[-2:]==[('release',202),('release',101)]
    assert sum(e[0]=='add' for e in api.events)==1

def test_invalid_payload_is_refused_before_native_default_keychain_lookup():
    api=API();v=payload();v['update']=1
    with pytest.raises(ValueError):native.apply(v,api)
    assert api.events==[]
