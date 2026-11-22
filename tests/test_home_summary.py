import copy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from curator.errors import UserError
from curator.history import acting
from curator.service import Service
from curator.store import Store, now


class Home(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'state')
        self.addCleanup(self.store.close)
        self.service = Service(self.store)
        self.at = now()
        self.clock = datetime.now(timezone.utc)
        with self.store.transaction():
            for key in ('one', 'two'):
                self.store.put(
                    'libraries',
                    key,
                    dict(
                        id=key,
                        server='server',
                        key=key,
                        title='Library ' + key,
                        type='movie',
                        agent='movie',
                        kind='movie',
                        standard_kind='movie',
                        observed_kind='movie',
                        profile='commercial',
                        mappings=[],
                    ),
                )
        self.asset('a1', 'one')
        self.asset('a2', 'two')

    def asset(self, key, library, **changes):
        row = dict(
            id=key,
            library=library,
            rating_key='1',
            title='Private title ' + key,
            present=True,
            scanned=self.at,
            local_path='/private/catalogue/' + key,
            plex_path='/secret/' + key,
            technical=dict(width=1920, height=1080, duration_seconds=60, bitrate=8_000_000),
            item=dict(
                type='movie',
                ratingKey='1',
                title='Private title ' + key,
                summary='Summary',
                year=2026,
                Genre=[{'tag': 'Family'}],
                addedAt=int(self.clock.timestamp()) - 60,
            ),
        )
        row.update(changes)
        with self.store.transaction():
            self.store.put('assets', key, row)
        return row

    def task(self, key, kind='upscale', status='awaiting_review', library='one', **changes):
        row = dict(
            id=key,
            asset='a1' if library == 'one' else 'a2',
            library=library,
            title='Private task ' + key,
            kind=kind,
            status=status,
            version=1,
            created=self.at,
            updated=self.at,
            plan={},
        )
        row.update(changes)
        with self.store.transaction():
            self.store.put('tasks', key, row)
        return row

    def test_home_get_never_calls_providers_writes_or_creates_work(self):
        before = {table: self.store.all(table) for table in self.store.TABLES}
        events = self.store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        with patch.object(self.service, 'checked_client', side_effect=AssertionError('network')):
            first = self.service.home_summary()
            self.service.home_summary(view='compact')
        self.assertEqual({table: self.store.all(table) for table in self.store.TABLES}, before)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0], events)
        self.assertFalse(first['stale'])
        self.assertEqual(first['health']['complete_items'], 2)

    def test_scope_and_cross_library_same_rating_key_never_merge(self):
        both = self.service.home_summary()
        self.assertEqual(both['arrivals_total'], 2)
        self.assertEqual({row['library'] for row in both['arrivals']}, {'one', 'two'})
        one = self.service.home_summary(library='one')
        self.assertEqual(one['arrivals_total'], 1)
        self.assertEqual(one['arrivals'][0]['asset'], 'a1')
        self.assertIn('asset=a1', one['arrivals'][0]['href'])
        self.assertTrue(one['links']['history'].endswith('library=one&period=7'))

    def test_review_families_have_exact_separate_destinations(self):
        for key, kind, library in [
            ('result', 'upscale', 'one'),
            ('preview', 'preview_render', 'two'),
            ('meta', 'home', 'one'),
            ('art', 'artwork', 'one'),
            ('portrait', 'portrait', 'two'),
        ]:
            self.task(key, kind, library=library)
        result = self.service.home_summary()
        self.assertEqual(result['counts']['ready'], 5)
        self.assertEqual((result['decisions']['results'], result['decisions']['metadata']), (2, 1))
        self.assertEqual(result['links']['results'], '#/library/all/review')
        self.assertEqual(result['links']['metadata'], '#/library/all/queue?status=review&lane=metadata')
        self.assertEqual(
            {row['href'] for row in result['decisions']['artwork']},
            {'#/library/one/artwork?status=review', '#/library/two/artwork?status=review'},
        )

    def test_health_disabled_optional_and_missing_are_distinct(self):
        self.service.save_library_overrides(
            'one', 0, {'metadata': {'required': ['studio']}, 'artwork': {'enabled': True}}
        )
        result = self.service.home_summary()
        self.assertEqual(result['decisions']['missing_required'], 1)
        rows = {row['library']: row for row in result['libraries']}
        self.assertEqual(rows['two']['complete'], 1)
        self.assertNotIn('cast', [row['dimension'] for row in rows['two']['dimensions']])
        self.assertEqual(rows['one']['dimensions'][0]['needs_attention'], 1)
        self.assertIn('dimension=metadata', rows['one']['dimensions'][0]['href'])

    def test_old_unknown_and_empty_scopes_never_look_fresh_or_healthy(self):
        self.asset('a1', 'one', scanned=None, technical={})
        result = self.service.home_summary()
        self.assertTrue(result['stale'])
        self.assertIsNone(result['observed_at'])
        self.assertEqual(result['health']['unknown_items'], 1)
        self.service.plex_failure = 'unavailable'
        self.assertTrue(self.service.home_summary(library='two')['stale'])
        with self.store.transaction():
            self.store.db.execute('DELETE FROM assets')
        result = self.service.home_summary()
        self.assertTrue(all(row['status'] == 'unknown' for row in result['libraries']))
        self.assertTrue(
            all(dimension['percent'] is None for row in result['libraries'] for dimension in row['dimensions'])
        )

    def test_compact_projection_excludes_catalogue_titles_paths_and_settings(self):
        self.task('work', 'metadata', 'blocked', error='Private source path')
        result = self.service.home_summary(view='compact')
        text = str(result)
        for secret in ('Private title', 'Private task', '/secret', '/private/catalogue', 'plex_token', 'Library one'):
            self.assertNotIn(secret, text)
        self.assertEqual(result['schema_version'], 1)
        self.assertNotIn('arrivals', result)
        self.assertNotIn('libraries', result)
        self.assertEqual(result['links']['ready'], '#/home')

    def test_recorded_completion_survives_requeue_and_deduplicates_publish_job(self):
        with acting('operator'):
            task = self.task('done', status='queued', source={'size': 100}, result={'size_bytes': 40}, published=True)
        task.update(status='applied')
        with self.store.transaction():
            self.store.put('tasks', 'done', task)
            self.store.put(
                'settings',
                'file-op',
                dict(
                    id='file-op',
                    record_type='file_operation',
                    operation='publish',
                    payload={'task': 'done'},
                    library='one',
                    phase='complete',
                    created=self.at,
                    updated=self.at,
                ),
            )
        work = self.service.home_summary()['work']
        self.assertEqual((work['completed'], work['published'], work['known_space_saved_bytes']), (1, 1, 60))
        self.assertEqual(work['initiators']['operator'], 1)
        task.update(status='queued', version=2)
        with self.store.transaction():
            self.store.put('tasks', 'done', task)
        self.assertEqual(self.service.home_summary()['work']['completed'], 1)
        task.update(status='applied', published=False)
        with self.store.transaction():
            self.store.put('tasks', 'done', task)
        self.assertEqual(self.service.home_summary()['work']['completed'], 2)

    def test_old_completion_is_not_redated_by_mutable_updated_field(self):
        older = (self.clock - timedelta(days=20)).isoformat()
        with patch('curator.store.now', return_value=older):
            self.task('older', status='applied', published=True, result={})
        self.assertEqual(self.service.home_summary()['work']['completed'], 0)
        self.task('unknown', status='applied', published=True, result={})
        work = self.service.home_summary()['work']
        self.assertEqual(work['space_unknown_items'], 1)
        self.assertEqual(work['initiators']['unknown'], 1)
        self.assertTrue(work['history_complete'])

    def test_file_queue_count_and_attention_do_not_duplicate_task_bookkeeping(self):
        self.task('blocked', status='blocked')
        with self.store.transaction():
            for key, phase, task in [
                ('failure', 'failed', 'blocked'),
                ('export', 'waiting', None),
                ('publication', 'waiting', 'ready'),
            ]:
                self.store.put(
                    'settings',
                    key,
                    dict(
                        id=key,
                        record_type='file_operation',
                        library='one',
                        operation='publish',
                        payload={'task': task},
                        phase=phase,
                        created=self.at,
                        updated=self.at,
                    ),
                )
        self.task('ready')
        result = self.service.home_summary()
        self.assertEqual(result['counts']['needs_attention'], 1)
        self.assertEqual(result['counts']['waiting'], 2)
        self.assertEqual(result['counts']['ready'], 0)

    def test_bad_scope_limit_and_view_are_refused(self):
        for kwargs in ({'library': 'unknown'}, {'view': 'raw'}, {'limit': True}, {'limit': 0}, {'limit': 31}):
            with self.assertRaises(UserError):
                self.service.home_summary(**kwargs)
