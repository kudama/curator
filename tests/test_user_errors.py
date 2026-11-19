"""Only UserError text reaches the browser; any other failure is logged and made generic."""

import io
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_curator
from curator.errors import UserError, user_message
from curator.plex import PlexError
from curator.queue_workflows import SourceBusy
from curator.runtime import RestartBlocked, Restarting
from curator.web import Handler


def handler(path, method='POST', body=b'{}', service=None):
    request = object.__new__(Handler)
    request.path, request.command = path, method
    request.headers = {'Content-Length': str(len(body))}
    request.rfile = io.BytesIO(body)
    request.server = SimpleNamespace(service=service or SimpleNamespace())
    request.request_host = lambda: True
    request.allowed = lambda mutate=False: True
    request.reply = Mock()
    return request


class UserErrors(unittest.TestCase):
    def test_provider_and_queue_errors_are_user_errors_and_still_value_errors(self):
        for error in (PlexError('Plex refused'), SourceBusy('Busy'), RestartBlocked('Work running'), UserError('x')):
            self.assertIsInstance(error, UserError)
            self.assertIsInstance(error, ValueError)

    def test_user_message(self):
        self.assertEqual(user_message(UserError('Choose a preset'), 'fallback'), 'Choose a preset')
        self.assertEqual(user_message(ValueError('invalid literal for int()'), 'fallback'), 'fallback')
        self.assertEqual(user_message(UserError('abcdef'), 'fallback', limit=3), 'abc')

    def test_post_shows_user_errors(self):
        request = handler('/api/tasks/unknown-route-raises', body=b'[]')
        request.post_response()
        request.reply.assert_called_once_with({'error': 'Expected a JSON object'}, 400)

    def test_post_hides_standard_library_messages(self):
        for body in (b'{not json', b'\xff\xfe'):
            request = handler('/api/settings', body=body)
            with self.assertLogs('curator', 'WARNING') as logged:
                request.post_response()
            request.reply.assert_called_once_with({'error': 'Missing or invalid request field'}, 400)
            self.assertIn('Traceback', '\n'.join(logged.output))

    def test_post_bad_base64_is_generic(self):
        body = json.dumps(dict(id='x', image='***not base64***')).encode()
        request = handler('/api/cover/apply', body=body)
        with self.assertLogs('curator', 'WARNING'):
            request.post_response()
        request.reply.assert_called_once_with({'error': 'Missing or invalid request field'}, 400)

    def test_restart_blocked_is_a_conflict(self):
        request = handler('/api/x')
        request.error_reply(RestartBlocked('Finish running work first'))
        request.reply.assert_called_once_with({'error': 'Finish running work first'}, 409)

    def test_restarting_is_never_swallowed(self):
        with self.assertRaises(Restarting):
            handler('/api/x').error_reply(Restarting())

    def test_get_unexpected_failure_replies_instead_of_dropping_the_connection(self):
        service = SimpleNamespace(state=Mock(side_effect=RuntimeError('bug with private detail')))
        request = handler('/api/state', 'GET', service=service)
        with self.assertLogs('curator', 'ERROR') as logged:
            request.get_response()
        request.reply.assert_called_once_with(
            {'error': 'Operation failed; configuration or provider needs attention'}, 500
        )
        self.assertIn('bug with private detail', '\n'.join(logged.output))

    def test_get_user_error_and_missing_parameter(self):
        service = SimpleNamespace(state=Mock(side_effect=UserError('Scan a library first')))
        request = handler('/api/state', 'GET', service=service)
        request.get_response()
        request.reply.assert_called_once_with({'error': 'Scan a library first'}, 400)
        request = handler('/api/state', 'GET', service=SimpleNamespace(state=Mock(side_effect=KeyError('library'))))
        with self.assertLogs('curator', 'WARNING'):
            request.get_response()
        request.reply.assert_called_once_with({'error': 'Missing or invalid request field'}, 400)


class BackgroundTaskErrors(unittest.TestCase):
    setUp = test_curator.Workflows.setUp
    tearDown = test_curator.Workflows.tearDown

    def test_internal_value_error_is_not_shown_on_the_task(self):
        task = dict(self.task, kind='join', status='awaiting_review', comparison_loaded=True)
        with self.store.transaction():
            self.store.put('tasks', task['id'], task)
        finished = threading.Event()
        original = self.service._finish_review

        def finish(*args):
            try:
                return original(*args)
            finally:
                finished.set()

        with (
            patch.object(self.service, 'publish_join', side_effect=ValueError('Expecting value: line 1 column 1')),
            patch.object(self.service, '_finish_review', finish),
            self.assertLogs('curator', 'ERROR'),
        ):
            self.service.review(task['id'], 1, 'manual', background=True)
            self.assertTrue(finished.wait(2))
            for _ in range(200):  # let the file-queue worker finish before the store closes
                with self.service.lock:
                    if not self.service.file_workers:
                        break
                threading.Event().wait(0.01)
        saved = self.service.get_task(task['id'])
        self.assertEqual(saved['status'], 'blocked')
        self.assertNotIn('Expecting value', saved['error'])
        self.assertIn('Unexpected publication error', saved['error'])


if __name__ == '__main__':
    unittest.main()
