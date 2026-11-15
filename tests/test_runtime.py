"""Restart coordination refuses active work and drains accepted requests."""
import io
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from curator.runtime import ServiceRuntime, RestartBlocked, Restarting, RESTART_EXIT_CODE
from curator import web


def service(tasks=None):
    return SimpleNamespace(active=set(),scan_status={},presence_status={},
                           store=SimpleNamespace(all=lambda table:tasks or []))


class RestartCoordination(unittest.TestCase):
    def test_manual_server_refuses_restart(self):
        runtime=ServiceRuntime(service())
        self.assertFalse(runtime.status()['restart_available'])
        with self.assertRaises(RestartBlocked):runtime.request_restart()
        self.assertFalse(runtime.restart_requested)

    def test_active_work_is_preserved_and_restart_refused(self):
        for category in ('queue','scan','presence','processing','publishing'):
            with self.subTest(category=category):
                source=service([{'status':'running' if category=='processing' else 'publishing'}]
                               if category in {'processing','publishing'} else [])
                if category=='queue':source.active.add('library')
                if category=='scan':source.scan_status['library']={'running':True}
                if category=='presence':source.presence_status['library']={'running':True}
                runtime=ServiceRuntime(source,managed=True)
                with self.assertRaises(RestartBlocked):runtime.request_restart()
                self.assertFalse(runtime.restart_requested)

    def test_other_mutation_blocks_restart_and_gate_closes_before_new_work(self):
        runtime=ServiceRuntime(service(),managed=True)
        entered=threading.Event();release=threading.Event()
        def mutation():
            with runtime.request(True):entered.set();release.wait(2)
        worker=threading.Thread(target=mutation);worker.start();self.assertTrue(entered.wait(1))
        try:
            with runtime.request(True):
                with self.assertRaises(RestartBlocked):runtime.request_restart()
        finally:release.set();worker.join(2)
        with runtime.request(True):
            self.assertTrue(runtime.request_restart()['accepted'])
            with self.assertRaises(Restarting):
                with runtime.request(True):self.fail('New mutation entered during restart')
            self.assertFalse(runtime.wait_for_idle(0))
        self.assertTrue(runtime.wait_for_idle(0))

    def test_existing_read_drains_and_queued_records_are_unchanged(self):
        tasks=[{'status':'queued','version':3}];runtime=ServiceRuntime(service(tasks),managed=True)
        with runtime.request():
            with runtime.request(True):runtime.request_restart()
            self.assertFalse(runtime.wait_for_idle(0))
        self.assertTrue(runtime.wait_for_idle(0));self.assertEqual(tasks,[{'status':'queued','version':3}])
        runtime.cancel_restart()
        with runtime.request():pass
        self.assertFalse(runtime.restart_requested);self.assertIsNotNone(runtime.status()['restart_error'])

    def test_failed_request_releases_counters(self):
        runtime=ServiceRuntime(service(),managed=True)
        with self.assertRaises(ValueError):
            with runtime.request(True):raise ValueError('request failed')
        self.assertEqual((runtime.requests,runtime.mutations),(0,0))
        self.assertTrue(runtime.request_restart()['accepted'])


class RestartHTTP(unittest.TestCase):
    def request(self,method='POST',path='/api/service/restart',headers=None,body=None,managed=True,busy=False):
        source=service();source.active={'library'} if busy else set()
        runtime=ServiceRuntime(source,managed)
        server=SimpleNamespace(service=source,runtime=runtime,session='session',
                               allowed_authorities={'localhost:8790'},shutdown=Mock())
        headers=headers if headers is not None else [('Host','localhost:8790'),
            ('Cookie','curator_session=session'),('Origin','http://localhost:8790'),('X-Curator-Request','1')]
        raw=json.dumps(body or {}).encode()
        request=(f'{method} {path} HTTP/1.1\r\n'+''.join(k+': '+v+'\r\n' for k,v in headers)
                 +f'Content-Length: {len(raw)}\r\nConnection: close\r\n\r\n').encode()+raw
        class Connection:
            def __init__(self):self.output=bytearray()
            def makefile(self,*args):return io.BytesIO(request)
            def sendall(self,data):self.output.extend(data)
        connection=Connection()
        with patch.object(web.threading,'Thread') as thread:
            web.Handler(connection,('127.0.0.1',1),server)
        return bytes(connection.output),runtime,thread

    def test_accepted_restart_responds_before_shutdown_and_status_is_private(self):
        output,runtime,thread=self.request()
        self.assertIn(b'202 Accepted',output);self.assertTrue(runtime.restart_requested)
        thread.return_value.start.assert_called_once()
        output,_,_=self.request('GET','/api/service/status',headers=[('Host','localhost:8790')])
        self.assertIn(b'403 Forbidden',output)

    def test_browser_guards_busy_work_and_extra_parameters_refuse_restart(self):
        cases=[({'headers':[('Host','localhost:8790')]},403),({'busy':True},409),
               ({'managed':False},409),({'body':{'command':'anything'}},400)]
        for kwargs,status in cases:
            with self.subTest(kwargs=kwargs):
                output,runtime,thread=self.request(**kwargs)
                self.assertIn(str(status).encode(),output.split(b'\r\n')[0])
                self.assertFalse(runtime.restart_requested);thread.assert_not_called()

    def test_valid_service_status_identifies_runtime(self):
        output,runtime,_=self.request('GET','/api/service/status')
        self.assertIn(b'200 OK',output)
        info=json.loads(output.split(b'\r\n\r\n',1)[1])
        self.assertEqual(info['instance_id'],runtime.instance_id)
        self.assertTrue(info['restart_available']);self.assertEqual(info['startup'],'after_login')


class SupervisedExit(unittest.TestCase):
    def test_main_closes_state_and_listener_before_restart_exit(self):
        store=Mock();server=Mock(server_port=8790)
        server.runtime=SimpleNamespace(restart_requested=True,wait_for_idle=lambda:True)
        with patch('sys.argv',['curator','--managed-service']),patch.object(web,'Store',return_value=store), \
             patch.object(web,'App',return_value=server),patch('sys.stdout',new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as error:web.main()
        self.assertEqual(error.exception.code,RESTART_EXIT_CODE)
        server.server_close.assert_called_once();store.close.assert_called_once()

    def test_slow_request_cancels_restart_and_resumes_serving(self):
        store=Mock();server=Mock(server_port=8790)
        server.serve_forever.side_effect=[None,KeyboardInterrupt]
        server.runtime=Mock(restart_requested=True);server.runtime.wait_for_idle.return_value=False
        with patch('sys.argv',['curator','--managed-service']),patch.object(web,'Store',return_value=store), \
             patch.object(web,'App',return_value=server),patch('sys.stdout',new_callable=io.StringIO):
            web.main()
        server.runtime.cancel_restart.assert_called_once();self.assertEqual(server.serve_forever.call_count,2)
        store.close.assert_called_once()


class RealRestart(unittest.TestCase):
    def test_managed_process_exits_and_preserves_database(self):
        import http.cookiejar
        import subprocess
        import sys
        import tempfile
        import urllib.request
        from curator.store import Store
        with tempfile.TemporaryDirectory() as directory:
            original=Store(directory)
            before={table:original.all(table) for table in ('tasks','libraries','assets')}
            original.close()
            identities=[]
            for _ in range(2):
                process=subprocess.Popen([sys.executable,'-u','-m','curator.web','--port','0',
                                          '--state',directory,'--managed-service'],
                                         stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    url=process.stdout.readline().strip().removeprefix('Curator: ')
                    self.assertTrue(url.startswith('http://127.0.0.1:'))
                    client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                    client.open(url+'/',timeout=5).close()
                    with client.open(url+'/api/service/status',timeout=5) as response:
                        identities.append(json.load(response)['instance_id'])
                    request=urllib.request.Request(url+'/api/service/restart',data=b'{}',
                        headers={'Content-Type':'application/json','Origin':url,'X-Curator-Request':'1'})
                    with client.open(request,timeout=5) as response:self.assertEqual(response.status,202)
                    self.assertEqual(process.wait(timeout=8),RESTART_EXIT_CODE)
                    restored=Store(directory)
                    self.assertEqual({table:restored.all(table) for table in before},before)
                    restored.close()
                finally:
                    if process.poll() is None:process.kill();process.wait(timeout=5)
                    process.stdout.close();process.stderr.close()
            self.assertNotEqual(*identities)
