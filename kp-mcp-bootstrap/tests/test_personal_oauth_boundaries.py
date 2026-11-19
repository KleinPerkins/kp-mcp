"""Provider hints cannot replace core PKCE fields; listener ownership is bounded."""
import threading
import urllib.parse
from unittest.mock import patch
import pytest
from kp_mcp_bootstrap.oauth import LoopbackPKCEFlow
from kp_mcp_bootstrap.errors import OAuthError

class Store:
    def get(self,key):raise AssertionError('credential read before exchange')
    def set(self,*a):raise AssertionError('persistence')

def flow(**kw):return LoopbackPKCEFlow(Store(),'https://example.net/auth','https://example.net/token','synthetic-client',timeout=0.05,**kw)

@pytest.mark.parametrize('key',['scope','state','client_id','redirect_uri','code_challenge','code_challenge_method','response_type','access_type','request_uri','unknown'])
def test_provider_hint_cannot_override_security_fields_or_add_unknown_parameters(key):
    with pytest.raises(OAuthError,match='Invalid provider authorization parameters'):
        flow(authorization_params={key:'injected'})

def test_browser_handoff_exception_closes_listener_and_joins_own_thread():
    import kp_mcp_bootstrap.oauth as o
    before=set(threading.enumerate());servers=[];original=o.HTTPServer
    def server(*a,**kw):
        v=original(*a,**kw);servers.append(v);return v
    with patch.object(o,'HTTPServer',side_effect=server),patch.object(o.webbrowser,'open',side_effect=RuntimeError('handoff failed')):
        with pytest.raises(RuntimeError,match='handoff failed'):flow().authorize(['openid'])
    assert len(servers)==1 and servers[0].socket.fileno()==-1 and set(threading.enumerate())==before

def test_timeout_closes_listener_and_joins_own_thread():
    import kp_mcp_bootstrap.oauth as o
    before=set(threading.enumerate());servers=[];original=o.HTTPServer
    def server(*a,**kw):v=original(*a,**kw);servers.append(v);return v
    with patch.object(o,'HTTPServer',side_effect=server),patch.object(o.webbrowser,'open',return_value=True):
        with pytest.raises(OAuthError,match='timed out'):flow().authorize(['openid'])
    assert servers[0].socket.fileno()==-1 and set(threading.enumerate())==before

def test_one_second_accepted_socket_timeout_is_set_before_handling():
    import kp_mcp_bootstrap.oauth as o
    import socket
    accepted=[];clients=[];servers=[];original=o.HTTPServer;before=set(threading.enumerate())
    def server(*a,**kw):
        v=original(*a,**kw);servers.append(v);get=v.get_request
        def capture():
            c,address=get();accepted.append(c);return c,address
        v.get_request=capture;return v
    def slow_browser(url):
        query=urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        endpoint=urllib.parse.urlparse(query['redirect_uri'][0])
        client=socket.socket();clients.append(client);client.settimeout(1)
        client.connect((endpoint.hostname,endpoint.port));client.sendall(b'GET /')
        return True
    try:
        with patch.object(o,'HTTPServer',side_effect=server),patch.object(o.webbrowser,'open',side_effect=slow_browser):
            with pytest.raises(OAuthError,match='timed out'):flow().authorize(['openid'])
        assert len(accepted)==1 and accepted[0].gettimeout()==1 and accepted[0].fileno()==-1
        assert servers[0].socket.fileno()==-1 and set(threading.enumerate())==before
    finally:
        for client in clients:client.close()
