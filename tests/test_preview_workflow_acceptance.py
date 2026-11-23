"""Integrated synthetic acceptance: batch rendering never implies publication."""

import copy
from pathlib import Path
import unittest
import uuid
from curator import tools
from curator.errors import UserError
from curator.preview_cards import DEFAULTS
from test_artwork_managers import png
import test_preview_render


class PreviewWorkflowAcceptance(unittest.TestCase):
    setUp = test_preview_render.PreviewMedia.setUp
    source = test_preview_render.PreviewMedia.source

    def test_real_batch_cards_review_selection_and_separate_publication(self):
        folder = self.media / 'Film'
        folder.mkdir()
        self.file = self.file.rename(folder / 'film.mkv')
        self.plex.rows[0]['Media'][0]['Part'][0]['file'] = '/plex/Film/film.mkv'
        self.asset.update(local_path=str(self.file.resolve()), plex_path='/plex/Film/film.mkv')
        self.source()
        source_hash = tools.digest(self.file)
        previous = folder / 'Previous-trailer.mp4'
        previous.write_bytes(b'retained prior trailer')
        other_folder = self.media / 'Other'
        other_folder.mkdir()
        other = other_folder / 'other.mkv'
        other.write_bytes(self.file.read_bytes())
        second = {
            **copy.deepcopy(self.asset),
            'id': 'b' * 24,
            'title': 'Other',
            'rating_key': '20',
            'local_path': str(other.resolve()),
            'plex_path': '/plex/Other/other.mkv',
            'fingerprint': tools.fingerprint(other),
        }
        with self.store.transaction():
            self.store.db.execute('DELETE FROM tasks')
            self.store.put('assets', second['id'], second)
            self.store.put('settings', self.service.pause_key(None, 'optimize'), True)
            self.store.put('settings', self.service.pause_key(None, 'file_operations'), True)
        intro = self.service.import_preview_card(dict(name='Synthetic intro', role='intro', image=png(160, 90)))
        outro = self.service.import_preview_card(dict(name='Synthetic outro', role='outro', image=png(90, 160)))
        values = {
            **DEFAULTS,
            'requested_duration_ms': 2000,
            'intro': dict(card=intro['id'], version=1),
            'outro': dict(card=outro['id'], version=1),
        }
        items = []
        for asset in [self.asset, second]:
            info = self.service.preview_info(asset['id'])
            items.append(
                dict(
                    asset=asset['id'],
                    asset_version=info['asset_version'],
                    start_ms=500,
                    audio_stream=info['default_audio'],
                )
            )
        batch = self.service.create_preview_batch(dict(items=items, values=values, defaults_revision=1))
        self.assertEqual(batch['count'], 2)
        self.assertEqual(batch['ready_count'], 2)
        self.assertFalse(self.store.all('tasks'))
        self.assertFalse(self.service.file_jobs())
        self.assertEqual(batch['rows'][0]['settings']['timing']['start_ms'], 500)
        # A single stale source must not discard the other selected item's output.
        other.write_bytes(b'changed after exact batch review')
        key = uuid.uuid4().hex
        submitted = self.service.submit_preview_batch(batch['id'], key)
        self.assertEqual(submitted['outcome'], 'mixed')
        self.assertEqual(submitted['rows'][1]['status'], 'unavailable')
        self.assertEqual(len(self.store.all('tasks')), 1)
        job = submitted['rows'][0]['job']
        self.assertFalse(self.service.active)
        self.service._execute(job)  # Deliberately execute this disposable job, not its paused queue.
        task = self.service.get_task(job)
        self.assertEqual(task['status'], 'awaiting_review', task.get('error'))
        candidate = self.store.get('settings', 'preview-output:' + job)
        result = candidate['result']
        self.assertAlmostEqual(result['duration_seconds'], 7, delta=0.1)
        self.assertEqual((result['width'], result['height'], result['codec']), (320, 180, 'h264'))
        self.assertTrue(any(stream.get('codec_type') == 'audio' for stream in result['streams']))
        self.assertIsNone(self.service.preview_selection(self.asset['id'])['job'])
        self.assertFalse(self.service.file_jobs())
        selected = self.service.select_preview(job, task['version'], 0)
        self.assertEqual(selected['job'], job)
        self.assertFalse(self.service.file_jobs())
        publication = self.service.preview_publication_plan(job, self.service.get_task(job)['version'])
        self.assertFalse(self.service.file_jobs())
        approval = self.service.approve_preview_publication(publication['id'], uuid.uuid4().hex)
        self.assertTrue(approval['file_job'])
        self.assertTrue(self.service.file_queue_paused())
        self.assertFalse(self.service.file_workers)
        receipt = self.service.get_preview_publication(publication['id'])
        destination = Path(receipt['destination'])
        self.assertFalse(destination.exists())
        saved = self.service.execute_preview_publication(dict(publication=publication['id']))
        self.assertEqual((saved['status'], saved['association']), ('local_saved', 'pending'))
        self.assertEqual(tools.digest(destination), candidate['sha256'])
        self.assertEqual(tools.digest(self.file), source_hash)
        self.assertEqual(previous.read_bytes(), b'retained prior trailer')
        self.assertFalse(self.plex.writes)
        self.assertEqual(self.service.preview_selection(self.asset['id']), selected)
        self.assertEqual(self.service.public_preview_batch(self.service.preview_batch(batch['id']))['outcome'], 'mixed')
        with self.assertRaises(UserError):
            self.service.execute_preview_publication(dict(publication=publication['id']))
        self.assertEqual(len(self.store.all('tasks')), 1)
