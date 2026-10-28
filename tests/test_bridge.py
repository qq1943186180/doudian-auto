import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from doudian_auto.bridge import Bridge
from doudian_auto.errors import DoudianError, WaitingHuman


@pytest.fixture
def server():
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"running":true,"extension_connected":false,"secret":"never-export"}')
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(body)
            action = body['action']
            if action == 'evaluate':
                data = {'ok':True,'data':{'type':'string','value':json.dumps({'title':'中文'})}}
            elif action == 'list_tabs':
                data = {'ok':True,'data':{'tabs':[{'tabId':9,'url':'https://fxg.jinritemai.com/ffa/g/create?product_id=3790019980637110699&tracking=1'}]}}
            elif action == 'fail':
                data = {'ok':False,'error':{'code':'not_connected','message':'secret'}}
            else:
                data = {'ok':True,'data':{'success':True}}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
    httpd = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = Thread(target=httpd.serve_forever,daemon=True)
    thread.start()
    yield Bridge('http://127.0.0.1:'+str(httpd.server_port)),calls
    httpd.shutdown()
    httpd.server_close()


def test_status_disconnected_actionable_no_secret(server):
    bridge,calls = server
    assert 'secret' not in bridge.status()
    with pytest.raises(WaitingHuman):
        bridge.require_ready()
    assert calls == []


def test_envelope_unicode_session_and_errors(server):
    bridge,calls = server
    assert bridge.evaluate('中文') == {'title':'中文'}
    assert calls[0]['session'] == 'doudian-auto'
    assert calls[0]['args']['code'] == '中文'
    with pytest.raises(WaitingHuman) as exc:
        bridge.command('fail')
    assert 'secret' not in str(exc.value)


def test_reuse_session_editor_after_tracking_redirect_by_exact_tab_id(server,monkeypatch):
    bridge,calls = server
    monkeypatch.setattr(bridge,'require_ready',lambda:None)
    bridge.open('https://fxg.jinritemai.com/ffa/g/create?product_id=3790019980637110699')
    assert [c['action'] for c in calls] == ['list_tabs','attach_tab']
    assert calls[-1]['args']['tabId'] == 9


def test_external_endpoint_rejected():
    with pytest.raises(DoudianError):
        Bridge('http://example.com:10086')
