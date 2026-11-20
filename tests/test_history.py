import json
import logging
import tempfile
import threading
import unittest
from pathlib import Path

from curator.errors import UserError
from curator.history import HistoryHandler, acting, current_initiator
from curator.logs import register_secret
from curator.plex import PlexError
from curator.service import Service
from curator.store import Store


class Plex:
    def __init__(self, rows=None, error=None):
        self.rows, self.error = rows or [], error

    def libraries(self):
        if self.error:
            raise PlexError(self.error)
        return [dict(row) for row in self.rows]


LIBRARY = dict(
    id='srv:1', server='srv', key='1', title='Films', type='movie', agent='tv.plex.agents.movie', locations=[]
)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'state'
        self.store = Store(self.root)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def curator(self, **filters):
        return self.store.curator_history(**filters)


class StructuredEvents(Base):
    def test_existing_events_become_job_history_with_their_library(self):
        with self.store.transaction():
            self.store.put('tasks', 't1', dict(id='t1', library='srv:1', status='applied'))
        self.store.db.execute('DROP INDEX events_task')
        self.store.db.execute('DROP INDEX events_category')
        self.store.db.execute('ALTER TABLE events RENAME TO old_events')
        self.store.db.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, at TEXT, task TEXT, data TEXT)')
        self.store.db.execute('DROP TABLE old_events')
        for task in ('t1', 'gone', None):
            self.store.db.execute(
                'INSERT INTO events(at,task,data) VALUES(?,?,?)', ('2026-01-01', task, json.dumps({'action': 'x'}))
            )
        self.store.db.execute('DELETE FROM schema_version WHERE version >= 3')
        self.store.db.commit()
        self.store.close()
        self.store = Store(self.root)
        rows = self.store.db.execute('SELECT task, category, library, initiator FROM events ORDER BY id').fetchall()
        self.assertEqual(rows, [('t1', 'job', 'srv:1', None), ('gone', 'job', None, None), (None, 'job', None, None)])

    def test_job_events_record_library_and_initiator(self):
        with self.store.transaction():
            self.store.put('tasks', 't1', dict(id='t1', library='srv:1', status='recommendation'))
            self.store.event('t1', {'action': 'unattributed'})
            with acting('operator'):
                self.store.event('t1', {'action': 'approved', 'previous': {'large': 'record'}, 'count': 2})
        events = self.store.task_history('t1')
        self.assertEqual(
            [(e['action'], e['initiator']) for e in events], [('unattributed', None), ('approved', 'operator')]
        )
        self.assertEqual(events[1]['count'], 2)
        self.assertNotIn('previous', events[1])
        library = self.store.db.execute("SELECT DISTINCT library FROM events WHERE task='t1'").fetchall()
        self.assertEqual(library, [('srv:1',)])

    def test_queueing_records_who_queued(self):
        with acting('operator'), self.store.transaction():
            self.store.put('tasks', 't1', dict(id='t1', library='srv:1', status='queued'))
        with acting('rule'), self.store.transaction():
            row = self.store.get('tasks', 't1')
            self.store.put('tasks', 't1', row)
        self.assertEqual(self.store.get('tasks', 't1')['queued_by'], 'operator')

    def test_acting_is_scoped_and_validated(self):
        with acting('ai'):
            self.assertEqual(current_initiator(), 'ai')
        self.assertIsNone(current_initiator())
        with self.assertRaises(ValueError), acting('someone'):
            pass


class CuratorHistory(Base):
    def test_record_commits_or_rolls_back_with_the_transaction(self):
        self.store.record('alone', 'Committed alone')
        with self.assertRaises(RuntimeError), self.store.transaction():
            self.store.record('inside', 'Rolled back')
            raise RuntimeError
        self.assertEqual([e['action'] for e in self.curator()], ['alone'])

    def test_record_soon_survives_a_rollback(self):
        with self.assertRaises(RuntimeError), self.store.transaction():
            self.store.record_soon('error', 'Logged during a failing transaction', level='error')
            raise RuntimeError
        self.assertEqual([e['message'] for e in self.curator()], ['Logged during a failing transaction'])

    def test_record_soon_never_waits_for_another_thread(self):
        entered, release = threading.Event(), threading.Event()

        def hold():
            with self.store.transaction():
                entered.set()
                release.wait(5)

        worker = threading.Thread(target=hold)
        worker.start()
        entered.wait(5)
        done = threading.Event()
        threading.Thread(target=lambda: (self.store.record_soon('error', 'Deferred'), done.set())).start()
        self.assertTrue(done.wait(1))
        release.set()
        worker.join()
        self.assertEqual([e['message'] for e in self.curator()], ['Deferred'])

    def test_filters_paging_and_levels(self):
        with acting('operator'):
            self.store.record('scan', 'One', library='srv:1')
        self.store.record('error', 'Two', level='error')
        self.store.record('scan', 'Three', library='srv:2', level='warning')
        self.assertEqual([e['message'] for e in self.curator()], ['Three', 'Two', 'One'])
        self.assertEqual([e['message'] for e in self.curator(library='srv:1')], ['One'])
        self.assertEqual(self.curator(library='srv:1')[0]['initiator'], 'operator')
        self.assertEqual([e['message'] for e in self.curator(level='error')], ['Two'])
        first = self.curator(limit=2)
        self.assertEqual([e['message'] for e in self.curator(before=first[-1]['id'])], ['One'])
        with self.assertRaises(ValueError):
            self.store.record('x', 'y', level='debug')

    def test_old_curator_history_is_pruned(self):
        self.store.CURATOR_HISTORY_LIMIT = 10
        with self.store.transaction():
            for number in range(500):
                self.store.record('n', str(number))
        count = self.store.db.execute("SELECT COUNT(*) FROM events WHERE category='curator'").fetchone()[0]
        self.assertEqual(count, 10)
        self.assertEqual(self.curator(limit=1)[0]['message'], '499')

    def test_logged_errors_are_redacted_without_tracebacks(self):
        register_secret('sekrit-token-value')
        logger = logging.getLogger('curator.test-history')
        handler = HistoryHandler(self.store)
        logger.addHandler(handler)
        try:
            try:
                raise OSError('could not open /x?X-Plex-Token=sekrit-token-value')
            except OSError:
                logger.exception('Upload failed with sekrit-token-value')
            logger.warning('Warnings stay in the log only')
        finally:
            logger.removeHandler(handler)
        events = self.curator()
        self.assertEqual(len(events), 1)
        text = json.dumps(events)
        self.assertNotIn('sekrit-token-value', text)
        self.assertNotIn('Traceback', text)
        self.assertEqual(events[0]['level'], 'error')
        self.assertTrue(events[0]['details']['error'].startswith('OSError: '))


class ServiceHistory(Base):
    def service(self, plex):
        return Service(self.store, lambda *args: plex)

    def test_configuration_changes_name_fields_never_values(self):
        service = self.service(Plex())
        with acting('operator'):
            service.save_config({'plex_token': 'very-secret-token', 'max_mbps_1080': 20})
            service.save_config({'max_mbps_1080': 20})
        events = self.curator()
        self.assertEqual([e['message'] for e in events], ['Configuration changed: max_mbps_1080, plex_token'])
        self.assertNotIn('very-secret-token', json.dumps(events))
        self.assertEqual(events[0]['initiator'], 'operator')

    def test_connection_failure_is_recorded_once_then_restored(self):
        plex = Plex(error='Plex request failed; check server, token and connectivity')
        service = self.service(plex)
        for _ in range(3):
            with self.assertRaises(PlexError):
                service.connect()
        plex.error, plex.rows = None, [LIBRARY]
        service.connect()
        messages = [e['message'] for e in reversed(self.curator())]
        self.assertEqual(
            messages,
            [
                'Plex connection failed: Plex request failed; check server, token and connectivity',
                'Plex connection restored',
                'Libraries refreshed from Plex: 1 available',
            ],
        )
        self.assertEqual(self.curator(level='warning')[0]['action'], 'connection')

    def test_library_and_standard_changes(self):
        service = self.service(Plex(rows=[LIBRARY]))
        service.connect()
        service.save_library('srv:1', dict(profile='home', mappings=[], themes=[]))
        service.save_library('srv:1', dict(profile='home', mappings=[], themes=[]))
        service.save_library_overrides('srv:1', 0, {'cast': {'enabled': True}})
        values = service.standards()['types']['show']['values']
        service.save_type_standard('show', 0, values)
        messages = [e['message'] for e in self.curator(library='srv:1')]
        self.assertEqual(messages, ['Films standard overrides changed', 'Films settings changed: profile'])
        self.assertEqual(self.curator(limit=1)[0]['message'], 'TV Shows standard changed')

    def test_history_request_validation(self):
        service = self.service(Plex())
        self.store.record('a', 'A')
        self.assertEqual(service.history()['next'], None)
        self.assertEqual(len(service.history(limit='1')['events']), 1)
        for bad in (
            dict(view='jobs'),
            dict(level='debug'),
            dict(since='yesterday'),
            dict(limit='0'),
            dict(limit='x'),
            dict(before='1 OR 1'),
        ):
            with self.subTest(bad=bad), self.assertRaises(UserError):
                service.history(**bad)


if __name__ == '__main__':
    unittest.main()
