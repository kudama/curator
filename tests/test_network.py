"""Synthetic private-network browser policy checks; no Plex or media operations."""
import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from curator import web


class ListenerPolicy(unittest.TestCase):
    def test_explicit_ipv4_and_bare_hostnames(self):
        self.assertEqual(web.listener_settings('10.0.0.106', ['Foundry', 'foundry.tfs.apt']),
                         ('10.0.0.106', ('foundry','foundry.tfs.apt')))
        for host in ('127.0.0.1','10.0.0.106','172.16.0.1','192.168.1.2'):
            self.assertEqual(web.listener_settings(host)[0], host)

    def test_refuses_unsafe_bind_and_hostname_inputs(self):
        for host in ('0.0.0.0','8.8.8.8','169.254.1.1','224.0.0.1','100.64.0.1',
                     'foundry','::','::1',' 127.0.0.1',None,True):
            with self.subTest(host=host), self.assertRaises(ValueError):web.listener_settings(host)
        for alias in ('*','foundry:8790','http://foundry','user@foundry','foundry/path',
                      'foundry.','-foundry','foundry\n','',None):
            with self.subTest(alias=alias), self.assertRaises(ValueError):
                web.listener_settings('10.0.0.106',[alias])

    def test_app_uses_actual_bound_port_and_only_configured_aliases(self):
        def bind(server, address, handler):
            server.server_port = 54321
            server.server_address = (address[0],54321)
        with patch.object(web.ThreadingHTTPServer,'__init__',bind):
            local = web.App(('127.0.0.1',0),Mock())
            lan = web.App(('10.0.0.106',0),Mock(),expected_hosts=['foundry'])
        self.assertEqual(local.allowed_authorities,{'localhost:54321','127.0.0.1:54321'})
        self.assertEqual(lan.allowed_authorities,{'10.0.0.106:54321','foundry:54321'})

    def test_real_loopback_listener_uses_assigned_port(self):
        with web.App(('127.0.0.1',0),Mock()) as server:
            self.assertGreater(server.server_port,0)
            self.assertEqual(server.socket.getsockname(),server.server_address)
            self.assertEqual(server.allowed_authorities,
                {'127.0.0.1:'+str(server.server_port),'localhost:'+str(server.server_port)})

    def test_invalid_cli_fails_before_opening_state(self):
        with patch('sys.argv',['curator','--host','0.0.0.0']), patch.object(web,'Store') as store, \
             patch('sys.stderr',new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as error:web.main()
        self.assertEqual(error.exception.code,2);store.assert_not_called()

    def test_cli_passes_explicit_bind_and_aliases_to_server(self):
        state = Mock();server = Mock(server_port=8790)
        server.serve_forever.side_effect = KeyboardInterrupt
        with patch('sys.argv',['curator','--host','10.0.0.106','--expected-host','foundry']), \
             patch.object(web,'Store',return_value=state), patch.object(web,'Service') as service, \
             patch.object(web,'App',return_value=server) as app, patch('sys.stdout',new_callable=io.StringIO):
            web.main()
        app.assert_called_once_with(('10.0.0.106',8790),service.return_value,expected_hosts=('foundry',),managed_service=False)
        server.server_close.assert_called_once();state.close.assert_called_once()


class BrowserPolicy(unittest.TestCase):
    def request(self, host='foundry:8790', path='/api/state', method='GET', origin=None,
                cookie=True, mutation_header=True, extra_headers=()):
        headers = [('Host',host)] if host is not None else []
        if cookie:headers.append(('Cookie','curator_session=test-session'))
        if origin is not None:headers.append(('Origin',origin))
        if mutation_header:headers.append(('X-Curator-Request','1'))
        headers.extend(extra_headers)
        payload = b'{}' if method == 'POST' else b''
        request = (f'{method} {path} HTTP/1.1\r\n'+''.join(k+': '+v+'\r\n' for k,v in headers)
                   +f'Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n').encode()+payload
        class Connection:
            def __init__(self):self.output=bytearray()
            def makefile(self,*args):return io.BytesIO(request)
            def sendall(self,data):self.output.extend(data)
        connection=Connection()
        service=Mock();service.state.return_value={'ok':True};service.save_config.return_value={'ok':True}
        server=SimpleNamespace(server_port=8790,session='test-session',service=service,
            allowed_authorities={'foundry:8790','10.0.0.106:8790'})
        web.Handler(connection,('10.0.0.50',1),server)
        return bytes(connection.output),service

    def test_lan_page_cookie_and_authenticated_session_read(self):
        page,_=self.request(path='/',cookie=False)
        self.assertIn(b'200 OK',page);self.assertIn(b'HttpOnly; SameSite=Strict',page)
        for host in ('foundry:8790','10.0.0.106:8790'):
            with self.subTest(host=host):self.assertIn(b'200 OK',self.request(host=host)[0])
        self.assertIn(b'403 Forbidden',self.request(cookie=False)[0])

    def test_unconfigured_missing_duplicate_or_wrong_port_host_is_rejected(self):
        for host in ('evil.example:8790','foundry:8791','localhost:8790',None,'foundry:8790, evil.example'):
            with self.subTest(host=host):self.assertIn(b'403 Forbidden',self.request(host=host,path='/')[0])
        self.assertIn(b'403 Forbidden',self.request(extra_headers=[('Host','foundry:8790')])[0])

    def test_same_origin_mutation_succeeds(self):
        output,service=self.request(path='/api/config',method='POST',origin='http://foundry:8790')
        self.assertIn(b'200 OK',output);service.save_config.assert_called_once_with({})

    def test_cross_origin_missing_headers_and_duplicate_origin_block_mutation(self):
        for origin in (None,'null','https://foundry:8790','http://foundry:8791',
                       'http://10.0.0.106:8790','http://evil.example:8790'):
            with self.subTest(origin=origin):
                output,service=self.request(path='/api/config',method='POST',origin=origin)
                self.assertIn(b'403 Forbidden',output);service.save_config.assert_not_called()
        for options in ({'cookie':False},{'mutation_header':False},
                        {'extra_headers':[('Origin','http://foundry:8790')]}):
            output,service=self.request(path='/api/config',method='POST',origin='http://foundry:8790',**options)
            self.assertIn(b'403 Forbidden',output);service.save_config.assert_not_called()


if __name__ == '__main__':
    unittest.main()
