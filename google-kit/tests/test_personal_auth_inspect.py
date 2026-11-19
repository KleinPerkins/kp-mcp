"""Offline synthetic checks; never use a real Keychain store or network."""
import copy
import json
import os
from pathlib import Path
import ssl
import unittest

from google_kit.core import personal_preflight as p

CLIENT='synthetic-client.apps.googleusercontent.com'
TOKEN='SYNTHETIC_ACCESS_TOKEN_NEVER_A_REAL_CREDENTIAL'
EMAIL='owner@example.net'; SUBJECT='1234567890'; PROFILE='personal-fixture'
DRIVE='https://www.googleapis.com/auth/drive.readonly'

class Store:
    profile=PROFILE
    def __init__(self): self.reads=[]
    def get(self,key):
        self.reads.append(key)
        return {'client_id':CLIENT,'access_token':TOKEN}[key]
    def set(self,*args): raise AssertionError('credential write')
    def delete(self,*args): raise AssertionError('credential delete')

class Provider:
    def __init__(self):
        self.info={'aud':CLIENT,'azp':CLIENT,'sub':SUBJECT,'expires_in':'3500','scope':DRIVE}
        self.user={'user':{'kind':'drive#user','me':True,'emailAddress':EMAIL}}
        self.calls=[];self.on_info=None
    def token_info(self,token):
        assert token==TOKEN;self.calls.append('tokeninfo')
        if self.on_info:self.on_info()
        return copy.deepcopy(self.info)
    def drive_identity(self,token):
        assert token==TOKEN;self.calls.append('drive.about')
        return copy.deepcopy(self.user)

class Preflight(unittest.TestCase):
    def setUp(self):
        self.store=Store();self.provider=Provider()
        self.ops=json.loads((Path(__file__).parent/'canonical-inventory.json').read_text())
        self.digest=p.inventory_digest(self.ops)
    def run_inspect(self,**kwargs):
        args=dict(profile=PROFILE,expected_email=EMAIL,expected_subject=SUBJECT,
                  expected_client_id=CLIENT,store=self.store,transport=self.provider,operations=self.ops,expected_inventory_digest=self.digest)
        args.update(kwargs);return p.inspect_profile(**args)
    def refused(self,reason,**kwargs):
        with self.assertRaises(p.Refused) as c:self.run_inspect(**kwargs)
        self.assertEqual(str(c.exception),reason)
        self.assertNotIn(TOKEN,str(c.exception))

    def test_complete_canonical_inventory_identity_and_no_authority(self):
        env=dict(os.environ);r=self.run_inspect()
        self.assertEqual(r['operation_count'],106)
        self.assertEqual(self.store.reads,['client_id','access_token'])
        self.assertEqual(self.provider.calls,['tokeninfo','drive.about'])
        self.assertFalse(r['credential_refresh_or_write'])
        self.assertFalse(r['functional_API_eligibility_or_complete_connection_proven'])
        self.assertFalse(r['source_runtime_transport_approval_and_destination_acceptance_proven'])
        self.assertTrue(all(not x['execution_authorized'] and not x['operation_authorization_observed'] for x in r['operations']))
        self.assertEqual(dict(os.environ),env)

    def test_verified_token_email_needs_only_one_request(self):
        self.provider.info.update(email=EMAIL,email_verified='true')
        self.assertEqual(self.run_inspect()['identity_resource'],'tokeninfo')
        self.assertEqual(self.provider.calls,['tokeninfo'])

    def test_numeric_email_verification_is_not_a_boolean(self):
        self.provider.info.update(email=EMAIL,email_verified=1)
        self.refused('email_not_verified')

    def test_unverified_email_does_not_fall_back(self):
        self.provider.info.update(email=EMAIL,email_verified=False)
        self.refused('email_not_verified');self.assertEqual(self.provider.calls,['tokeninfo'])

    def test_wrong_subject_refused_before_any_Drive_request(self):
        self.provider.info['sub']='99999';self.refused('account_identity_mismatch')
        self.assertEqual(self.provider.calls,['tokeninfo'])

    def test_wrong_token_email_never_overridden_by_Drive(self):
        self.provider.info.update(email='wrong@example.invalid',email_verified=True)
        self.refused('account_identity_mismatch');self.assertEqual(self.provider.calls,['tokeninfo'])

    def test_wrong_Drive_email_refused(self):
        self.provider.user['user']['emailAddress']='wrong@example.invalid';self.refused('account_identity_mismatch')

    def test_missing_Drive_email_unknown_identity(self):
        del self.provider.user['user']['emailAddress'];self.refused('account_identity_mismatch')

    def test_Drive_me_must_be_actual_true(self):
        self.provider.user['user']['me']='true';self.refused('invalid_identity_response')

    def test_Drive_kind_required(self):
        del self.provider.user['user']['kind'];self.refused('invalid_identity_response')

    def test_wrong_client_audience_refused(self):
        self.provider.info['aud']='other.apps.googleusercontent.com';self.refused('client_identity_mismatch')

    def test_unreviewed_client_refused_before_access_token_read(self):
        original=self.store.get
        def wrong_client(key):
            value=original(key)
            return 'other-client.apps.googleusercontent.com' if key=='client_id' else value
        self.store.get=wrong_client
        self.refused('selected_client_identity_mismatch')
        self.assertEqual(self.store.reads,['client_id'])
        self.assertEqual(self.provider.calls,[])

    def test_expected_client_required_before_any_credential_read(self):
        self.refused('expected_client_identity_required',expected_client_id=None)
        self.assertEqual(self.store.reads,[])
        self.assertEqual(self.provider.calls,[])

    def test_unreviewed_client_never_reads_token_even_if_later_refused(self):
        original=self.store.get
        def wrong_client(key):
            value=original(key)
            return 'other-client.apps.googleusercontent.com' if key=='client_id' else value
        self.store.get=wrong_client
        with self.assertRaises(p.Refused):self.run_inspect()
        self.assertEqual(self.store.reads,['client_id'])
        self.assertEqual(self.provider.calls,[])

    def test_authorized_presenter_required(self):
        del self.provider.info['azp'];self.refused('client_identity_mismatch')

    def test_no_ambient_profile_fallback(self):
        for value in [None,'','../default','bad:profile','with space']:
            with self.subTest(value=value):self.refused('explicit_profile_required',profile=value)
        self.assertEqual(self.store.reads,[]);self.assertEqual(self.provider.calls,[])

    def test_expected_email_required_before_credentials(self):
        self.refused('expected_identity_required',expected_email='')
        self.assertEqual(self.store.reads,[])

    def test_expected_subject_required_before_credentials(self):
        self.refused('expected_identity_required',expected_subject='unknown')
        self.assertEqual(self.store.reads,[])

    def test_selected_store_namespace_must_match(self):
        self.store.profile='default';self.refused('store_profile_mismatch')
        self.assertEqual(self.store.reads,[])

    def test_changed_inventory_refused_before_credentials(self):
        self.ops.pop();self.refused('inventory_changed')
        self.assertEqual(self.store.reads,[])

    def test_inventory_duplicate_refused(self):
        self.ops.append(copy.deepcopy(self.ops[0]));self.refused('invalid_inventory')

    def test_inventory_ungated_write_refused(self):
        op=next(r for r in self.ops if r['posture']=='write');op['flag']=None
        self.refused('invalid_inventory')

    def test_inventory_freezes_before_provider_callback(self):
        self.provider.on_info=lambda:self.ops.clear()
        self.assertEqual(self.run_inspect()['operation_count'],106)

    def test_rw_scope_does_not_silently_prove_readonly_scope(self):
        self.provider.info.update(scope='https://www.googleapis.com/auth/spreadsheets',email=EMAIL,email_verified=True)
        r=self.run_inspect();op=next(x for x in r['operations'] if x['name']=='sheets.read')
        self.assertFalse(op['exact_declared_scopes_observed'])
        self.assertTrue(op['scope_implication_or_additional_grant_review_needed'])
        self.assertFalse(op['execution_authorized'])

    def test_missing_identity_scope_refused_without_extra_API(self):
        self.provider.info['scope']='https://www.googleapis.com/auth/gmail.readonly'
        self.refused('identity_scope_unavailable');self.assertEqual(self.provider.calls,['tokeninfo'])

    def test_near_expiry_never_refreshes(self):
        self.provider.info['expires_in']='30';self.refused('token_expired_or_near_expiry')
        self.assertEqual(self.store.reads,['client_id','access_token'])
        self.assertEqual(self.provider.calls,['tokeninfo'])

    def test_malformed_lifetimes_refused(self):
        for value in [True,None,'NaN','-1',1.1]:
            with self.subTest(value=value):
                self.provider.info['expires_in']=value;self.refused('invalid_token_metadata')

    def test_scope_values_not_guessed_or_echoed_on_failure(self):
        self.provider.info['scope']=TOKEN;self.refused('invalid_token_metadata')

    def test_store_error_sanitized_without_refresh(self):
        def fail(key):raise RuntimeError(TOKEN)
        self.store.get=fail;self.refused('credential_unavailable')
        self.assertEqual(self.provider.calls,[])

    def test_provider_error_sanitized(self):
        def fail(token):raise RuntimeError(TOKEN)
        self.provider.token_info=fail;self.refused('provider_unavailable')

    def test_success_output_has_no_credentials_or_unrecognized_payload(self):
        self.provider.info.update(refresh_token=TOKEN,client_secret=TOKEN,extra=TOKEN)
        result=json.dumps(self.run_inspect())
        self.assertNotIn(TOKEN,result);self.assertNotIn(CLIENT,result)

    def test_invalid_access_token_refused_before_network(self):
        self.store.get=lambda key:CLIENT if key=='client_id' else TOKEN+'\n'
        self.refused('invalid_access_token');self.assertEqual(self.provider.calls,[])


class Response:
    status=200
    def __init__(self,raw):self.raw=raw;self.reads=[];self.content_type='application/json; charset=utf-8'
    def getheader(self,*args):return self.content_type
    def read(self,size):self.reads.append(size);return self.raw[:size]

class Connection:
    def __init__(self,response):self.response=response;self.requests=[];self.closed=False;self.debug=None
    def set_debuglevel(self,n):self.debug=n
    def request(self,*args,**kwargs):self.requests.append((args,kwargs))
    def getresponse(self):return self.response
    def close(self):self.closed=True

class Transport(unittest.TestCase):
    def setUp(self):
        self.response=Response(b'{"scope":"openid"}');self.conn=Connection(self.response);self.factories=[]
        def factory(host,**kwargs):self.factories.append((host,kwargs));return self.conn
        self.transport=p.GoogleReadTransport(_connection_factory=factory)
    def test_fixed_tokeninfo_TLS_GET_no_redirect_proxy_or_log(self):
        self.transport.token_info(TOKEN)
        host,kwargs=self.factories[0];args,kw=self.conn.requests[0]
        self.assertEqual(host,'oauth2.googleapis.com');self.assertIsInstance(kwargs['context'],ssl.SSLContext)
        self.assertEqual(args,('GET','/tokeninfo?access_token='+TOKEN));self.assertEqual(self.conn.debug,0)
        self.assertNotIn('Authorization',kw['headers']);self.assertTrue(self.conn.closed)

    def test_fixed_Drive_identity_minimal_fields_and_bearer(self):
        self.transport.drive_identity(TOKEN);args,kw=self.conn.requests[0]
        self.assertEqual(self.factories[0][0],'www.googleapis.com')
        self.assertEqual(args[0],'GET');self.assertIn('user%28kind%2Cme%2CemailAddress%29',args[1])
        self.assertNotIn(TOKEN,args[1]);self.assertEqual(kw['headers']['Authorization'],'Bearer '+TOKEN)

    def test_redirect_not_followed_or_body_read(self):
        self.response.status=302
        with self.assertRaisesRegex(p.Refused,'^provider_refused$'):self.transport.token_info(TOKEN)
        self.assertEqual(self.response.reads,[]);self.assertEqual(len(self.factories),1);self.assertTrue(self.conn.closed)

    def test_HTTP_refusal_body_not_echoed_or_read(self):
        self.response.status=401;self.response.raw=TOKEN.encode()
        with self.assertRaisesRegex(p.Refused,'^provider_refused$'):self.transport.token_info(TOKEN)
        self.assertEqual(self.response.reads,[])

    def test_bound_response_refused(self):
        self.response.raw=b' '*(p.MAX_RESPONSE+1)
        with self.assertRaisesRegex(p.Refused,'^invalid_provider_response$'):self.transport.token_info(TOKEN)
        self.assertEqual(self.response.reads,[p.MAX_RESPONSE+1]);self.assertTrue(self.conn.closed)

    def test_content_type_required_before_body(self):
        self.response.content_type='text/html'
        with self.assertRaisesRegex(p.Refused,'^invalid_provider_response$'):self.transport.token_info(TOKEN)
        self.assertEqual(self.response.reads,[])

    def test_duplicate_JSON_keys_refused(self):
        self.response.raw=b'{"scope":"a","scope":"b"}'
        with self.assertRaisesRegex(p.Refused,'^invalid_provider_response$'):self.transport.token_info(TOKEN)

    def test_nonobject_nonfinite_and_invalid_JSON_refused(self):
        for raw in [b'[]',b'NaN',b'{"value":Infinity}',b'\xff',b'{']:
            with self.subTest(raw=raw):
                self.response.raw=raw
                with self.assertRaisesRegex(p.Refused,'^invalid_provider_response$'):self.transport.token_info(TOKEN)

    def test_connection_error_does_not_echo_token_URL(self):
        def fail(*args,**kwargs):raise OSError('/tokeninfo?access_token='+TOKEN)
        self.conn.request=fail
        with self.assertRaisesRegex(p.Refused,'^provider_unavailable$'):self.transport.token_info(TOKEN)
        self.assertTrue(self.conn.closed)

if __name__=='__main__':unittest.main()
