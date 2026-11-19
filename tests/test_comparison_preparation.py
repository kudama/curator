"""Synthetic comparison readiness/race checks; no decoder, Plex or real media."""

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from curator.service import Service
from curator.store import Store


class ComparisonPreparation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.addCleanup(self.store.close)
        self.service = Service(self.store)
        self.task = dict(
            id='a' * 24,
            asset='asset',
            library='one',
            kind='optimize',
            status='awaiting_review',
            version=1,
            source={'size': 1},
            source_hash='original',
            output_hash='processed',
            output='/synthetic/output.mp4',
            result={'duration_seconds': 100},
            comparison_loaded=True,
        )
        with self.store.transaction():
            self.store.put('tasks', self.task['id'], self.task)
        self.asset = dict(local_path='/synthetic/input.mp4', technical={'duration_seconds': 100})
        self.asset_patch = patch.object(self.service, 'asset', return_value=self.asset).start()
        self.addCleanup(patch.stopall)
        self.samples = [{'file': str(i) + '.jpg'} for i in range(4)]

    def current(self):
        return self.service.get_task(self.task['id'])

    def test_ready_requires_all_four_images_on_both_sides(self):
        def complete(*args):
            self.assertFalse(self.current()['comparison_loaded'])
            return self.samples

        with patch('curator.service.tools.frames', side_effect=complete) as frames:
            self.assertEqual(self.service.comparison(self.task['id']), {'ready': True})
        self.assertEqual(frames.call_count, 2)
        self.assertTrue(self.current()['comparison_loaded'])
        self.assertEqual(self.current()['status'], 'awaiting_review')

    def test_partial_original_or_processed_images_clear_readiness_and_offer_specific_error(self):
        for side in ('Original', 'Processed'):
            with self.subTest(side=side):
                with self.store.transaction():
                    self.store.put('tasks', self.task['id'], self.task)
                results = [self.samples[:3]] if side == 'Original' else [self.samples, self.samples[:3]]
                with (
                    patch('curator.service.tools.frames', side_effect=results),
                    self.assertRaisesRegex(ValueError, side + ' comparison is incomplete'),
                ):
                    self.service.comparison(self.task['id'])
                self.assertFalse(self.current()['comparison_loaded'])
                self.assertEqual(self.current()['status'], 'awaiting_review')

    def test_late_preparation_does_not_overwrite_a_new_task_state_or_identity(self):
        for change in (
            {'status': 'publishing'},
            {'status': 'recommendation', 'version': 2},
            {'output': '/synthetic/new.mp4'},
            {'deleted': True},
        ):
            with self.subTest(change=change):
                with self.store.transaction():
                    self.store.put('tasks', self.task['id'], self.task)

                def changed(*args):
                    with self.store.transaction():
                        current = self.current()
                        current.update(change)
                        self.store.put('tasks', current['id'], current)
                    return self.samples

                with (
                    patch('curator.service.tools.frames', side_effect=changed),
                    self.assertRaisesRegex(ValueError, 'Review changed'),
                ):
                    self.service.comparison(self.task['id'])
                for key, value in change.items():
                    self.assertEqual(self.current()[key], value)
                self.assertFalse(self.current()['comparison_loaded'])

    def test_simultaneous_retries_serialize_extraction(self):
        entered = threading.Event()
        second_attempt = threading.Event()
        release = threading.Event()
        guard = threading.Lock()
        active = 0
        maximum = 0
        errors = []
        attempts = 0
        lock = self.service.operation_lock(self.task['id'])

        def observed_lock(key):
            nonlocal attempts
            with guard:
                attempts += 1
                if attempts == 2:
                    second_attempt.set()
            return lock

        def frames(*args):
            nonlocal active, maximum
            with guard:
                active += 1
                maximum = max(maximum, active)
            entered.set()
            release.wait(3)
            with guard:
                active -= 1
            return self.samples

        def prepare():
            try:
                self.service.comparison(self.task['id'])
            except Exception as error:
                errors.append(error)

        with (
            patch('curator.service.tools.frames', side_effect=frames),
            patch.object(self.service, 'operation_lock', side_effect=observed_lock),
        ):
            first = threading.Thread(target=prepare)
            second = threading.Thread(target=prepare)
            try:
                first.start()
                self.assertTrue(entered.wait(3))
                second.start()
                self.assertTrue(second_attempt.wait(3))
                release.set()
            finally:
                release.set()
                first.join(3)
                if second.ident is not None:
                    second.join(3)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(maximum, 1)
        self.assertTrue(self.current()['comparison_loaded'])
