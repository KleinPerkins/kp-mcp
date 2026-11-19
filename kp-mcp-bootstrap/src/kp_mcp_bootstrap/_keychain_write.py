"""Private bounded stdin helper for default-Keychain generic-password writes.

Only this process loads the native Security APIs. It emits no data or native
diagnostics, takes no arguments, changes no search list/default and never reads
password data. The legacy API matches this store's existing default-Keychain
contract; native build/ACL/Keychain behavior requires separate qualification.
"""
from __future__ import annotations
import ctypes
import json
import sys

MAX_VALUE_BYTES = 1024 * 1024
MAX_INPUT_BYTES = 4 * 1024 * 1024
DUPLICATE_ITEM = -25299


def encode_payload(payload):
    if type(payload) is not dict or set(payload) != {'service','account','value','update'}:
        raise ValueError('Invalid Keychain write fields.')
    if type(payload['update']) is not bool or any(type(payload[k]) is not str for k in ('service','account','value')):
        raise ValueError('Invalid Keychain write field types.')
    try:
        fields = tuple(payload[k].encode('utf-8') for k in ('service','account','value'))
    except UnicodeError:
        raise ValueError('Invalid Keychain write encoding.') from None
    if any(b'\0' in v for v in fields) or not fields[0] or not fields[1]:
        raise ValueError('Invalid Keychain write field encoding.')
    if len(fields[0]) > 4096 or len(fields[1]) > 4096 or len(fields[2]) > MAX_VALUE_BYTES:
        raise ValueError('Keychain write exceeds the transport limit.')
    text = json.dumps(payload, ensure_ascii=True, separators=(',',':'))
    if len(text.encode('ascii')) > MAX_INPUT_BYTES:
        raise ValueError('Keychain write exceeds the transport limit.')
    return text, fields


class NativeAPI:
    def __init__(self):
        self.security = ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
        self.cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        ptr=ctypes.c_void_p;out=ctypes.POINTER(ptr);size=ctypes.c_uint32;status=ctypes.c_int32
        for name,args in (
            ('SecKeychainCopyDefault',[out]),
            ('SecKeychainAddGenericPassword',[ptr,size,ctypes.c_char_p,size,ctypes.c_char_p,size,ptr,out]),
            ('SecKeychainFindGenericPassword',[ptr,size,ctypes.c_char_p,size,ctypes.c_char_p,ctypes.POINTER(size),out,out]),
            ('SecKeychainItemModifyAttributesAndData',[ptr,ptr,size,ptr]),
        ):
            function=getattr(self.security,name);function.argtypes=args;function.restype=status
        self.cf.CFRelease.argtypes=[ptr];self.cf.CFRelease.restype=None

    def copy_default(self):
        ref=ctypes.c_void_p();status=self.security.SecKeychainCopyDefault(ctypes.byref(ref))
        return status,ref.value

    def add(self,keychain,service,account,value):
        data=ctypes.create_string_buffer(value)
        return self.security.SecKeychainAddGenericPassword(keychain,len(service),service,
            len(account),account,len(value),data,None)

    def find(self,keychain,service,account):
        ref=ctypes.c_void_p()
        status=self.security.SecKeychainFindGenericPassword(keychain,len(service),service,
            len(account),account,None,None,ctypes.byref(ref))
        return status,ref.value

    def modify(self,item,value):
        data=ctypes.create_string_buffer(value)
        return self.security.SecKeychainItemModifyAttributesAndData(item,None,len(value),data)

    def release(self,ref):
        self.cf.CFRelease(ref)


def apply(payload,api):
    _,(service,account,value)=encode_payload(payload)
    keychain=None;item=None
    try:
        status,keychain=api.copy_default()
        if status != 0 or not keychain:return False
        status=api.add(keychain,service,account,value)
        if status==DUPLICATE_ITEM and payload['update']:
            status,item=api.find(keychain,service,account)
            if status != 0 or not item:return False
            status=api.modify(item,value)
        return status==0
    finally:
        if item:api.release(item)
        if keychain:api.release(keychain)


def main():
    try:
        if sys.platform!='darwin' or len(sys.argv)!=1:return 1
        import resource
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        raw=sys.stdin.buffer.read(MAX_INPUT_BYTES+1)
        if len(raw)>MAX_INPUT_BYTES:return 1
        def unique(pairs):
            result={}
            for k,v in pairs:
                if k in result:raise ValueError('duplicate')
                result[k]=v
            return result
        payload=json.loads(raw.decode('utf-8'),object_pairs_hook=unique)
        encode_payload(payload)
        return 0 if apply(payload,NativeAPI()) else 1
    except BaseException:
        return 1


if __name__=='__main__':
    raise SystemExit(main())
