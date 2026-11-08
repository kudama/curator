import unittest
from unittest.mock import patch

import test_curator
from curator.plex import Plex, PlexError


class Metadata(unittest.TestCase):
    setUp = test_curator.Workflows.setUp
    tearDown = test_curator.Workflows.tearDown

    def tagged_adapter(self):
        def edit(library, item, changes):
            self.plex.writes.append(changes)
            for field, value in changes.items():
                self.plex.rows[0][field.title() if isinstance(value, list) else field] = (
                    [{'tag': x} for x in reversed(value)] if isinstance(value, list) else value)
            return self.plex.item('10')
        self.plex.edit = edit

    def test_apply_displayed_description_overrides_older_proposal(self):
        saved = self.service.edit_task(self.task['id'], {'changes': {'summary': 'Old proposal'}}, 1)
        result = self.service.apply_metadata(saved['id'], saved['version'], {'summary': 'Displayed description'})
        self.assertEqual(self.plex.rows[0]['summary'], 'Displayed description')
        self.assertEqual(result['status'], 'applied')
        self.assertEqual(self.store.get('assets', self.asset['id'])['item']['summary'], 'Displayed description')

    def test_home_apply_uses_displayed_fields_not_original_ai_result(self):
        task = dict(self.task, kind='home', status='awaiting_review', result={'summary': 'AI draft'})
        with self.store.transaction():
            self.store.put('tasks', task['id'], task)
        self.service.apply_metadata(task['id'], 1, {'summary': 'Human edit'})
        self.assertEqual(self.plex.writes, [{'summary': 'Human edit'}])

    def test_all_requested_fields_verified_and_cached(self):
        self.tagged_adapter()
        changes = {'summary': 'Description', 'studio': 'Example studio', 'tagline': 'A tagline',
                   'genre': ['Travel', 'Family'], 'label': ['Private'], 'collection': ['Summer']}
        result = self.service.apply_metadata(self.task['id'], 1, changes)
        self.assertEqual(result['status'], 'applied')
        actual = self.service.metadata_fields(self.store.get('assets', self.asset['id'])['item'])
        self.assertEqual(actual['studio'], changes['studio'])
        self.assertEqual(actual['genre'], ['Family', 'Travel'])
        self.assertEqual(actual['label'], ['Private'])

    def test_clear_scalar_and_tag_fields(self):
        self.tagged_adapter()
        self.plex.rows[0].update(studio='Studio', tagline='Tagline', Genre=[{'tag': 'Old'}], Label=[{'tag': 'Old label'}])
        self.asset['item'] = self.plex.item('10')
        with self.store.transaction():
            self.store.put('assets', self.asset['id'], self.asset)
        self.service.apply_metadata(self.task['id'], 1, {'studio': '', 'tagline': '', 'genre': [], 'label': []})
        self.assertEqual(self.plex.rows[0]['Genre'], [])
        self.assertEqual(self.plex.rows[0]['studio'], '')

    def test_external_metadata_change_blocks_apply(self):
        self.plex.rows[0]['summary'] = 'Changed elsewhere'
        with self.assertRaisesRegex(ValueError, 'metadata changed'):
            self.service.apply_metadata(self.task['id'], 1, {'summary': 'My edit'})
        self.assertEqual(self.plex.writes, [])
        self.assertEqual(self.service.get_task(self.task['id'])['status'], 'blocked')

    def test_readback_mismatch_does_not_claim_success(self):
        self.plex.edit = lambda *args: self.plex.item('10')
        with self.assertRaisesRegex(ValueError, 'readback differs'):
            self.service.apply_metadata(self.task['id'], 1, {'summary': 'Not saved'})
        self.assertEqual(self.store.get('assets', self.asset['id'])['item']['summary'], 'Before')

    def test_stale_version_and_running_task_rejected(self):
        with self.assertRaises(ValueError):
            self.service.apply_metadata(self.task['id'], 2, {'summary': 'Edit'})
        with self.store.transaction():
            self.store.put('tasks', self.task['id'], dict(self.task, status='running'))
        with self.assertRaises(ValueError):
            self.service.apply_metadata(self.task['id'], 1, {'summary': 'Edit'})
        self.assertEqual(self.plex.writes, [])

    def test_invalid_fields_and_types_never_reach_plex(self):
        for changes in [{'studio': []}, {'label': 'tag'}, {'label': ['']}, {'unsupported': 'x'}, {}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.service.apply_metadata(self.task['id'], 1, changes)
        self.assertEqual(self.plex.writes, [])

    def test_queued_legacy_snapshot_still_applies_and_refreshes_cache(self):
        task = self.service.edit_task(self.task['id'], {'changes': {'summary': 'Queued'}}, 1)
        task = self.service.action(task['id'], 'queue', task['version'])
        task['metadata_before'] = {k: v for k, v in task['metadata_before'].items() if k not in {'studio', 'tagline', 'label'}}
        with self.store.transaction():
            self.store.put('tasks', task['id'], task)
        self.service._execute(task['id'])
        self.assertEqual(self.service.get_task(task['id'])['status'], 'applied')
        self.assertEqual(self.store.get('assets', self.asset['id'])['item']['summary'], 'Queued')

    def test_edit_metadata_can_be_opened_without_scan_finding(self):
        with self.store.transaction():
            self.store.db.execute('DELETE FROM tasks')
        task = self.service.metadata_task(self.asset['id'])
        self.assertEqual(task['kind'], 'metadata')
        self.assertEqual(self.service.metadata_task(self.asset['id'])['id'], task['id'])

    def test_open_metadata_refreshes_full_fields_without_writing_to_plex(self):
        self.plex.rows[0].update(studio='Fresh studio', Label=[{'tag': 'Fresh label'}])
        result = self.service.read_metadata(self.task['id'])
        self.assertEqual(result['item']['studio'], 'Fresh studio')
        self.assertEqual(self.store.get('assets', self.asset['id'])['item']['Label'], [{'tag': 'Fresh label'}])
        self.assertEqual(self.plex.writes, [])

    def test_queue_displayed_description_then_run(self):
        task = self.service.queue_metadata(self.task['id'], 1, {'summary': 'Queued description'})
        self.assertEqual(task['status'], 'queued')
        self.assertEqual(self.plex.writes, [])
        self.service._execute(task['id'])
        self.assertEqual(self.service.get_task(task['id'])['status'], 'applied')
        self.assertEqual(self.plex.rows[0]['summary'], 'Queued description')

    def test_queue_home_metadata_does_not_run_analysis(self):
        with self.store.transaction():
            source = self.service.task(self.asset, {'kind': 'home', 'reason': 'Analyze'})
        task = self.service.queue_metadata(source['id'], source['version'], {'summary': 'Reviewed summary'})
        self.assertEqual(task['kind'], 'metadata')
        self.assertNotEqual(task['id'], source['id'])
        self.assertEqual(task['approval'], task['version'])
        self.service._execute(task['id'])
        self.assertEqual(self.plex.rows[0]['summary'], 'Reviewed summary')

    def test_plex_request_includes_studio_tagline_and_tag_removals(self):
        plex = Plex('http://localhost:32400', 'test')
        item = dict(ratingKey='10', type='movie', Label=[{'tag': 'Old label'}], Genre=[{'tag': 'Old genre'}])
        with patch.object(plex, 'request', return_value={}) as request, patch.object(plex, 'item', return_value=item):
            plex.edit({'key': '1'}, item, {'summary': 'Description', 'studio': 'Studio', 'tagline': 'Tagline', 'label': [], 'genre': ['New genre']})
        params = request.call_args.args[2]
        self.assertEqual(params['summary.value'], 'Description')
        self.assertEqual(params['studio.value'], 'Studio')
        self.assertEqual(params['tagline.value'], 'Tagline')
        self.assertEqual(params['label[].tag.tag-'], 'Old%20label')
        self.assertEqual(params['genre[].tag.tag-'], 'Old%20genre')
        self.assertEqual(params['genre[0].tag.tag'], 'New genre')
        self.assertEqual(params['label.locked'], 1)
