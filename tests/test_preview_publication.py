"""Synthetic trailer publication preserves media, trailers and queue controls."""

import concurrent.futures
from pathlib import Path
from unittest.mock import patch
import uuid
from curator import tools
from curator.errors import UserError
import test_preview_review


import unittest


class TrailerPublication(unittest.TestCase):
    candidate = test_preview_review.PreviewReview.candidate
    plan = test_preview_review.PreviewReview.plan
    tearDown = test_preview_review.PreviewReview.tearDown

    # Reuse the synthetic candidate builder without inheriting unrelated checks.
    def setUp(self):
        test_preview_review.PreviewReview.setUp(self)
        folder = self.media / 'Film'
        folder.mkdir()
        self.file = self.file.rename(folder / 'film.mkv')
        self.plex.rows[0]['Media'][0]['Part'][0]['file'] = '/plex/Film/film.mkv'
        self.asset.update(
            local_path=str(self.file.resolve()),
            plex_path='/plex/Film/film.mkv',
            fingerprint=tools.fingerprint(self.file),
        )
        with self.store.transaction():
            self.store.put('assets', self.asset['id'], self.asset)
            self.store.put('settings', self.service.pause_key(None, 'file_operations'), True)

    def publication(self):
        task, path = self.candidate()
        plan = self.service.preview_publication_plan(task['id'], task['version'])
        return task, path, plan

    def test_separate_approval_pause_copy_retention_and_idempotence(self):
        old = self.file.with_name('Old-trailer.mp4')
        old.write_bytes(b'old trailer')
        task, candidate, plan = self.publication()
        self.assertFalse(self.service.file_jobs())
        request = uuid.uuid4().hex
        first = self.service.approve_preview_publication(plan['id'], request)
        again = self.service.approve_preview_publication(plan['id'], request)
        self.assertEqual(first['file_job'], again['file_job'])
        self.assertEqual(len(self.service.file_jobs()), 1)
        self.assertTrue(self.service.file_queue_paused())
        self.assertFalse(self.service.file_workers)
        record = self.service.get_preview_publication(plan['id'])
        self.assertFalse(Path(record['destination']).exists())
        result = self.service.execute_preview_publication(dict(publication=plan['id']))
        self.assertEqual(result['status'], 'local_saved')
        self.assertEqual(result['association'], 'pending')
        self.assertEqual(Path(record['destination']).read_bytes(), candidate.read_bytes())
        self.assertEqual(self.file.read_bytes(), b'original-video')
        self.assertEqual(old.read_bytes(), b'old trailer')
        self.assertIsNone(self.service.preview_selection(task['asset'])['job'])
        self.assertFalse(self.plex.writes)
        with self.assertRaises(UserError):
            self.service.execute_preview_publication(dict(publication=plan['id']))
        self.assertNotIn(str(self.root), str(result))

    def test_collision_after_approval_and_dangling_symlink_never_overwritten(self):
        _, _, plan = self.publication()
        self.service.approve_preview_publication(plan['id'], uuid.uuid4().hex)
        target = Path(self.service.get_preview_publication(plan['id'])['destination'])
        target.symlink_to(self.root / 'absent')
        with self.assertRaises(UserError):
            self.service.execute_preview_publication(dict(publication=plan['id']))
        self.assertTrue(target.is_symlink())
        self.assertFalse((self.root / 'absent').exists())

    def test_stale_source_candidate_and_edition_refused(self):
        for change in ('source', 'candidate', 'edition'):
            with self.subTest(change=change):
                _, candidate, plan = self.publication()
                if change == 'source':
                    self.file.write_bytes(b'changed')
                elif change == 'candidate':
                    candidate.write_bytes(b'changed')
                else:
                    self.plex.rows[0]['editionTitle'] = 'Other edition'
                with self.assertRaises(UserError):
                    self.service.approve_preview_publication(plan['id'], uuid.uuid4().hex)
                if change == 'source':
                    self.file.write_bytes(b'original-video')
                    self.asset['fingerprint'] = tools.fingerprint(self.file)
                    with self.store.transaction():
                        self.store.put('assets', self.asset['id'], self.asset)
                self.plex.rows[0].pop('editionTitle', None)

    def test_duplicate_concurrent_plans_only_one_owns_destination(self):
        task, _, plan = self.publication()
        second = self.service.preview_publication_plan(task['id'], task['version'])

        def submit(plan):
            try:
                self.service.approve_preview_publication(plan['id'], uuid.uuid4().hex)
                return 'queued'
            except UserError:
                return 'conflict'

        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            self.assertCountEqual(list(pool.map(submit, [plan, second])), ['queued', 'conflict'])
        self.assertEqual(len(self.service.file_jobs()), 1)

    def test_interrupted_install_is_retained_without_replay(self):
        _, _, plan = self.publication()
        self.service.approve_preview_publication(plan['id'], uuid.uuid4().hex)
        with patch('curator.preview_publication.install_exclusive', side_effect=OSError('disconnected')):
            with self.assertRaises(OSError):
                self.service.execute_preview_publication(dict(publication=plan['id']))
        record = self.service.get_preview_publication(plan['id'])
        self.assertEqual(record['status'], 'attempted')
        self.assertTrue(Path(record['staging']).is_file())
        self.service.recover_file_jobs()
        self.assertEqual(self.service.file_jobs()[0]['phase'], 'interrupted')
        with self.assertRaises(UserError):
            self.service.execute_preview_publication(dict(publication=plan['id']))

    def test_ambiguous_movie_folder_and_multiple_parts_refused(self):
        task, _, _ = self.publication()
        sibling = self.file.with_name('Other.mkv')
        sibling.write_bytes(b'other movie')
        with self.assertRaises(UserError):
            self.service.preview_publication_plan(task['id'], 1)
        sibling.unlink()
        self.plex.rows[0]['Media'].append({'Part': [{'file': '/plex/Other.mkv'}]})
        with self.assertRaises(UserError):
            self.service.preview_publication_plan(task['id'], 1)

    def test_association_read_only_requires_exact_extra_path(self):
        _, _, plan = self.publication()
        self.service.approve_preview_publication(plan['id'], uuid.uuid4().hex)
        self.service.execute_preview_publication(dict(publication=plan['id']))
        self.plex.request = lambda *a, **kw: {'Metadata': [{'Extras': {'Metadata': []}}]}
        self.assertEqual(self.service.reconcile_preview_publication(plan['id'])['association'], 'pending')
        self.plex.request = lambda *a, **kw: {
            'Metadata': [
                {'Extras': {'Metadata': [dict(extraType=1, Media=[{'Part': [{'file': plan['destination']}]}])]}}
            ]
        }
        self.assertEqual(self.service.reconcile_preview_publication(plan['id'])['association'], 'verified')
        self.assertFalse(self.plex.writes)
