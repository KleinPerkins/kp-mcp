"""Bounded native default-Keychain access under the writer's Python identity.

This private stdin helper neither grants trust nor changes ACLs, search lists,
defaults or interaction preferences. Only get emits a bounded JSON value, on
its captured stdout. Presence never requests password data; deletion addresses
only the item reference returned for the exact service/account/default keychain.
Source tests do not qualify native Keychain behavior or installation.
"""
from __future__ import annotations

import ctypes
import importlib.util
import json
from pathlib import Path
import sys

MAX_VALUE_BYTES=1024*1024
MAX_INPUT_BYTES=64*1024
MAX_OUTPUT_BYTES=6*MAX_VALUE_BYTES+64
NOT_FOUND=-25300
NOT_FOUND_EXIT=44

def validate_payload(payload):
    if type(payload) is not dict or set(payload)!={'operation','service','account'}:raise ValueError('Invalid native access fields.')
    if payload['operation'] not in ('get','has','delete'):raise ValueError('Invalid native access operation.')
    if any(type(payload[k]) is not str for k in ('operation','service','account')):raise ValueError('Invalid native access field types.')
    try:fields=tuple(payload[k].encode('utf-8') for k in ('service','account'))
    except UnicodeError:raise ValueError('Invalid native access encoding.') from None
    if any(not b or b'\0' in b or len(b)>4096 for b in fields):raise ValueError('Invalid native access identity.')
    return fields

def decode_value(raw):
    if type(raw) is not bytes or len(raw)>MAX_VALUE_BYTES:raise ValueError('Invalid native value.')
    value=raw.decode('utf-8','strict')
    if '\0' in value:raise ValueError('Invalid native value.')
    return value

class NativeAccessAPI:
    def __init__(self):
        # Isolated Python (-I -S -B) loads only the adjacent owner helper, never
        # a caller-controlled package search path or site initialization.
        spec=importlib.util.spec_from_file_location('_kp_mcp_keychain_writer',Path(__file__).with_name('_keychain_write.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.writer=module.NativeAPI();self.security=self.writer.security
        ptr=ctypes.c_void_p;size=ctypes.c_uint32
        for name,args in (
            ('SecKeychainItemCopyContent',[ptr,ptr,ptr,ctypes.POINTER(size),ctypes.POINTER(ptr)]),
            ('SecKeychainItemFreeContent',[ptr,ptr]),('SecKeychainItemDelete',[ptr]),
        ):
            fn=getattr(self.security,name);fn.argtypes=args;fn.restype=ctypes.c_int32

    def copy_default(self):return self.writer.copy_default()
    def find(self,*args):return self.writer.find(*args)
    def release(self,ref):self.writer.release(ref)
    def delete(self,item):return self.security.SecKeychainItemDelete(item)

    def read(self,item):
        length=ctypes.c_uint32();data=ctypes.c_void_p()
        status=self.security.SecKeychainItemCopyContent(item,None,None,ctypes.byref(length),ctypes.byref(data))
        try:
            if status:return status,None
            if length.value>MAX_VALUE_BYTES or length.value and not data:raise ValueError('Invalid native value.')
            return 0,ctypes.string_at(data,length.value) if length.value else b''
        finally:
            if data and self.security.SecKeychainItemFreeContent(None,data):raise RuntimeError('Native data release failed.')

def apply(payload,api):
    service,account=validate_payload(payload)
    keychain=item=None
    try:
        status,keychain=api.copy_default()
        if status or not keychain:return 1,None
        status,item=api.find(keychain,service,account)
        if status==NOT_FOUND:return NOT_FOUND_EXIT,None
        if status or not item:return 1,None
        if payload['operation']=='has':return 0,None
        if payload['operation']=='delete':return (0 if api.delete(item)==0 else 1),None
        status,raw=api.read(item)
        if status:return 1,None
        return 0,decode_value(raw)
    finally:
        if item:api.release(item)
        if keychain:api.release(keychain)

def unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate native access field.')
        result[key]=value
    return result

def parse_result(raw):
    # JSON escaping preserves CR/LF and trailing newlines across text-mode
    # subprocess pipes. No CLI formatter whitespace is stripped from the value.
    if type(raw) is not str or len(raw.encode('utf-8'))>MAX_OUTPUT_BYTES:raise ValueError('Invalid native response.')
    result=json.loads(raw,object_pairs_hook=unique)
    if type(result) is not dict or set(result)!={'value'} or type(result['value']) is not str:raise ValueError('Invalid native response.')
    value=result['value'];decode_value(value.encode('utf-8','strict'))
    return value

def main():
    try:
        if sys.platform!='darwin' or len(sys.argv)!=1:return 1
        import resource
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        raw=sys.stdin.buffer.read(MAX_INPUT_BYTES+1)
        if len(raw)>MAX_INPUT_BYTES:return 1
        payload=json.loads(raw.decode('utf-8','strict'),object_pairs_hook=unique)
        validate_payload(payload)
        status,value=apply(payload,NativeAccessAPI())
        if status==0 and payload['operation']=='get':
            output=json.dumps({'value':value},ensure_ascii=True,separators=(',',':'))+'\n'
            if len(output.encode('ascii'))>MAX_OUTPUT_BYTES:return 1
            sys.stdout.write(output)
        return status
    except BaseException:return 1

if __name__=='__main__':raise SystemExit(main())
