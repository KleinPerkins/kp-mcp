"""Proposed personal-profile identity/scope inspection; no credential writes.

This component has no CLI, default profile, credential discovery or refresh path.
The owner must supply an explicitly selected store and a reviewed inventory.
Source/fixture results do not establish a destination observation or authority.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import re
import ssl
from urllib.parse import urlencode

MAX_RESPONSE = 32768
PROFILE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z')
EMAIL = re.compile(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}\Z')
SUBJECT = re.compile(r'[0-9]{1,128}\Z')
CLIENT = re.compile(r'[A-Za-z0-9._-]{1,240}\.apps\.googleusercontent\.com\Z')
SCOPE = re.compile(r'https://www\.googleapis\.com/auth/[A-Za-z0-9_./-]{1,200}\Z')
DRIVE_IDENTITY_SCOPES = frozenset('https://www.googleapis.com/auth/'+s for s in (
    'drive','drive.appdata','drive.file','drive.metadata','drive.metadata.readonly','drive.photos.readonly','drive.readonly'))


class Refused(Exception):
    """Fixed machine-readable reason only; never include provider/store values."""
    REASONS=frozenset(('invalid_provider_response','provider_refused','provider_unavailable',
        'invalid_inventory','invalid_token_metadata','token_expired_or_near_expiry',
        'explicit_profile_required','expected_identity_required','inventory_changed',
        'store_profile_mismatch','credential_unavailable','invalid_client_identity',
        'invalid_access_token','client_identity_mismatch','account_identity_mismatch',
        'email_not_verified','identity_scope_unavailable','invalid_identity_response',
        'explicit_config_dir_required','authorization_changed','authorization_path_unsafe',
        'authorization_corrupt','authorization_inventory_mismatch','authorization_unavailable',
        'inspection_unavailable','expected_client_identity_required','selected_client_identity_mismatch'))
    def __init__(self,reason):
        self.reason=reason if type(reason) is str and reason in self.REASONS else 'inspection_unavailable'
        super().__init__(self.reason)


def _refuse(reason):
    raise Refused(reason) from None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: _refuse('invalid_provider_response')
        result[key] = value
    return result


def _json_body(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE:
        _refuse('invalid_provider_response')
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object,
                          parse_constant=lambda _: _refuse('invalid_provider_response'))
    except (UnicodeError, ValueError, RecursionError):
        _refuse('invalid_provider_response')
    if type(data) is not dict: _refuse('invalid_provider_response')
    return data


class GoogleReadTransport:
    """Two fixed HTTPS diagnostic resources; no redirects, proxy or retry.

    Tokeninfo's access_token query is kept in memory. Never log a request URL,
    response body, connection exception or token. Google documents this resource
    for diagnostic introspection; it is not used as an application auth gateway.
    """
    def __init__(self, *, _connection_factory=None):
        self._connection_factory = _connection_factory

    def _get(self, host, path, headers):
        connection = None
        try:
            factory = self._connection_factory or http.client.HTTPSConnection
            connection = factory(host, timeout=10, context=ssl.create_default_context())
            connection.set_debuglevel(0)
            connection.request('GET', path, headers=headers)
            response = connection.getresponse()
            if response.status != 200: _refuse('provider_refused')
            kind = response.getheader('Content-Type', '').split(';', 1)[0].strip().lower()
            if kind != 'application/json': _refuse('invalid_provider_response')
            return _json_body(response.read(MAX_RESPONSE + 1))
        except Refused:
            raise
        except Exception:
            _refuse('provider_unavailable')
        finally:
            if connection is not None:
                try: connection.close()
                except Exception: pass

    def token_info(self, access_token):
        return self._get('oauth2.googleapis.com', '/tokeninfo?'+urlencode({'access_token':access_token}),
                         {'Accept':'application/json','Cache-Control':'no-store'})

    def drive_identity(self, access_token):
        return self._get('www.googleapis.com', '/drive/v3/about?'+urlencode({'fields':'user(kind,me,emailAddress)'}),
                         {'Accept':'application/json','Cache-Control':'no-store','Authorization':'Bearer '+access_token})


def inventory_digest(operations):
    """Digest the complete diagnostic projection; it does not grant authority."""
    try:
        if not isinstance(operations, list) or not operations: _refuse('invalid_inventory')
        seen = set(); rows = []
        for op in operations:
            if type(op) is not dict or set(op) != {'name','scopes','posture','flag'}: _refuse('invalid_inventory')
            name = op['name']; scopes = op['scopes']; posture = op['posture']; flag = op['flag']
            if not isinstance(name,str) or not re.fullmatch(r'[a-z_]+\.[a-z_]+',name) or name in seen: _refuse('invalid_inventory')
            if not isinstance(scopes,list) or not scopes or any(not isinstance(s,str) or not SCOPE.fullmatch(s) for s in scopes): _refuse('invalid_inventory')
            if len(scopes)!=len(set(scopes)) or posture not in ('read','write','admin','destructive'): _refuse('invalid_inventory')
            if flag is not None and (not isinstance(flag,str) or not re.fullmatch(r'GOOGLE_KIT_ENABLE_[A-Z_]+',flag)): _refuse('invalid_inventory')
            if posture in ('write','destructive') and flag is None: _refuse('invalid_inventory')
            seen.add(name); rows.append(dict(op,scopes=sorted(scopes)))
        raw=json.dumps(sorted(rows,key=lambda r:r['name']),sort_keys=True,separators=(',',':')).encode()
        return hashlib.sha256(raw).hexdigest()
    except Refused:
        raise
    except Exception:
        _refuse('invalid_inventory')


def _scopes(raw):
    if not isinstance(raw,str) or len(raw)>16384: _refuse('invalid_token_metadata')
    values=raw.split()
    if not values or len(values)>128 or len(values)!=len(set(values)):
        _refuse('invalid_token_metadata')
    if any(s not in ('openid','email','profile') and not SCOPE.fullmatch(s) for s in values):
        _refuse('invalid_token_metadata')
    return frozenset(values)


def _positive_lifetime(raw):
    if isinstance(raw,bool) or not isinstance(raw,(str,int)):
        _refuse('invalid_token_metadata')
    if isinstance(raw,str) and not re.fullmatch(r'[0-9]{1,10}',raw):
        _refuse('invalid_token_metadata')
    if int(raw)<=30: _refuse('token_expired_or_near_expiry')
    return int(raw)


def inspect_profile(*, profile, expected_email, expected_subject, expected_client_id, store, transport,
                    operations, expected_inventory_digest):
    """Read only client_id/access_token, introspect and verify a selected identity.

    No refresh token, client secret, filesystem profile data, write authorization
    config or ambient environment is read. A missing/expired token stays held.
    Returned scope matches are exact syntactic matches, not API eligibility or
    grants to execute. A reviewed broader-scope implication is deliberately not
    guessed by removing '.readonly'. Caller-selected/fake inputs remain claims
    until the actual owner transport, source/runtime and operation are verified.
    """
    if not isinstance(profile,str) or not PROFILE.fullmatch(profile): _refuse('explicit_profile_required')
    if not isinstance(expected_email,str) or not EMAIL.fullmatch(expected_email): _refuse('expected_identity_required')
    if not isinstance(expected_subject,str) or not SUBJECT.fullmatch(expected_subject): _refuse('expected_identity_required')
    if not isinstance(expected_client_id,str) or not CLIENT.fullmatch(expected_client_id): _refuse('expected_client_identity_required')
    try:
        raw_inventory=json.dumps(operations,allow_nan=False)
        if len(raw_inventory)>524288: _refuse('invalid_inventory')
        operations=json.loads(raw_inventory)
    except Refused:
        raise
    except Exception:
        _refuse('invalid_inventory')
    digest=inventory_digest(operations)
    if not isinstance(expected_inventory_digest,str) or digest!=expected_inventory_digest: _refuse('inventory_changed')
    try:
        if store.profile!=profile: _refuse('store_profile_mismatch')
        client_id=store.get('client_id')
        if client_id!=expected_client_id: _refuse('selected_client_identity_mismatch')
        access_token=store.get('access_token')
    except Refused:
        raise
    except Exception:
        _refuse('credential_unavailable')
    if not isinstance(client_id,str) or not CLIENT.fullmatch(client_id): _refuse('invalid_client_identity')
    if not isinstance(access_token,str) or not (1<=len(access_token)<=16384) or any(ord(c)<33 or ord(c)>126 for c in access_token):
        _refuse('invalid_access_token')
    try:
        info=transport.token_info(access_token)
    except Refused:
        raise
    except Exception:
        _refuse('provider_unavailable')
    if type(info) is not dict: _refuse('invalid_token_metadata')
    if info.get('aud')!=client_id or info.get('azp')!=client_id: _refuse('client_identity_mismatch')
    if info.get('sub')!=expected_subject: _refuse('account_identity_mismatch')
    remaining=_positive_lifetime(info.get('expires_in'))
    scopes=_scopes(info.get('scope'))
    # A mismatching declared token email is never overridden by a second API.
    if 'email' in info:
        if not isinstance(info['email'],str) or info['email'].casefold()!=expected_email.casefold(): _refuse('account_identity_mismatch')
        verified=info.get('email_verified')
        if verified is not True and verified!='true': _refuse('email_not_verified')
        identity_resource='tokeninfo'
    else:
        if not scopes & DRIVE_IDENTITY_SCOPES: _refuse('identity_scope_unavailable')
        try:
            data=transport.drive_identity(access_token)
        except Refused:
            raise
        except Exception:
            _refuse('provider_unavailable')
        if type(data) is not dict or type(data.get('user')) is not dict: _refuse('invalid_identity_response')
        user=data['user']
        if user.get('kind')!='drive#user' or user.get('me') is not True: _refuse('invalid_identity_response')
        if not isinstance(user.get('emailAddress'),str) or user['emailAddress'].casefold()!=expected_email.casefold(): _refuse('account_identity_mismatch')
        identity_resource='drive.about'
    observations=[]
    for op in sorted(operations,key=lambda r:r['name']):
        missing=sorted(set(op['scopes'])-scopes)
        observations.append({'name':op['name'],'declared_scopes':sorted(op['scopes']),
            'exact_declared_scopes_observed':not missing,'declared_scopes_not_exactly_observed':missing,
            'scope_implication_or_additional_grant_review_needed':bool(missing),
            'operation_authorization_observed':False,'execution_authorized':False})
    return {'schema':'google-kit/personal-profile-preflight/v1','profile':profile,
        'expected_email':expected_email,'expected_subject':expected_subject,
        'expected_client_id_sha256':hashlib.sha256(expected_client_id.encode()).hexdigest(),
        'identity_resource':identity_resource,'selected_token_identity_matches':True,
        'token_expires_in_at_observation':remaining,'observed_token_scopes':sorted(scopes),
        'inventory_sha256':digest,'operation_count':len(observations),'operations':observations,
        'provider_requests_completed':1+(identity_resource=='drive.about'),
        'credential_refresh_or_write':False,'operation_grants_read_or_changed':False,
        'functional_API_eligibility_or_complete_connection_proven':False,
        'source_runtime_transport_approval_and_destination_acceptance_proven':False}
