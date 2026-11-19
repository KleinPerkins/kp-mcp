"""Explicit, non-mutating diagnostic snapshots of one authorization file.

There is no default config path, environment resolver, repair or grant path.
Snapshots are observations; they never authorize an operation or evaluate env
overrides. Directory/FD checks bound cooperative owner changes, not hostile
filesystem or platform-wide access-control qualification.
"""
from __future__ import annotations
import errno
import hashlib
import json
import os
from pathlib import Path
import stat

from .personal_preflight import PROFILE, Refused, _refuse, _unique_object, inventory_digest

MAX_AUTHZ_BYTES=65536

def _identity(s, *, content=True):
    fields=(s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_nlink,getattr(s,'st_flags',0))
    return fields+(s.st_size,s.st_mtime_ns,s.st_ctime_ns) if content else fields

def _owned(s):
    return s.st_uid==os.getuid() and not (s.st_mode & 0o022)

def read_authorizations(*,config_dir,profile,operations,expected_inventory_digest):
    """Observe valid/absent state; corrupt/unsafe/changed state is refused."""
    if not isinstance(profile,str) or not PROFILE.fullmatch(profile):_refuse('explicit_profile_required')
    if not isinstance(config_dir,(str,Path)):_refuse('explicit_config_dir_required')
    config_dir=Path(config_dir)
    if not config_dir.is_absolute() or config_dir==Path('/') or '..' in config_dir.parts:_refuse('explicit_config_dir_required')
    if inventory_digest(operations)!=expected_inventory_digest:_refuse('inventory_changed')
    gated=sorted(op['name'] for op in operations if op['flag'])
    descriptors=[];chain=[]
    def remember(fd,path,content=False):
        descriptors.append(fd);s=os.fstat(fd);chain.append((fd,path,s,content));return s
    def check_chain():
        for fd,path,before,content in chain:
            if _identity(before,content=content)!=_identity(os.fstat(fd),content=content) or _identity(before,content=content)!=_identity(path.lstat(),content=content):
                _refuse('authorization_changed')
    def result(state,tools=None,raw=None,file_identity=None):
        check_chain()
        tools=tools or {}
        return {'schema':'google-kit/personal-authz-snapshot/v1','profile':profile,
            'config_dir':str(config_dir),'inventory_sha256':expected_inventory_digest,
            'state':state,'profile_grants_observed':state=='valid',
            'file_sha256':hashlib.sha256(raw).hexdigest() if raw is not None else None,
            'file_identity':list(file_identity) if file_identity is not None else None,
            'directory_identities':[{'path':str(path),'identity':list(_identity(s,content=content))} for _,path,s,content in chain],
            'operations':[{'name':name,'persisted':name in tools,'profile_grant':tools.get(name,0),
                'default_deny_if_unrecorded':name not in tools,'execution_authorized':False} for name in gated],
            'environment_overrides_evaluated':False,'execution_authorized':False,
            'actual_native_source_or_destination_acceptance_proven':False}
    try:
        current=Path('/');fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        remember(fd,current)
        for part in config_dir.parts[1:]:
            current=current/part
            try:child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            except FileNotFoundError:return result('absent_config_dir')
            fd=child;s=remember(fd,current,current==config_dir)
        if not _owned(s):_refuse('authorization_path_unsafe')
        try:child=os.open('authorizations',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
        except FileNotFoundError:return result('absent_authorizations_dir')
        fd=child;s=remember(fd,config_dir/'authorizations',True)
        if not _owned(s):_refuse('authorization_path_unsafe')
        name=profile+'.json';path=config_dir/'authorizations'/name
        try:leaf=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        except FileNotFoundError:return result('absent_profile')
        try:
            before=os.fstat(leaf)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or not _owned(before) or before.st_size>MAX_AUTHZ_BYTES:
                _refuse('authorization_path_unsafe')
            raw=b''
            while True:
                part=os.read(leaf,min(8192,MAX_AUTHZ_BYTES+1-len(raw)))
                if not part:break
                raw+=part
                if len(raw)>MAX_AUTHZ_BYTES:_refuse('authorization_path_unsafe')
            if _identity(before)!=_identity(os.fstat(leaf)) or _identity(before)!=_identity(path.lstat()):_refuse('authorization_changed')
            try:
                data=json.loads(raw.decode('utf-8'),object_pairs_hook=_unique_object,
                    parse_constant=lambda _: _refuse('authorization_corrupt'))
            except (ValueError,UnicodeError,RecursionError):_refuse('authorization_corrupt')
            except Refused:_refuse('authorization_corrupt')
            if type(data) is not dict or set(data)!={'schema','tools'} or type(data['schema']) is not int or data['schema']!=1 or type(data['tools']) is not dict:
                _refuse('authorization_corrupt')
            tools=data['tools']
            if set(tools)-set(gated):_refuse('authorization_inventory_mismatch')
            if any(type(value) is not int or value not in (0,1) for value in tools.values()):_refuse('authorization_corrupt')
            if _identity(before)!=_identity(os.fstat(leaf)) or _identity(before)!=_identity(path.lstat()):_refuse('authorization_changed')
            return result('valid',tools,raw,_identity(before))
        finally:os.close(leaf)
    except Refused:raise
    except OSError as exc:
        _refuse('authorization_path_unsafe' if exc.errno in (errno.ELOOP,errno.ENOTDIR) else 'authorization_unavailable')
    finally:
        for fd in reversed(descriptors):os.close(fd)
