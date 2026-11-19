"""Synthetic filesystem and actual CLI wiring; no real credentials or network."""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from google_kit.core import personal_authz as a
from google_kit.core.personal_preflight import Refused,inventory_digest
from google_kit.registry import all_specs
from google_kit.cli import main
from google_kit.cli.auth import cmd_inspect

PROFILE='personal-fixture';EMAIL='owner@example.net';SUBJECT='1234567890'
CLIENT='synthetic-client.apps.googleusercontent.com';TOKEN='SYNTHETIC_TOKEN_NOT_REAL'
def operations():return [{'name':s.name,'scopes':list(s.scopes),'posture':s.posture,'flag':s.flag} for s in all_specs()]

@pytest.fixture
def setup(tmp_path):
    root=tmp_path/'config';root.mkdir(mode=0o700)
    folder=root/'authorizations';folder.mkdir(mode=0o700)
    path=folder/(PROFILE+'.json');path.write_text(json.dumps({'schema':1,'tools':{'gmail.send':1}}))
    return root,path,operations()

def read(setup):
    root,path,ops=setup
    return a.read_authorizations(config_dir=root,profile=PROFILE,operations=ops,expected_inventory_digest=inventory_digest(ops))

def refused(setup,reason):
    with pytest.raises(Refused,match='^'+reason+'$'):read(setup)

def test_valid_snapshot_reports_59_profile_gates_without_execution(setup):
    r=read(setup);assert r['state']=='valid' and r['profile_grants_observed']
    assert len(r['operations'])==59 and all(not x['execution_authorized'] for x in r['operations'])
    send=next(x for x in r['operations'] if x['name']=='gmail.send')
    assert send['profile_grant']==1 and send['persisted']
    other=next(x for x in r['operations'] if x['name']=='calendar.create')
    assert other['profile_grant']==0 and other['default_deny_if_unrecorded']
    assert not r['environment_overrides_evaluated'] and not r['execution_authorized']

def test_valid_snapshot_preserves_bytes_inode_and_directories(setup):
    root,path,_=setup;before=(path.read_bytes(),path.stat(),root.stat(),path.parent.stat())
    read(setup)
    after=(path.read_bytes(),path.stat(),root.stat(),path.parent.stat())
    assert before==after

def test_absent_file_distinct_no_creation(setup):
    _,path,_=setup;path.unlink();r=read(setup)
    assert r['state']=='absent_profile' and not r['profile_grants_observed'] and not path.exists()
    assert all(x['default_deny_if_unrecorded'] for x in r['operations'])

def test_absent_authz_directory_distinct_no_creation(setup):
    _,path,_=setup;path.unlink();path.parent.rmdir()
    assert read(setup)['state']=='absent_authorizations_dir' and not path.parent.exists()

def test_absent_config_distinct_no_creation(setup):
    root,path,_=setup;path.unlink();path.parent.rmdir();root.rmdir()
    assert read(setup)['state']=='absent_config_dir' and not root.exists()

@pytest.mark.parametrize('raw',['{bad','[]','{"schema":true,"tools":{}}','{"schema":2,"tools":{}}','{"schema":1,"tools":{},"unknown":"SECRET"}','{"schema":1,"tools":{},"tools":{}}','{"schema":1,"tools":{"gmail.send":true}}','{"schema":1,"tools":{"gmail.send":"1"}}'])
def test_corrupt_data_is_never_absence_or_grant(setup,raw):
    _,path,_=setup;path.write_text(raw);refused(setup,'authorization_corrupt');assert path.read_text()==raw

def test_unknown_operation_is_inventory_drift(setup):
    _,path,_=setup;path.write_text('{"schema":1,"tools":{"unknown.op":1}}')
    refused(setup,'authorization_inventory_mismatch')

def test_symlink_leaf_refused_before_foreign_body_read(setup):
    root,path,_=setup;foreign=root/'foreign';path.rename(foreign);path.symlink_to(foreign)
    original=os.read;foreign_ino=foreign.stat().st_ino;reads=[]
    def track(fd,size):
        if os.fstat(fd).st_ino==foreign_ino:reads.append(fd)
        return original(fd,size)
    with patch.object(os,'read',track):refused(setup,'authorization_path_unsafe')
    assert not reads and path.is_symlink()

def test_symlink_directory_refused(setup):
    root,path,ops=setup;folder=path.parent;other=root/'other';folder.rename(other);folder.symlink_to(other,target_is_directory=True)
    refused(setup,'authorization_path_unsafe')

def test_alias_body_never_read_even_when_identity_check_later_refuses(setup):
    root,path,_=setup;foreign=root/'foreign';path.rename(foreign);path.symlink_to(foreign)
    original=os.read;inode=foreign.stat().st_ino;reads=[]
    def track(fd,size):
        if os.fstat(fd).st_ino==inode:reads.append(fd)
        return original(fd,size)
    with patch.object(os,'read',track):
        with pytest.raises(Refused):read(setup)
    assert reads==[]

def test_shared_file_refused(setup):
    root,path,_=setup;os.link(path,root/'peer');refused(setup,'authorization_path_unsafe')

def test_fifo_refused_without_reader_wait(setup):
    _,path,_=setup;path.unlink();os.mkfifo(path);refused(setup,'authorization_path_unsafe')

def test_mutable_by_other_accounts_refused(setup):
    _,path,_=setup;path.chmod(0o666);refused(setup,'authorization_path_unsafe')

def test_oversized_file_refused(setup):
    _,path,_=setup;path.write_bytes(b' '*(a.MAX_AUTHZ_BYTES+1));refused(setup,'authorization_path_unsafe')

def test_parse_time_in_place_foreign_edit_is_detected_and_preserved(setup):
    _,path,_=setup;original=json.loads;replacement='{"schema":1,"tools":{"gmail.send":0}}';done=False
    def race(*args,**kwargs):
        nonlocal done
        result=original(*args,**kwargs)
        if not done:path.write_text(replacement);done=True
        return result
    with patch.object(a.json,'loads',race):refused(setup,'authorization_changed')
    assert path.read_text()==replacement

def test_read_time_replacement_is_detected_and_preserved(setup):
    _,path,_=setup;original=os.read;done=False;replacement=b'{"schema":1,"tools":{}}'
    def race(fd,size):
        nonlocal done
        raw=original(fd,size)
        if raw and not done:
            other=path.with_suffix('.new');other.write_bytes(replacement);other.replace(path);done=True
        return raw
    with patch.object(os,'read',race):refused(setup,'authorization_changed')
    assert path.read_bytes()==replacement

def test_repeated_reads_release_all_descriptors(setup):
    before=len(os.listdir('/dev/fd'))
    for _ in range(20):read(setup)
    assert len(os.listdir('/dev/fd'))==before

@pytest.mark.parametrize('value',['relative','/','/tmp/../elsewhere'])
def test_config_path_requires_explicit_absolute_nonroot_without_traversal(setup,value):
    root,path,ops=setup
    with patch.object(os,'open',side_effect=AssertionError('unexpected filesystem access')):
        with pytest.raises(Refused,match='explicit_config_dir_required'):
            a.read_authorizations(config_dir=value,profile=PROFILE,operations=ops,expected_inventory_digest=inventory_digest(ops))

class Store:
    profile=PROFILE
    def __init__(self):self.reads=[]
    def get(self,key):self.reads.append(key);return {'client_id':CLIENT,'access_token':TOKEN}[key]
    def set(self,*args):raise AssertionError('credential write')
    def delete(self,*args):raise AssertionError('credential delete')

class Transport:
    def __init__(self,callback=None):self.callback=callback;self.calls=0
    def token_info(self,token):
        assert token==TOKEN;self.calls+=1
        if self.callback:self.callback()
        return {'aud':CLIENT,'azp':CLIENT,'sub':SUBJECT,'expires_in':'3500','scope':'https://www.googleapis.com/auth/drive.readonly','email':EMAIL,'email_verified':True}
    def drive_identity(self,token):raise AssertionError('unnecessary identity API')

def arguments(setup):
    root,path,ops=setup
    return ['--profile',PROFILE,'auth','inspect','--expected-email',EMAIL,'--expected-subject',SUBJECT,'--expected-client-id',CLIENT,'--config-dir',str(root),'--inventory-sha256',inventory_digest(ops)]

def test_actual_cli_uses_complete_registry_and_explicit_read_only_bindings(setup,capsys):
    store=Store();transport=Transport()
    with pytest.raises(SystemExit) as exc:
        main(arguments(setup),_store_factory=lambda profile:store,_transport_factory=lambda:transport)
    assert exc.value.code==0
    r=json.loads(capsys.readouterr().out)
    assert r['operation_count']==106 and r['authorization_snapshot']['state']=='valid'
    assert r['operation_grants_observed'] and not r['operation_grants_changed']
    assert not r['source_runtime_transport_approval_and_destination_acceptance_proven']
    assert store.reads==['client_id','access_token'] and transport.calls==1
    assert TOKEN not in json.dumps(r) and CLIENT not in json.dumps(r)

def test_cli_accepts_profile_after_subcommand_without_fallback(setup,capsys):
    args=arguments(setup);args=args[2:]+args[:2]
    with pytest.raises(SystemExit) as exc:main(args,_store_factory=lambda _:Store(),_transport_factory=Transport)
    assert exc.value.code==0 and json.loads(capsys.readouterr().out)['profile']==PROFILE

def test_cli_missing_profile_refuses_before_store_or_provider(setup,capsys):
    args=arguments(setup)[2:]
    with pytest.raises(SystemExit) as exc:
        main(args,_store_factory=lambda _:pytest.fail('unexpected store'),_transport_factory=lambda:pytest.fail('unexpected provider'))
    assert exc.value.code==1 and json.loads(capsys.readouterr().err)['reason']=='explicit_profile_required'

def test_cli_requires_independently_reviewed_client_id(setup,capsys):
    args=arguments(setup);at=args.index('--expected-client-id');del args[at:at+2]
    with pytest.raises(SystemExit) as exc:main(args,_store_factory=lambda _:pytest.fail('unexpected store'))
    assert exc.value.code==2 and '--expected-client-id' in capsys.readouterr().err

def test_cli_corrupt_snapshot_refuses_before_credential_access(setup,capsys):
    _,path,_=setup;path.write_text('SECRET NOT JSON')
    with pytest.raises(SystemExit) as exc:main(arguments(setup),_store_factory=lambda _:pytest.fail('unexpected store'))
    assert exc.value.code==1 and 'SECRET' not in capsys.readouterr().err

def test_cli_changed_snapshot_during_provider_call_refuses_and_preserves_foreign_edit(setup,capsys):
    _,path,_=setup;replacement='{"schema":1,"tools":{"gmail.send":0}}'
    transport=Transport(lambda:path.write_text(replacement))
    with pytest.raises(SystemExit) as exc:main(arguments(setup),_store_factory=lambda _:Store(),_transport_factory=lambda:transport)
    assert exc.value.code==1 and json.loads(capsys.readouterr().err)['reason']=='authorization_changed'
    assert path.read_text()==replacement

def test_cli_reports_absent_default_deny_without_creating_authz_data(setup,capsys):
    _,path,_=setup;path.unlink()
    with pytest.raises(SystemExit) as exc:main(arguments(setup),_store_factory=lambda _:Store(),_transport_factory=Transport)
    assert exc.value.code==0 and json.loads(capsys.readouterr().out)['authorization_snapshot']['state']=='absent_profile' and not path.exists()

def test_cli_inventory_drift_refuses_before_store(setup,capsys):
    args=arguments(setup);args[-1]='0'*64
    with pytest.raises(SystemExit) as exc:main(args,_store_factory=lambda _:pytest.fail('unexpected store'))
    assert exc.value.code==1 and json.loads(capsys.readouterr().err)['reason']=='inventory_changed'

def test_direct_inspect_exception_is_sanitized(setup,capsys):
    root,path,ops=setup
    def fail(_):raise RuntimeError(TOKEN)
    rc=cmd_inspect(PROFILE,expected_email=EMAIL,expected_subject=SUBJECT,expected_client_id=CLIENT,config_dir=str(root),expected_inventory_digest=inventory_digest(ops),_store_factory=fail)
    assert rc==1 and TOKEN not in capsys.readouterr().err

def test_refusal_reason_is_closed_and_cannot_contain_a_token():
    assert str(Refused(TOKEN))=='inspection_unavailable'

def test_typed_store_failure_cannot_inject_a_raw_refusal_reason(setup,capsys):
    root,path,ops=setup
    def fail(_):raise Refused(TOKEN)
    rc=cmd_inspect(PROFILE,expected_email=EMAIL,expected_subject=SUBJECT,expected_client_id=CLIENT,config_dir=str(root),expected_inventory_digest=inventory_digest(ops),_store_factory=fail)
    error=capsys.readouterr().err
    assert rc==1 and TOKEN not in error and json.loads(error)['reason']=='inspection_unavailable'
