import copy
import json
import unittest
from curator.state_updates import StateUpdates
from curator.web import Handler
from types import SimpleNamespace
from unittest.mock import Mock


class StateUpdateTests(unittest.TestCase):
    def setUp(self):
        self.cache = StateUpdates(capacity=2)
        self.state = dict(assets=[dict(id='a', title='A'), dict(id='b', title='B')],
                          tasks=[dict(id='t', status='queued', plan={'large': 'x' * 100000})],
                          config={'token_configured': True}, queue_running=False)

    def test_initial_unchanged_and_single_record_change(self):
        initial = self.cache.response(self.state)
        self.assertTrue(initial['reset'])
        same = self.cache.response(self.state, initial['revision'])
        self.assertFalse(same['reset'])
        self.assertEqual(same['changes'], {})
        self.assertEqual(same['fields'], {})
        self.assertLess(len(json.dumps(same)), len(json.dumps(initial)) / 100)
        changed = copy.deepcopy(self.state)
        changed['assets'][1]['title'] = 'New'
        changed['queue_running'] = True
        delta = self.cache.response(changed, initial['revision'])
        self.assertEqual(delta['changes'], {'assets': dict(upsert=[changed['assets'][1]], removed=[])})
        self.assertEqual(delta['fields'], {'queue_running': True})

    def test_removal_insertion_order_and_expired_revision(self):
        original = self.cache.response(self.state)
        self.state['assets'].reverse()
        reordered = self.cache.response(self.state, original['revision'])
        self.assertNotEqual(reordered['revision'], original['revision'])
        self.assertEqual(reordered['changes']['assets']['order'], ['b', 'a'])
        self.state['assets'] = [dict(id='c', title='C')]
        changed = self.cache.response(self.state, reordered['revision'])
        self.assertEqual(set(changed['changes']['assets']['removed']), {'a', 'b'})
        self.assertEqual(changed['changes']['assets']['upsert'], self.state['assets'])
        self.assertTrue(self.cache.response(self.state, original['revision'])['reset'])
        self.assertTrue(StateUpdates().response(self.state, changed['revision'])['reset'])
        self.assertLessEqual(len(self.cache.snapshots), 2)

    def test_disconnected_client_does_not_trigger_second_error_response(self):
        handler = object.__new__(Handler)
        handler.server = object()
        for exception in (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            with self.subTest(exception=exception):
                def disconnected():
                    raise exception('client closed')
                handler.dispatch(disconnected)
        with self.assertRaises(RuntimeError):
            handler.dispatch(lambda: (_ for _ in ()).throw(RuntimeError('real server failure')))

    def test_state_disconnect_is_not_replied_to_as_resource_error(self):
        handler = object.__new__(Handler)
        handler.server = SimpleNamespace(service=SimpleNamespace(state=lambda: {}))
        handler.path = '/api/state'
        handler.request_host = lambda: True
        handler.allowed = lambda: True
        handler.reply = Mock(side_effect=BrokenPipeError('closed'))
        handler.dispatch(handler.get_response)
        self.assertEqual(handler.reply.call_count, 1)
