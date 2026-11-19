"""Native access boundary tests use synthetic values and fake OS references only."""
import io
import ctypes
import json
import os
import subprocess
from unittest.mock import patch
from types import SimpleNamespace
import pytest
from kp_mcp_bootstrap import secrets as store
from kp_mcp_bootstrap import _keychain_access as access
from kp_mcp_bootstrap.errors import SecretStoreError

VALUES=['','ascii','✓'*5000,'line1\nline2\rline3\r\n','one\n\n','  leading and trailing  ','$(never_execute)_"_\\_value']

class API:
    def __init__(self,value=b'fixture',default=0,find=0,read=0,delete=0):
        self.value=value;self.default_status=default;self.find_status=find
        self.read_status=read;self.delete_status=delete;self.events=[]
    def copy_default(self):self.events.append('default');return self.default_status,101
    def find(self,keychain,service,account):self.events.append(('find',keychain,service,account));return self.find_status,202
    def read(self,item):self.events.append(('read',item));return self.read_status,self.value
    def delete(self,item):self.events.append(('delete',item));return self.delete_status
    def release(self,item):self.events.append(('release',item))

def payload(operation='get'):
    return dict(operation=operation,service='google-kit',account='synthetic-profile:fixture')

@pytest.mark.parametrize('value',VALUES)
def test_native_get_preserves_complete_opaque_utf8_value_and_releases_refs(value):
    api=API(value.encode())
    assert access.apply(payload(),api)==(0,value)
    assert api.events==['default',('find',101,b'google-kit',b'synthetic-profile:fixture'),('read',202),('release',202),('release',101)]
    framed=json.dumps({'value':value},ensure_ascii=True)+'\n'
    assert access.parse_result(framed)==value

@pytest.mark.parametrize('operation',['has','delete'])
def test_non_read_operations_never_request_password_data(operation):
    api=API();assert access.apply(payload(operation),api)==(0,None)
    assert not any(type(e) is tuple and e[0]=='read' for e in api.events)
    assert sum(type(e) is tuple and e[0]=='delete' for e in api.events)==(operation=='delete')
    assert api.events[-2:]==[('release',202),('release',101)]

@pytest.mark.parametrize('operation',['get','has','delete'])
def test_exact_not_found_does_not_read_delete_or_retry(operation):
    api=API(find=access.NOT_FOUND);assert access.apply(payload(operation),api)==(44,None)
    assert api.events==['default',('find',101,b'google-kit',b'synthetic-profile:fixture'),('release',202),('release',101)]

@pytest.mark.parametrize('stage',['default','find','read','delete'])
def test_unexpected_native_error_is_not_absence_and_releases_retained_refs(stage):
    api=API(**{stage:-1});operation='delete' if stage=='delete' else 'get'
    assert access.apply(payload(operation),api)==(1,None)
    assert api.events[-1]==('release',101)
    if stage!='default':assert api.events[-2]==('release',202)

@pytest.mark.parametrize('raw',[b'\xff',b'bad\0next',b'x'*(access.MAX_VALUE_BYTES+1)])
def test_invalid_or_overbound_native_value_refuses_without_truncation(raw):
    api=API(raw)
    with pytest.raises((ValueError,UnicodeError)):access.apply(payload(),api)
    assert api.events[-2:]==[('release',202),('release',101)]

@pytest.mark.parametrize('change',[{'operation':'update'},{'operation':True},{'service':''},{'account':'bad\0next'},
    {'account':'\ud800'},{'account':'x'*4097},{'extra':True}])
def test_bad_access_request_fails_before_default_keychain_lookup(change):
    api=API()
    with pytest.raises(ValueError):access.apply({**payload(),**change},api)
    assert api.events==[]

@pytest.mark.parametrize('raw',['not-json','{}','{"value":1}','{"value":"a","value":"b"}',
    '{"value":"a","extra":true}',json.dumps({'value':'bad\0next'}),json.dumps({'value':'x'*(access.MAX_VALUE_BYTES+1)})])
def test_bad_read_frames_never_fall_back_to_cli_or_plaintext(raw):
    with patch.object(store.sys,'platform','darwin'),patch.object(store.subprocess,'run',return_value=subprocess.CompletedProcess([],0,raw,'')) as run:
        with pytest.raises(SecretStoreError) as error:store.KeychainSecretStore('synthetic-profile').get('fixture')
    assert 'bad\0next' not in str(error.value) and run.call_count==1

@pytest.mark.parametrize('value',VALUES)
def test_actual_store_get_decodes_framing_without_stripping_value(value):
    with patch.object(store.sys,'platform','darwin'),patch.object(store.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps({'value':value}),'')) as run:
        assert store.KeychainSecretStore('synthetic-profile').get('fixture')==value
    args=run.call_args.args[0];kw=run.call_args.kwargs
    assert args[0]==store.sys.executable and args[1:4]==['-I','-S','-B'] and args[-1].endswith('/_keychain_access.py')
    assert 'synthetic-profile' not in repr(args) and kw['timeout']==15 and kw['encoding']=='utf-8' and kw['capture_output']
    assert json.loads(kw['input'])==payload()

@pytest.mark.parametrize('operation',['get','has','delete'])
def test_access_child_filters_injection_environment_preserving_actual_homes(operation,monkeypatch):
    before={k:os.environ.get(k) for k in ('HOME','CODEX_HOME')}
    forbidden=('PYTHONPATH','BASH_ENV','DYLD_INSERT_LIBRARIES','DYLD_LIBRARY_PATH','HTTP_PROXY','HTTPS_PROXY','SSH_AUTH_SOCK')
    for key in forbidden:monkeypatch.setenv(key,'synthetic-injection')
    output=json.dumps({'value':'fixture'}) if operation=='get' else ''
    with patch.object(store.sys,'platform','darwin'),patch.object(store.subprocess,'run',return_value=subprocess.CompletedProcess([],0,output,'')) as run:
        getattr(store.KeychainSecretStore('synthetic-profile'),operation)('fixture')
    env=run.call_args.kwargs['env'];assert not any(k in env for k in forbidden)
    assert {k:env.get(k) for k in ('HOME','CODEX_HOME')}==before
    assert all((k in env)==(k in os.environ) for k in ('HOME','CODEX_HOME'))

@pytest.mark.parametrize('operation',['get','has','delete'])
def test_access_timeout_preserves_fixed_limit_and_hides_exception_output(operation):
    with patch.object(store.sys,'platform','darwin'),patch.object(store.subprocess,'run',side_effect=subprocess.TimeoutExpired(['helper'],15,output='SYNTHETIC_SECRET',stderr='SYNTHETIC_SECRET')):
        with pytest.raises(SecretStoreError) as error:getattr(store.KeychainSecretStore('synthetic-profile'),operation)('fixture')
    assert str(error.value)=='Keychain operation timed out after 15 seconds.'

@pytest.mark.parametrize('operation',['get','has','delete'])
def test_access_stderr_is_refusal_even_when_process_exit_is_zero(operation):
    with patch.object(store.sys,'platform','darwin'),patch.object(store.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','SYNTHETIC_SECRET')):
        with pytest.raises(SecretStoreError) as error:getattr(store.KeychainSecretStore('synthetic-profile'),operation)('fixture')
    assert 'SYNTHETIC_SECRET' not in str(error.value)

@pytest.mark.parametrize('args',[
    ['find-generic-password','-s','google-kit','-a','p:k','-w','-w'],
    ['delete-generic-password','-s','google-kit','-a','p:k','-w'],
    ['find-generic-password','-s','google-kit','-s','duplicate','-a','p:k'],
    ['find-generic-password','-s','google-kit','-a'],['dump-keychain'],
])
def test_unsupported_access_command_never_starts_child(args):
    with patch.object(store.subprocess,'run',side_effect=AssertionError('unexpected child')):
        with pytest.raises(SecretStoreError):store._run_security(args)

def test_read_exception_releases_item_and_keychain_without_deletion():
    api=API()
    with patch.object(api,'read',side_effect=RuntimeError('synthetic failure')):
        with pytest.raises(RuntimeError):access.apply(payload(),api)
    assert api.events[-2:]==[('release',202),('release',101)]
    assert not any(type(e) is tuple and e[0]=='delete' for e in api.events)

def test_main_invalid_input_refuses_before_native_loader_and_emits_nothing(capsys):
    class Input:buffer=io.BytesIO(b'{"operation":"get","operation":"delete"}')
    with patch.object(access.sys,'platform','darwin'),patch.object(access.sys,'argv',['helper']),patch.object(access.sys,'stdin',Input()),patch.object(access,'NativeAccessAPI',side_effect=AssertionError('native API')):
        assert access.main()==1
    output=capsys.readouterr();assert output.out==output.err==''

@pytest.mark.parametrize('value',VALUES)
def test_native_copy_content_buffer_is_read_exactly_and_freed(value):
    raw=value.encode();buffer=ctypes.create_string_buffer(raw);events=[]
    def copy(item,unused1,unused2,length,data):
        assert item==202
        ctypes.cast(length,ctypes.POINTER(ctypes.c_uint32))[0]=len(raw)
        ctypes.cast(data,ctypes.POINTER(ctypes.c_void_p))[0]=ctypes.addressof(buffer)
        return 0
    def free(attributes,data):events.append(('free',data.value));return 0
    api=object.__new__(access.NativeAccessAPI)
    api.security=SimpleNamespace(SecKeychainItemCopyContent=copy,SecKeychainItemFreeContent=free)
    assert api.read(202)==(0,raw)
    assert events==[('free',ctypes.addressof(buffer))]

@pytest.mark.parametrize('status,length',[(-1,0),(0,access.MAX_VALUE_BYTES+1)])
def test_native_error_and_oversize_free_buffer_without_dereferencing(status,length):
    buffer=ctypes.create_string_buffer(b'owned');events=[]
    def copy(item,a,b,out_length,data):
        ctypes.cast(out_length,ctypes.POINTER(ctypes.c_uint32))[0]=length
        ctypes.cast(data,ctypes.POINTER(ctypes.c_void_p))[0]=ctypes.addressof(buffer)
        return status
    api=object.__new__(access.NativeAccessAPI)
    api.security=SimpleNamespace(SecKeychainItemCopyContent=copy,SecKeychainItemFreeContent=lambda a,b:events.append('free') or 0)
    with patch.object(access.ctypes,'string_at',side_effect=AssertionError('unbounded read')):
        if status:assert api.read(202)==(status,None)
        else:
            with pytest.raises(ValueError):api.read(202)
    assert events==['free']
