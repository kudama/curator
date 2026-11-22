import copy
import unittest
from unittest.mock import patch
import test_curator
from curator.service import identifier
from curator.store import now


class MetadataManagers(unittest.TestCase):
    setUp = test_curator.Workflows.setUp
    tearDown = test_curator.Workflows.tearDown

    def preview(self, fields):
        return self.service.metadata_preview([{'id': self.task['id'], 'version': self.task['version']}], fields)

    def test_preview_and_approval_only_queue_and_keep_unchecked_labels(self):
        self.plex.rows[0]['Label'] = [{'tag': 'Keep this private label'}]
        p = self.preview(
            {'genre': {'mode': 'add', 'values': [' Travel ', 'travel', 'New category']}, 'studio': 'Creator'}
        )
        row = p['rows'][0]
        self.assertEqual(row['changes']['genre'], ['Travel', 'New category'])
        self.assertEqual(row['before']['label'], ['Keep this private label'])
        self.assertNotIn('label', row['changes'])
        self.assertEqual(self.plex.writes, [])
        result = self.service.approve_metadata_preview(p['id'])
        task = self.service.get_task(result['tasks'][0])
        self.assertEqual(task['status'], 'queued')
        self.assertEqual(task['metadata_before'], row['before'])
        self.assertEqual(self.plex.writes, [])
        self.assertFalse(self.service.queue_running())
        self.assertEqual(self.service.approve_metadata_preview(p['id']), result)

    def test_stale_task_or_plex_value_rejects_without_any_queue_changes(self):
        p = self.preview({'studio': 'New'})
        self.plex.rows[0]['summary'] = 'Changed elsewhere'
        with self.assertRaisesRegex(ValueError, 'changed after preview'):
            self.service.approve_metadata_preview(p['id'])
        self.assertEqual(self.service.get_task(self.task['id'])['status'], 'recommendation')
        self.plex.rows[0]['summary'] = 'Before'
        self.service.edit_task(self.task['id'], {'changes': {'studio': 'Different draft'}}, 1)
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.service.approve_metadata_preview(p['id'])
        self.assertEqual(self.plex.writes, [])

    def test_empty_and_unsupported_fields_rejected(self):
        for fields in (
            {},
            {'label': []},
            {'genre': {'mode': 'clear', 'values': ['wrong']}},
            {'genre': {'mode': 'unknown', 'values': []}},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.preview(fields)
        self.assertEqual(self.plex.writes, [])

    def test_list_add_replace_clear_and_noop(self):
        self.plex.rows[0]['Genre'] = [{'tag': 'Original'}]
        self.assertEqual(
            self.preview({'genre': {'mode': 'add', 'values': ['new']}})['rows'][0]['changes']['genre'],
            ['Original', 'new'],
        )
        self.assertEqual(
            self.preview({'genre': {'mode': 'replace', 'values': ['new']}})['rows'][0]['changes']['genre'], ['new']
        )
        self.assertEqual(self.preview({'genre': {'mode': 'clear', 'values': []}})['rows'][0]['changes']['genre'], [])
        p = self.preview({'genre': {'mode': 'replace', 'values': ['original']}})
        self.assertEqual(p['rows'][0]['changes'], {})
        self.assertEqual(self.service.approve_metadata_preview(p['id'])['tasks'], [])

    def test_cast_is_explicit_and_existing_portrait_is_preserved(self):
        self.plex.rows[0]['Role'] = [
            {'tag': 'Person', 'role': 'Original role', 'thumb': '/library/metadata/10/actor.jpg'}
        ]
        p = self.preview({'studio': 'New'})
        self.assertNotIn('cast', p['rows'][0]['changes'])
        p = self.preview({'cast': [{'name': 'Person', 'role': 'New role'}]})
        self.assertEqual(
            p['rows'][0]['changes']['cast'],
            [{'name': 'Person', 'role': 'New role', 'thumb': '/library/metadata/10/actor.jpg'}],
        )
        self.assertEqual(self.preview({'cast': []})['rows'][0]['changes']['cast'], [])
        self.assertEqual(self.plex.writes, [])

    def test_multi_folder_selection_and_atomic_approval(self):
        other = copy.deepcopy(self.asset)
        other.update(id='b' * 24, rating_key='11', title='Other', plex_path='/plex/Other/other.mp4')
        other_item = copy.deepcopy(self.plex.rows[0])
        other_item.update(ratingKey='11', title='Other')
        self.plex.item = lambda key: copy.deepcopy(other_item if key == '11' else self.plex.rows[0])
        with self.store.transaction():
            self.store.put('assets', other['id'], other)
            task = self.service.task(other, dict(kind='metadata', reason='Missing description'))
        refs = [{'id': t['id'], 'version': t['version']} for t in (self.task, task)]
        p = self.service.metadata_preview(refs, {'collection': {'mode': 'add', 'values': ['Summer']}})
        self.assertEqual(len(p['rows']), 2)
        self.service.edit_task(task['id'], {'changes': {'title': 'changed draft'}}, task['version'])
        with self.assertRaises(ValueError):
            self.service.approve_metadata_preview(p['id'])
        self.assertFalse(any(t['status'] == 'queued' for t in self.store.all('tasks')))
        self.assertEqual(self.plex.writes, [])

    def test_legacy_running_queued_history_plans_are_not_migrated(self):
        for status in ('queued', 'running', 'applied', 'cancelled', 'blocked'):
            task = dict(self.task, status=status, plan={'changes': {'summary': 'An approved value'}}, approval=1)
            with self.store.transaction():
                self.store.put('tasks', task['id'], task)
                self.store.db.execute("DELETE FROM settings WHERE id='metadata-artwork-split-v1'")
            before = self.service.get_task(task['id'])
            self.service.split_metadata_findings()
            self.assertEqual(self.service.get_task(task['id']), before)
        art = [t for t in self.store.all('tasks') if t['kind'] == 'artwork']
        self.assertEqual(len(art), 1)
        self.assertTrue(art[0]['evidence']['discovery'])

    def test_scan_separates_missing_description_and_cover_and_resolves_only_discovery(self):
        self.service.save_library_overrides(
            self.lib['id'],
            0,
            {
                'metadata': {'required': ['summary']},
                'artwork': {'enabled': True},
            },
        )
        self.plex.rows[0]['summary'] = ''
        self.plex.rows[0].pop('thumb', None)
        self.plex.items = lambda library: iter([self.plex.item('10')])
        self.service.scan_status[self.lib['id']] = {'count': 0}
        technical = dict(
            width=1920, height=1080, codec='h264', duration_seconds=100, size_bytes=100, bitrate=8, streams=[]
        )
        with patch('curator.service.tools.probe', return_value=technical):
            self.service._scan(self.lib)
        findings = [t for t in self.store.all('tasks') if t['kind'] in {'metadata', 'artwork'}]
        self.assertEqual({t['kind'] for t in findings}, {'metadata', 'artwork'})
        for _ in range(2):
            with patch('curator.service.tools.probe', return_value=technical):
                self.service._scan(self.lib)
        self.assertEqual(len([t for t in self.store.all('tasks') if t['kind'] == 'artwork']), 1)
        self.plex.rows[0].update(summary='Now described', thumb='/poster')
        with patch('curator.service.tools.probe', return_value=technical):
            self.service._scan(self.lib)
        self.assertTrue(
            all(t['status'] == 'resolved' for t in self.store.all('tasks') if t['kind'] in {'metadata', 'artwork'})
        )
