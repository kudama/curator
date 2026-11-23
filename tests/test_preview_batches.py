"""Selected batches keep independent, idempotent renderer work and mixed outcomes."""

import copy
import concurrent.futures
import uuid
from unittest.mock import patch
import unittest
from curator import tools
from curator.errors import UserError
from curator.preview_cards import DEFAULTS
import test_preview_render


class PreviewBatches(unittest.TestCase):
    def setUp(self):
        test_preview_render.PreviewPlans.setUp(self)
        with self.store.transaction():
            self.store.db.execute('DELETE FROM tasks')
            self.store.put('settings', self.service.pause_key(None, 'optimize'), True)

    tearDown = test_preview_render.PreviewPlans.tearDown
    plan = test_preview_render.PreviewPlans.plan

    def second_asset(self):
        path = self.media / 'other.mkv'
        path.write_bytes(b'second original')
        asset = {
            **copy.deepcopy(self.asset),
            'id': 'b' * 24,
            'title': 'Other',
            'rating_key': '20',
            'plex_path': '/plex/other.mkv',
            'local_path': str(path.resolve()),
            'fingerprint': tools.fingerprint(path),
        }
        with self.store.transaction():
            self.store.put('assets', asset['id'], asset)
        return asset

    def manifest(self, assets=None):
        self.plan()  # Freeze disposable tool identities used by existing renderer planning.
        with patch('curator.preview_render.tools.probe', return_value=test_preview_render.media()):
            items = []
            for asset in assets or [self.asset, self.second_asset()]:
                info = self.service.preview_info(asset['id'])
                items.append(dict(asset=asset['id'], asset_version=info['asset_version'], start_ms=0, audio_stream=1))
            return self.service.create_preview_batch(
                dict(items=items, values={**DEFAULTS, 'requested_duration_ms': 3000}, defaults_revision=1)
            )

    def test_explicit_selection_exact_settings_and_paused_shared_encoding(self):
        batch = self.manifest()
        self.assertEqual(batch['count'], 2)
        self.assertEqual(batch['ready_count'], 2)
        self.assertFalse(self.store.all('tasks'))
        self.assertTrue(all(row['settings']['timing']['end_ms'] == 3000 for row in batch['rows']))
        request = uuid.uuid4().hex
        result = self.service.submit_preview_batch(batch['id'], request)
        again = self.service.submit_preview_batch(batch['id'], request)
        self.assertEqual([r['job'] for r in result['rows']], [r['job'] for r in again['rows']])
        self.assertEqual(len(self.store.all('tasks')), 2)
        self.assertTrue(all(t['kind'] == 'preview_render' for t in self.store.all('tasks')))
        self.assertEqual(self.service.active, set())
        self.assertEqual(len(self.service.waiting_tasks(kind='optimize')), 2)
        self.assertNotIn(str(self.root), str(result))
        self.assertFalse(self.plex.writes)

    def test_changed_source_mixed_result_keeps_other_job(self):
        batch = self.manifest()
        self.file.write_bytes(b'changed')
        result = self.service.submit_preview_batch(batch['id'], uuid.uuid4().hex)
        self.assertEqual(result['outcome'], 'mixed')
        self.assertEqual(result['rows'][0]['status'], 'unavailable')
        self.assertEqual(result['rows'][1]['status'], 'queued')
        self.assertEqual(len(self.store.all('tasks')), 1)

    def test_duplicate_and_missing_sources_are_explicit(self):
        batch = self.manifest()
        row = dict(asset=self.asset['id'], asset_version='stale', start_ms=0, audio_stream=1)
        with self.assertRaises(UserError):
            self.service.create_preview_batch(dict(items=[row, row], values=DEFAULTS, defaults_revision=1))
        with patch('curator.preview_render.tools.probe', return_value=test_preview_render.media()):
            missing = self.service.create_preview_batch(
                dict(items=[{**row, 'asset': 'missing'}], values=DEFAULTS, defaults_revision=1)
            )
        self.assertEqual(missing['rows'][0]['status'], 'unavailable')
        self.assertEqual(missing['ready_count'], 0)
        self.assertEqual(batch['count'], 2)

    def test_crash_after_individual_submit_resumes_same_job_only(self):
        batch = self.manifest()
        original = self.service.generate_preview

        def interrupted(plan, key):
            original(plan, key)
            raise RuntimeError('synthetic power loss before manifest write')

        request = uuid.uuid4().hex
        with patch.object(self.service, 'generate_preview', side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.service.submit_preview_batch(batch['id'], request)
        self.assertEqual(len(self.store.all('tasks')), 1)
        self.assertEqual(self.service.preview_batch(batch['id'])['status'], 'submitting')
        resumed = self.service.submit_preview_batch(batch['id'], request)
        self.assertEqual(len(self.store.all('tasks')), 2)
        self.assertTrue(all(row['job'] for row in resumed['rows']))
        self.assertEqual(len({row['job'] for row in resumed['rows']}), 2)

    def test_concurrent_same_request_never_duplicates_jobs(self):
        batch = self.manifest()
        request = uuid.uuid4().hex
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.service.submit_preview_batch(batch['id'], request), range(2)))
        self.assertEqual(len(self.store.all('tasks')), 2)
        self.assertEqual([r['job'] for r in results[0]['rows']], [r['job'] for r in results[1]['rows']])
        with self.assertRaises(UserError):
            self.service.submit_preview_batch(batch['id'], uuid.uuid4().hex)

    def test_mixed_runtime_outcomes_and_selection_remain_individual(self):
        batch = self.manifest()
        result = self.service.submit_preview_batch(batch['id'], uuid.uuid4().hex)
        one, two = [self.service.get_task(r['job']) for r in result['rows']]
        with self.store.transaction():
            one.update(status='awaiting_review')
            two.update(status='blocked', error='Interrupted; inspect retained output')
            self.store.put('tasks', one['id'], one)
            self.store.put('tasks', two['id'], two)
        read = self.service.public_preview_batch(self.service.preview_batch(batch['id']))
        self.assertEqual(read['outcome'], 'mixed')
        self.assertEqual(read['rows'][0]['status'], 'awaiting_review')
        self.assertEqual(read['rows'][1]['status'], 'blocked')
        self.assertIsNone(self.service.preview_selection(one['asset'])['job'])
        self.assertEqual(self.service.preview_batches(self.lib['id'])[0]['id'], batch['id'])

    def test_defaults_change_requires_new_review_no_work_started(self):
        batch = self.manifest()
        self.service.save_preview_defaults(1, {'audio_fade_ms': 200})
        result = self.service.submit_preview_batch(batch['id'], uuid.uuid4().hex)
        self.assertTrue(all(row['status'] == 'unavailable' for row in result['rows']))
        self.assertFalse(self.store.all('tasks'))

    def test_aliases_of_same_physical_file_are_rejected(self):
        alias = {**self.asset, 'id': 'c' * 24}
        with self.store.transaction():
            self.store.put('assets', alias['id'], alias)
        with self.assertRaises(UserError):
            self.manifest([self.asset, alias])

    def test_changed_edition_only_blocks_that_item(self):
        batch = self.manifest()
        current = self.store.get('assets', self.asset['id'])
        current['item'] = {**current['item'], 'editionTitle': 'Different edition'}
        with self.store.transaction():
            self.store.put('assets', current['id'], current)
        result = self.service.submit_preview_batch(batch['id'], uuid.uuid4().hex)
        self.assertEqual(result['rows'][0]['status'], 'unavailable')
        self.assertEqual(result['rows'][1]['status'], 'queued')

    def test_actual_restart_keeps_interrupted_item_and_resumes_only_unsubmitted_items(self):
        from curator.service import Service
        from curator.store import Store

        batch = self.manifest()
        original = self.service.generate_preview

        def interrupted(plan, key):
            result = original(plan, key)
            with self.store.transaction():
                task = self.service.get_task(result['id'])
                task['status'] = 'running'
                self.store.put('tasks', task['id'], task)
            raise RuntimeError('synthetic power loss')

        request = uuid.uuid4().hex
        with patch.object(self.service, 'generate_preview', side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.service.submit_preview_batch(batch['id'], request)
        state = self.store.root
        self.store.close()
        self.store = Store(state)
        self.service = Service(self.store, lambda *args: self.plex)
        result = self.service.submit_preview_batch(batch['id'], request)
        self.assertEqual(len(self.store.all('tasks')), 2)
        self.assertEqual(result['rows'][0]['status'], 'blocked')
        self.assertEqual(result['rows'][1]['status'], 'queued')
        self.assertEqual(result['outcome'], 'mixed')
