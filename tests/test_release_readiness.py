"""Fresh-install and publication-boundary regressions using synthetic data only."""
import io
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.request import BaseHandler, build_opener
from urllib.response import addinfourl

import test_curator
from curator import tools
from curator.plex import Plex, PlexError
from curator import web


class ToolDiscovery(unittest.TestCase):
    def test_standard_ffmpeg_tools_work_without_topaz(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('ffmpeg', 'ffprobe'):
                executable = root / name
                executable.write_text('#!/bin/sh\nexit 0\n')
                executable.chmod(0o700)
                with self.subTest(tool=name), patch('curator.tools.TOPAZ', str(root / 'missing') + '/'), \
                     patch('curator.tools.shutil.which', return_value=str(executable)):
                    self.assertEqual(tools.executable({}, name), str(executable))

    def test_invalid_explicit_tool_never_falls_back_to_path(self):
        with patch('curator.tools.shutil.which') as lookup:
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                tools.executable({'ffmpeg': '/missing/explicit/ffmpeg'}, 'ffmpeg')
            lookup.assert_not_called()


class CredentialBoundary(unittest.TestCase):
    def test_api_redirect_is_not_followed_with_plex_token(self):
        calls = []

        class RedirectingServer(BaseHandler):
            handler_order = 100

            def http_open(self, request):
                calls.append(request)
                headers = Message()
                if len(calls) == 1:
                    headers['Location'] = 'http://elsewhere.test/collect'
                    status, data = 302, b''
                else:
                    status, data = 200, b'{"MediaContainer": {}}'
                response = addinfourl(io.BytesIO(data), headers, request.full_url, status)
                response.msg = 'fixture response'
                return response

        # Replace only the transport handler, not redirect handling, and never use a socket.
        from curator import plex
        real_opener = build_opener

        def fixture_opener(*handlers):
            return real_opener(*handlers, RedirectingServer())

        with patch.object(plex, 'build_opener', side_effect=fixture_opener), \
             patch.object(plex, 'urlopen', real_opener(RedirectingServer()).open, create=True):
            with self.assertRaises(PlexError):
                Plex('http://plex.test', 'fixture-token').request('/identity')
        self.assertEqual(len(calls), 1, 'A credential-bearing request followed a redirect')


class PublicationSafety(unittest.TestCase):
    setUp = test_curator.Workflows.setUp
    tearDown = test_curator.Workflows.tearDown

    def test_file_created_during_swap_is_preserved_with_original_and_output(self):
        output = self.root / 'result.mkv'
        output.write_bytes(b'processed-video')
        task = dict(self.task, kind='optimize', status='awaiting_review', output=str(output),
                    validation=[], source_hash=tools.digest(self.file), output_hash=tools.digest(output),
                    comparison_loaded=True)
        with self.store.transaction():
            self.store.put('tasks', task['id'], task)
        replace = __import__('os').replace

        def concurrent_writer(source, destination):
            result = replace(source, destination)
            if Path(source).resolve() == self.file.resolve():
                self.file.write_bytes(b'new-external-file')
            return result

        with patch('curator.service.os.replace', side_effect=concurrent_writer):
            with self.assertRaises(ValueError):
                self.service.review(task['id'], 1, 'manual')
        self.assertEqual(self.file.read_bytes(), b'new-external-file')
        self.assertEqual(self.file.with_name('film-old.mkv').read_bytes(), b'original-video')
        self.assertEqual(output.read_bytes(), b'processed-video')
        self.assertFalse(self.service.get_task(task['id']).get('published'))
        self.assertEqual(self.plex.writes, [])


class Startup(unittest.TestCase):
    def test_listener_failure_releases_state_and_explains_next_action(self):
        from unittest.mock import Mock
        state = Mock()
        with patch('sys.argv', ['curator']), patch.object(web, 'Store', return_value=state), \
             patch.object(web, 'App', side_effect=OSError('Address already in use')), \
             patch('sys.stderr', new_callable=io.StringIO) as output:
            with self.assertRaises(SystemExit) as error:
                web.main()
        self.assertEqual(error.exception.code, 2)
        state.close.assert_called_once()
        self.assertIn('--port 8791', output.getvalue())
        self.assertNotIn('Traceback', output.getvalue())
