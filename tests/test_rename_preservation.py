"""#70: curated Plex metadata and selected artwork survive a rename and a later Plex rematch.

Fake Plex only: synthetic files in a temporary folder and temporary state.
"""

import copy
import hashlib
import unittest
from unittest.mock import patch

from curator.plex import PlexError
import test_files
from test_files import media

PNG = b'\x89PNG\r\n\x1a\n' + b'synthetic poster'
JPEG = b'\xff\xd8\xff' + b'synthetic background'


class Preservation(unittest.TestCase):
    # Reuse the rename harness from test_files without re-running its tests.
    plan, run_task, tearDown = test_files.Plans.plan, test_files.Plans.run_task, test_files.Plans.tearDown

    def setUp(self):
        test_files.Plans.setUp(self)
        row = self.plex.rows['1']
        row.update(thumb='/library/metadata/1/thumb/1', art='/library/metadata/1/art/1')
        self.plex.images = {('1', 'cover'): PNG, ('1', 'background'): JPEG}

        def image(key, kind):
            data = self.plex.images.get((str(key), kind))
            if data is None:
                raise PlexError('HTTP 404')
            return data

        self.plex.image = image
        with self.store.transaction():
            asset = self.store.get('assets', self.assets[0]['id'])
            asset['item'] = copy.deepcopy(row)
            self.store.put('assets', asset['id'], asset)

    def scan(self):
        self.service.scan_status[self.library['id']] = {'running': True, 'count': 0}
        with patch('curator.service.tools.probe', return_value=media()):
            self.service._scan(self.library)
        self.assertIsNone(self.service.scan_status[self.library['id']].get('error'))

    def receipts(self):
        return self.store.where('settings', record_type='rename_receipt')

    def rename_and_rematch(self, new_key='100', images=None, **plex_changes):
        task = self.run_task(self.plan())
        self.assertEqual(task['status'], 'applied')
        self.plex.scan_folder(self.library, '/plex')  # Plex's own scheduled refresh, later.
        row = self.plex.rows.pop('1')
        row['ratingKey'] = new_key
        row.update(plex_changes)
        self.plex.rows[new_key] = row
        for (key, kind), data in list(self.plex.images.items()):
            if key == '1':
                self.plex.images[new_key, kind] = data
        for kind, data in (images or {}).items():
            self.plex.images[new_key, kind] = data
        self.scan()
        return task, self.receipts()[0]

    def test_capture_is_private_fresh_and_complete_before_any_move(self):
        self.plex.rows['1']['summary'] = 'Edited in Plex after the last scan'
        task = self.run_task(self.plan())
        [receipt] = self.receipts()
        self.assertEqual(receipt['status'], 'moved')
        self.assertEqual(task['rename_receipt'], receipt['receipt'])
        self.assertEqual(receipt['metadata']['summary'], 'Edited in Plex after the last scan')
        self.assertEqual(set(receipt['artwork']), {'cover', 'background'})
        folder = self.store.root / 'rename-receipts' / receipt['receipt']
        self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
        for kind, entry in receipt['artwork'].items():
            path = folder / entry['file']
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry['sha256'])
        self.assertEqual(receipt['artwork']['cover']['file'], 'cover.png')
        self.assertEqual(receipt['artwork']['background']['file'], 'background.jpg')
        self.assertTrue(receipt['destination_fingerprint'])

    def test_no_capture_means_no_move(self):
        task = self.plan()
        source = self.assets[0]['local_path']
        for failure in ('item', 'image'):
            with self.subTest(failure=failure):
                patched = (
                    patch.object(self.plex, 'item', side_effect=PlexError('Plex request failed'))
                    if failure == 'item'
                    else patch.object(self.plex, 'image', side_effect=PlexError('HTTP 500'))
                )
                with patched:
                    result = self.run_task(self.service.get_task(task['id']))
                self.assertNotEqual(result['status'], 'applied')
                self.assertIn('rename not started', result['error'])
                self.assertFalse(result.get('rename_started'))
                self.assertTrue((self.folder / 'Trip - Part 1.mkv').exists())
                self.assertEqual(self.store.get('assets', self.assets[0]['id'])['local_path'], source)
                self.assertEqual(self.receipts(), [])
                folder = self.store.root / 'rename-receipts'
                self.assertEqual(list(folder.iterdir()) if folder.exists() else [], [])

    def test_rematch_that_lost_metadata_proposes_a_reviewed_restore_without_writing_plex(self):
        task, receipt = self.rename_and_rematch(summary='', Genre=[], Role=[])
        self.assertEqual(receipt['status'], 'review')
        outcome = receipt['outcome']
        self.assertTrue(outcome['rematched'])
        self.assertEqual(outcome['rating_key_after'], '100')
        self.assertEqual(sorted(outcome['differs']), ['cast', 'genre', 'summary'])
        self.assertIn('title', outcome['retained'])
        self.assertEqual(outcome['restore']['state'], 'proposed')
        restore = self.service.get_task(outcome['restore']['task'])
        self.assertEqual(restore['status'], 'recommendation')
        self.assertEqual(
            restore['plan']['changes'],
            {'summary': 'Description', 'genre': ['Travel'], 'cast': [{'name': 'Person', 'role': 'Self', 'thumb': ''}]},
        )
        self.assertEqual(self.plex.rows['100']['summary'], '')  # Nothing written to Plex.
        # Stable identity: the same Curator asset now follows the new Plex key.
        asset = self.store.get('assets', self.assets[0]['id'])
        self.assertEqual(asset['rating_key'], '100')
        self.assertEqual(restore['asset'], asset['id'])
        [event] = self.store.curator_history(level='warning')
        self.assertIn('summary', event['message'])
        # Recovery through the existing metadata workflow restores exactly the captured values.
        self.service.apply_metadata(restore['id'], restore['version'], restore['plan']['changes'])
        self.assertEqual(self.plex.rows['100']['summary'], 'Description')
        self.assertEqual(self.plex.rows['100']['Genre'], [{'tag': 'Travel'}])

    def test_retained_metadata_and_artwork_need_nothing(self):
        task, receipt = self.rename_and_rematch()
        self.assertEqual(receipt['status'], 'reconciled')
        self.assertEqual(receipt['outcome']['differs'], [])
        self.assertEqual(receipt['outcome']['artwork'], {'cover': 'retained', 'background': 'retained'})
        self.assertNotIn('restore', receipt['outcome'])
        self.assertEqual(self.store.curator_history(level='warning'), [])
        # Reconciled receipts are not processed again by later scans.
        self.scan()
        self.assertEqual(self.receipts()[0]['settled_at'], receipt['settled_at'])

    def test_replaced_artwork_is_reported_and_the_original_bytes_are_kept(self):
        task, receipt = self.rename_and_rematch(images={'cover': b'\xff\xd8\xff' + b'agent default poster'})
        self.assertEqual(receipt['status'], 'review')
        self.assertEqual(receipt['outcome']['artwork']['cover'], 'changed')
        self.assertEqual(self.service.retained_rename_artwork(receipt, 'cover'), PNG)
        tampered = self.store.root / 'rename-receipts' / receipt['receipt'] / 'cover.png'
        tampered.write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            self.service.retained_rename_artwork(receipt, 'cover')

    def test_newer_curator_edits_are_never_replaced(self):
        task = self.run_task(self.plan())
        [receipt] = self.receipts()
        with self.store.transaction():
            self.store.put(
                'tasks',
                'later-edit',
                dict(
                    id='later-edit',
                    asset=self.assets[0]['id'],
                    library=self.library['id'],
                    kind='metadata',
                    status='applied',
                    version=1,
                    plan={'changes': {'summary': 'Newer description'}},
                    updated='9999-01-01T00:00:00+00:00',
                ),
            )
        self.plex.scan_folder(self.library, '/plex')
        self.plex.rows['1'].update(summary='Newer description', tagline='')
        self.scan()
        outcome = self.receipts()[0]['outcome']
        self.assertEqual(outcome['superseded'], ['summary'])
        self.assertEqual(outcome['differs'], ['tagline'])
        restore = self.service.get_task(outcome['restore']['task'])
        self.assertEqual(restore['plan']['changes'], {'tagline': 'Tagline'})

    def test_open_metadata_work_is_a_conflict_not_overwritten(self):
        task = self.run_task(self.plan())
        metadata = self.service.metadata_task(self.assets[0]['id'])
        with self.store.transaction():
            metadata.update(plan={'changes': {'summary': 'Operator draft'}}, status='recommendation')
            self.store.put('tasks', metadata['id'], metadata)
        self.plex.scan_folder(self.library, '/plex')
        self.plex.rows['1']['summary'] = ''
        self.scan()
        outcome = self.receipts()[0]['outcome']
        self.assertEqual(outcome['restore']['state'], 'conflict')
        self.assertEqual(self.service.get_task(metadata['id'])['plan']['changes'], {'summary': 'Operator draft'})

    def test_rolled_back_rename_is_void_and_never_reconciled(self):
        task = self.plan()
        self.service.action(task['id'], 'queue', task['version'])
        # The source changes after approval and capture, before it moves: the rename stops and rolls back.
        real_capture = self.service.capture_rename_receipt

        def capture_then_change(*args):
            receipt = real_capture(*args)
            (self.folder / 'Trip - Part 1.mkv').write_bytes(b'changed before the move')
            return receipt

        with patch.object(self.service, 'capture_rename_receipt', side_effect=capture_then_change):
            self.service._execute(task['id'])
        result = self.service.get_task(task['id'])
        self.assertNotEqual(result['status'], 'applied')
        [receipt] = self.receipts()
        self.assertEqual(receipt['status'], 'void')
        self.scan()
        self.assertEqual(self.receipts()[0]['status'], 'void')

    def test_changed_destination_file_blocks_reconciliation(self):
        self.run_task(self.plan())
        self.plex.scan_folder(self.library, '/plex')
        with self.store.transaction():
            [receipt] = self.receipts()
            receipt['destination_fingerprint'] = {'size': 1, 'modified': 1}
            self.store.put('settings', receipt['id'], receipt)
        self.scan()
        receipt = self.receipts()[0]
        self.assertEqual(receipt['status'], 'blocked')
        self.assertIn('changed', receipt['reason'])
        self.assertNotIn('outcome', receipt)
