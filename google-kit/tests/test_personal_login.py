"""Synthetic complete personal enrollment: no Keychain, browser or provider calls."""
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch
import ssl
import urllib.parse
import urllib.request

import pytest
from google_kit.core import personal_login as p
from google_kit.core.personal_preflight import inventory_digest
from google_kit.registry import all_specs
from google_kit.cli import main
from kp_mcp_bootstrap.secrets import KeychainSecretStore

PROFILE='personal-fixture';EMAIL='owner@example.net';SUBJECT='1234567890'
CLIENT='synthetic-client.apps.googleusercontent.com';PROJECT='fixture-project'
SECRET='SYNTHETIC_CLIENT_SECRET';ACCESS='SYNTHETIC_ACCESS_TOKEN';REFRESH='SYNTHETIC_REFRESH_TOKEN'
SCOPES=['email','openid']

def projection():return [{'name':s.name,'scopes':list(s.scopes),'posture':s.posture,'flag':s.flag} for s in all_specs()]

class Store:
    profile=PROFILE
    def __init__(self):self.data={};self.events=[];self.on_create=None;self.fail=None
    def has(self,key):self.events.append(('has',key));return key in self.data
    def get(self,key):self.events.append(('get',key));return self.data[key]
    def validate_create(self,key,value):
        self.events.append(('validate',key));KeychainSecretStore(PROFILE).validate_create(key,value)
    def create(self,key,value):
        self.events.append(('create',key))
        if key in self.data:raise RuntimeError('duplicate')
        self.data[key]=value
        if self.on_create:self.on_create(key)
        if key==self.fail:raise RuntimeError(SECRET)
    def set(self,*a):pytest.fail('update is forbidden')
    def delete(self,*a):pytest.fail('deletion is forbidden')

class Transport:
    def __init__(self):
        self.calls=[];self.on_info=None
        self.info={'aud':CLIENT,'azp':CLIENT,'sub':SUBJECT,'email':EMAIL,'email_verified':True,
                   'expires_in':'3500','scope':'email openid'}
    def token_info(self,token):
        assert token==ACCESS;self.calls.append('tokeninfo')
        if self.on_info:self.on_info()
        return self.info
    def drive_identity(self,token):pytest.fail('unnecessary Drive request')

class Flow:
    def __init__(self,stage):
        self.stage=stage;self.scopes=None;self.calls=[];self.callback=None
        self.tokens={'access_token':ACCESS,'refresh_token':REFRESH,'token_type':'Bearer','scope':'email openid'}
    def authorize(self,scopes):
        self.calls.append('authorize');self.scopes=scopes
        if self.callback:self.callback()
        return 'SYNTHETIC_CODE'
    def exchange(self,code):
        assert code=='SYNTHETIC_CODE';self.calls.append('exchange')
        for key in ('access_token','refresh_token'):
            if key in self.tokens:self.stage.set(key,self.tokens[key])
        return self.tokens

@pytest.fixture
def setup(tmp_path):
    config=tmp_path/'config';config.mkdir(mode=0o700)
    client=tmp_path/'client.json';client.write_text(json.dumps({'installed':{
        'client_id':CLIENT,'client_secret':SECRET,'project_id':PROJECT,
        'auth_uri':'https://accounts.google.com/o/oauth2/v2/auth',
        'token_uri':'https://oauth2.googleapis.com/token','redirect_uris':['http://localhost']}}));client.chmod(0o600)
    store=Store();transport=Transport();flows=[]
    def flow_factory(stage,client_id,**kw):
        assert client_id==CLIENT and kw['expected_email']==EMAIL and kw['transport'] is transport
        f=Flow(stage);flows.append(f);return f
    args=dict(profile=PROFILE,expected_email=EMAIL,expected_subject=SUBJECT,
        expected_client_id=CLIENT,expected_project_id=PROJECT,client_file=str(client),
        client_file_sha256=hashlib.sha256(client.read_bytes()).hexdigest(),config_dir=str(config),
        expected_inventory_digest=inventory_digest(projection()),operations=projection(),requested_scopes=SCOPES.copy(),
        store_factory=lambda profile:store,flow_factory=flow_factory,transport_factory=lambda:transport)
    return args,store,transport,flows,client,config

def result(setup):return p.login_personal(**setup[0])
def creations(store):return [key for op,key in store.events if op=='create']
def assert_no_secrets(report):
    raw=json.dumps(report)
    for secret in (SECRET,ACCESS,REFRESH,CLIENT):assert secret not in raw

def test_verified_identity_precedes_every_create_and_access_is_last(setup):
    args,store,transport,flows,client,config=setup
    transport.on_info=lambda:pytest.fail('premature persistence') if creations(store) else None
    before=client.read_bytes(),client.stat(),config.stat()
    r=result(setup)
    assert r['status']=='verified_credentials_created' and creations(store)==list(p.KEYS)
    assert store.data=={'client_id':CLIENT,'client_secret':SECRET,'refresh_token':REFRESH,'access_token':ACCESS}
    assert flows[0].calls==['authorize','exchange'] and flows[0].stage.values=={}
    assert r['account_verified_before_any_credential_persistence'] and not r['execution_authorized']
    assert r['operation_count']==106 and not r['operation_grants_changed']
    assert not r['native_registration_or_full_connection_accepted']
    assert (client.read_bytes(),client.stat(),config.stat())==before
    assert_no_secrets(r)

@pytest.mark.parametrize('field,value,reason',[
    ('sub','999','account_identity_mismatch'),('aud','foreign','client_identity_mismatch'),
    ('azp','foreign','client_identity_mismatch'),('email','other@example.net','account_identity_mismatch'),
    ('email_verified',False,'email_not_verified'),('expires_in','1','token_expired_or_near_expiry'),
    ('scope','email openid https://www.googleapis.com/auth/drive','scope_grant_mismatch'),
    ('scope','openid','scope_grant_mismatch')])
def test_identity_scope_or_expiry_refusal_never_persists(setup,field,value,reason):
    setup[2].info[field]=value;r=result(setup)
    assert r['status']=='held' and r['reason']==reason and not creations(setup[1])
    assert_no_secrets(r)

def test_initial_existing_profile_refuses_without_reading_a_credential_or_client_file(setup):
    setup[1].data['client_id']='FOREIGN'
    with patch.object(p,'read_client_file',side_effect=AssertionError('unexpected client read')):r=result(setup)
    assert r['reason']=='profile_not_empty' and setup[1].data=={'client_id':'FOREIGN'}
    assert not setup[3] and not any(op=='get' for op,key in setup[1].events)

@pytest.mark.parametrize('name,value',[
    ('profile',None),('profile','default'),('expected_client_id','bad'),
    ('expected_project_id',None),('expected_email','bad'),('expected_subject','bad'),
    ('requested_scopes',[]),('requested_scopes',['openid','openid']),
    ('requested_scopes',['openid,email'])])
def test_missing_explicit_review_bindings_refuse_before_store(setup,name,value):
    setup[0][name]=value;setup[0]['store_factory']=lambda _:pytest.fail('unexpected store')
    assert result(setup)['status']=='held' and not setup[3]

def test_inventory_drift_refuses_before_credential_or_flow_access(setup):
    setup[0]['expected_inventory_digest']='0'*64
    setup[0]['store_factory']=lambda _:pytest.fail('unexpected store')
    assert result(setup)['reason']=='inventory_changed'

def test_namespace_mismatch_refuses_without_key_presence_reads(setup):
    setup[1].profile='foreign';r=result(setup)
    assert r['reason']=='store_profile_mismatch' and setup[1].events==[]

def test_store_without_create_only_primitive_is_refused(setup):
    setup[1].create=None
    assert result(setup)['reason']=='create_only_store_required' and not setup[3]

@pytest.mark.parametrize('field,value',[
    ('client_id','foreign.apps.googleusercontent.com'),('project_id','foreign-project'),
    ('token_uri','https://example.net/token'),('auth_uri','https://example.net/auth'),
    ('redirect_uris',['https://example.net/callback'])])
def test_client_file_binding_mismatch_precedes_oauth(setup,field,value):
    data=json.loads(setup[4].read_text());data['installed'][field]=value;setup[4].write_text(json.dumps(data))
    setup[0]['client_file_sha256']=hashlib.sha256(setup[4].read_bytes()).hexdigest()
    r=result(setup);assert r['reason']=='client_binding_mismatch' and not setup[3] and not creations(setup[1])

@pytest.mark.parametrize('kind',['symlink','hardlink','fifo','permissions','oversized','duplicate'])
def test_unsafe_client_file_refuses_without_flow_or_keychain_write(setup,kind):
    file=setup[4]
    if kind=='symlink':
        foreign=file.with_suffix('.foreign');file.rename(foreign);file.symlink_to(foreign)
    elif kind=='hardlink':os.link(file,file.with_suffix('.peer'))
    elif kind=='fifo':file.unlink();os.mkfifo(file)
    elif kind=='permissions':file.chmod(0o644)
    elif kind=='oversized':file.write_bytes(b' ' * 65537)
    elif kind=='duplicate':
        raw=file.read_text().replace('"installed":','"installed":{},"installed":');file.write_text(raw)
        setup[0]['client_file_sha256']=hashlib.sha256(file.read_bytes()).hexdigest()
    r=result(setup);assert r['status']=='held' and not setup[3] and not creations(setup[1])
    assert_no_secrets(r)

def test_parse_time_client_change_refuses_before_oauth_and_preserves_edit(setup):
    original=p.json.loads;replacement='{"installed":{}}';done=False
    def race(raw,*args,**kwargs):
        nonlocal done
        answer=original(raw,*args,**kwargs)
        if not done and isinstance(raw,str) and '"installed"' in raw:
            setup[4].write_text(replacement);done=True
        return answer
    with patch.object(p.json,'loads',race):r=result(setup)
    assert r['reason']=='client_file_changed' and not setup[3] and not creations(setup[1])
    assert setup[4].read_text()==replacement

def test_replaced_client_body_is_not_read_during_postflight(setup):
    real=setup[0]['flow_factory'];foreign_inode=None;reads=[];original=os.read
    def factory(*a,**kw):
        f=real(*a,**kw)
        def replace():
            nonlocal foreign_inode
            new=setup[4].with_suffix('.new');new.write_text('{"FOREIGN":"DO_NOT_READ"}');new.chmod(0o600)
            foreign_inode=new.stat().st_ino;new.replace(setup[4])
        f.callback=replace;return f
    def track(fd,size):
        if foreign_inode is not None and os.fstat(fd).st_ino==foreign_inode:reads.append(fd)
        return original(fd,size)
    setup[0]['flow_factory']=factory
    with patch.object(os,'read',track):r=result(setup)
    assert r['reason']=='client_file_changed' and not reads and not creations(setup[1])
    assert 'FOREIGN' in setup[4].read_text()

def test_callback_cannot_replace_staged_credential_after_token_verification(setup):
    setup[2].on_info=lambda:setup[3][0].stage.values.update(refresh_token='FOREIGN')
    r=result(setup)
    assert r['reason']=='staged_credentials_changed' and not creations(setup[1])

def test_flow_scope_mutation_cannot_change_reviewed_scope_contract(setup):
    real=setup[0]['flow_factory']
    def factory(*a,**kw):
        f=real(*a,**kw)
        def mutate():
            f.scopes.append('https://www.googleapis.com/auth/drive')
            setup[2].info['scope']='email openid https://www.googleapis.com/auth/drive'
        f.callback=mutate;return f
    setup[0]['flow_factory']=factory;r=result(setup)
    assert r['reason']=='scope_grant_mismatch' and not creations(setup[1])

@pytest.mark.parametrize('key',['refresh_token','token_type','access_token'])
def test_malformed_or_incomplete_exchange_never_persists(setup,key):
    real=setup[0]['flow_factory']
    def factory(*a,**kw):
        f=real(*a,**kw);f.tokens.pop(key);return f
    setup[0]['flow_factory']=factory
    assert result(setup)['reason']=='token_exchange_invalid' and not creations(setup[1])

def test_long_refresh_is_preserved_without_process_argument_truncation(setup):
    real=setup[0]['flow_factory']
    def factory(*a,**kw):
        f=real(*a,**kw);f.tokens['refresh_token']='A'*5000;return f
    setup[0]['flow_factory']=factory;r=result(setup)
    assert r['status']=='verified_credentials_created' and setup[1].data['refresh_token']=='A'*5000
    assert 'A'*5000 not in json.dumps(r)

def test_foreign_item_appearing_during_commit_is_preserved(setup):
    def race(key):
        if key=='client_secret':setup[1].data['refresh_token']='FOREIGN'
    setup[1].on_create=race;r=result(setup)
    assert r['status']=='held' and r['partial_profile_requires_review']
    assert creations(setup[1])==['client_id','client_secret'] and setup[1].data['refresh_token']=='FOREIGN'
    assert 'access_token' not in setup[1].data and not r['automatic_retry_rollback_delete_or_overwrite_performed']

def test_foreign_edit_of_created_item_stops_commit_and_is_preserved(setup):
    setup[1].on_create=lambda key:setup[1].data.update(client_id='FOREIGN') if key=='client_id' else None
    r=result(setup)
    assert r['reason']=='credentials_changed' and creations(setup[1])==['client_id'] and setup[1].data['client_id']=='FOREIGN'

def test_storage_failure_reports_unknown_create_and_never_deletes_or_replays(setup):
    setup[1].fail='client_secret';r=result(setup)
    assert r['status']=='held' and r['created_keys']==['client_id'] and r['uncertain_create_key']=='client_secret'
    assert r['partial_profile_requires_review'] and not r['automatic_retry_rollback_delete_or_overwrite_performed']
    assert setup[1].data['client_secret']==SECRET and 'access_token' not in setup[1].data
    second=result(setup);assert second['reason']=='profile_not_empty' and len(setup[3])==1
    assert_no_secrets(r)

def test_final_authorization_change_is_held_after_create_without_deleting_foreign_data(setup):
    def race(key):
        if key=='access_token':
            folder=setup[5]/'authorizations';folder.mkdir(mode=0o700)
            (folder/(PROFILE+'.json')).write_text('{"schema":1,"tools":{"gmail.send":1}}')
    setup[1].on_create=race;r=result(setup)
    assert r['reason']=='authorization_changed' and r['partial_profile_requires_review'] and len(r['created_keys'])==4
    assert (setup[5]/'authorizations'/(PROFILE+'.json')).exists() and len(setup[1].data)==4

def test_provider_failure_is_closed_and_never_persists(setup):
    def fail():raise RuntimeError(ACCESS+SECRET)
    setup[2].on_info=fail;r=result(setup)
    assert r['reason']=='provider_unavailable' and not creations(setup[1]);assert_no_secrets(r)

def cli_args(setup):
    a=setup[0]
    return ['--profile',PROFILE,'auth','login','--personal','--expected-email',EMAIL,
        '--expected-subject',SUBJECT,'--expected-client-id',CLIENT,'--expected-project-id',PROJECT,
        '--client-secret-file',a['client_file'],'--client-file-sha256',a['client_file_sha256'],
        '--config-dir',a['config_dir'],'--inventory-sha256',a['expected_inventory_digest'],
        '--personal-scope','openid','--personal-scope','email']

def test_actual_cli_routes_explicit_personal_login_without_legacy_profile_or_seed(setup,capsys):
    a=setup[0]
    with patch('google_kit.cli.auth._resolve_profile',side_effect=AssertionError('ambient resolution')):
        with patch('google_kit.core.authz.seed_profile',side_effect=AssertionError('grant file write')):
            with pytest.raises(SystemExit) as e:
                main(cli_args(setup),_store_factory=a['store_factory'],_flow_factory=a['flow_factory'],_transport_factory=a['transport_factory'])
    assert e.value.code==0;r=json.loads(capsys.readouterr().out)
    assert r['status']=='verified_credentials_created' and r['requested_and_observed_scopes']==SCOPES
    assert_no_secrets(r)

@pytest.mark.parametrize('extra',[['--force'],['--scopes','https://www.googleapis.com/auth/drive']])
def test_personal_cli_rejects_legacy_force_or_extra_scope_union_before_store(setup,capsys,extra):
    with pytest.raises(SystemExit) as e:main(cli_args(setup)+extra,_store_factory=lambda _:pytest.fail('unexpected store'))
    assert e.value.code==1 and json.loads(capsys.readouterr().err)['status']=='held'

def test_personal_cli_refuses_ambient_extra_scopes_before_store(setup,capsys,monkeypatch):
    monkeypatch.setenv('GOOGLE_KIT_EXTRA_SCOPES','https://www.googleapis.com/auth/drive')
    with pytest.raises(SystemExit) as e:main(cli_args(setup),_store_factory=lambda _:pytest.fail('unexpected store'))
    assert e.value.code==1 and json.loads(capsys.readouterr().err)['reason']=='personal_scope_override_refused'

def test_personal_options_without_mode_do_not_fall_back_to_legacy_login(setup,capsys):
    args=cli_args(setup);args.remove('--personal')
    with pytest.raises(SystemExit) as e:main(args,_store_factory=lambda _:pytest.fail('unexpected store'))
    assert e.value.code==1 and json.loads(capsys.readouterr().err)['status']=='held'


class Response:
    def __init__(self,data,status=200,kind='application/json'):
        self.raw=json.dumps(data).encode();self.status=status;self.kind=kind;self.reads=[]
    def getheader(self,*a):return self.kind
    def read(self,size):self.reads.append(size);return self.raw[:size]

class Connection:
    def __init__(self,response):self.response=response;self.requests=[];self.closed=False;self.debug=None
    def set_debuglevel(self,n):self.debug=n
    def request(self,*a,**kw):self.requests.append((a,kw))
    def getresponse(self):return self.response
    def close(self):self.closed=True

def test_real_default_personal_flow_and_transport_integrate_through_actual_CLI(setup,capsys):
    responses=[Response({'access_token':ACCESS,'refresh_token':REFRESH,'token_type':'Bearer','scope':'email openid'}),Response(setup[2].info)]
    connections=[];hosts=[];auth_urls=[]
    def factory(host,**kw):
        assert host=='oauth2.googleapis.com' and isinstance(kw['context'],ssl.SSLContext)
        hosts.append(host);conn=Connection(responses[len(connections)]);connections.append(conn);return conn
    def open_browser(url):
        auth_urls.append(url);parsed=urllib.parse.urlparse(url);params=urllib.parse.parse_qs(parsed.query)
        assert parsed.scheme=='https' and parsed.netloc=='accounts.google.com' and parsed.path=='/o/oauth2/v2/auth'
        assert params['login_hint']==[EMAIL] and params['prompt']==['consent select_account']
        assert params['scope']==['email openid'] and params['include_granted_scopes']==['false']
        assert params['code_challenge_method']==['S256'] and params['client_id']==[CLIENT]
        redirect=params['redirect_uri'][0];assert urllib.parse.urlparse(redirect).hostname=='127.0.0.1'
        with urllib.request.urlopen(redirect+'/?'+urllib.parse.urlencode({'state':params['state'][0],'code':'SYNTHETIC_CODE'}),timeout=3) as reply:assert reply.status==200
        return True
    transport=p.PersonalGoogleTransport(_connection_factory=factory)
    with patch('kp_mcp_bootstrap.oauth.webbrowser.open',side_effect=open_browser):
        with pytest.raises(SystemExit) as e:main(cli_args(setup),_store_factory=setup[0]['store_factory'],_transport_factory=lambda:transport)
    assert e.value.code==0 and len(auth_urls)==1 and len(connections)==2
    request,kw=connections[0].requests[0];assert request==('POST','/token')
    body=urllib.parse.parse_qs(kw['body'].decode())
    assert body['client_id']==[CLIENT] and body['client_secret']==[SECRET] and body['code']==['SYNTHETIC_CODE']
    assert len(body['code_verifier'][0])>=43
    assert all(c.closed and c.debug==0 for c in connections)
    report=json.loads(capsys.readouterr().out);assert report['status']=='verified_credentials_created';assert_no_secrets(report)

@pytest.mark.parametrize('status,kind,raw',[
    (302,'application/json',b'{"error":"'+ACCESS.encode()+b'"}'),
    (401,'application/json',b'{"error":"'+ACCESS.encode()+b'"}'),
    (200,'text/plain',ACCESS.encode()),(200,'application/json',b' ' * 32769),
    (200,'application/json',b'{"access_token":"a","access_token":"b"}')])
def test_fixed_token_POST_refuses_redirect_errors_and_unbounded_or_malformed_bodies(status,kind,raw):
    response=Response({});response.status=status;response.kind=kind;response.raw=raw
    connection=Connection(response);calls=[]
    def factory(host,**kw):calls.append(host);return connection
    transport=p.PersonalGoogleTransport(_connection_factory=factory)
    with pytest.raises(p.Refused) as e:transport.exchange_token(b'synthetic-form')
    assert len(calls)==1 and connection.closed and ACCESS not in str(e.value)
    if status!=200 or kind!='application/json':assert response.reads==[]
    else:assert response.reads==[32769]

def test_fixed_token_POST_closes_on_exception_without_echoing_form_values():
    conn=Connection(Response({}))
    def fail(*a,**kw):raise OSError(SECRET)
    conn.request=fail
    with pytest.raises(p.Refused,match='^provider_unavailable$'):
        p.PersonalGoogleTransport(_connection_factory=lambda *a,**kw:conn).exchange_token(SECRET.encode())
    assert conn.closed
