"""Immutable trailer cards survive replacement/hiding and concurrent settings edits."""

import base64
import concurrent.futures
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from curator.errors import UserError
from curator.service import Service
from curator.store import Store
from test_artwork_managers import png


class PreviewCards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'state')
        self.addCleanup(self.store.close)
        self.service = Service(self.store)

    def card(self, role='intro', **changes):
        return self.service.import_preview_card(dict(name='Family', role=role, image=png(32, 18), **changes))

    def test_import_replacement_retains_exact_old_version_after_hide(self):
        first = self.card()
        old = self.service.preview_card_image(first['id'], 1)
        second = self.service.import_preview_card(
            dict(id=first['id'], revision=1, name='Family new', role='intro', image=png(64, 36))
        )
        self.assertEqual(second['id'], first['id'])
        self.assertEqual(second['revision'], 2)
        self.assertNotEqual(first['image']['sha256'], second['image']['sha256'])
        self.service.hide_preview_card(first['id'], 2)
        self.assertEqual(self.service.preview_cards()['cards'], [])
        self.assertEqual(self.service.preview_card_image(first['id'], 1), old)
        self.assertEqual(first['image']['sha256'], hashlib.sha256(old).hexdigest())
        path = self.service.preview_card_path(first['id'], 1)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_invalid_png_and_stale_replacement_do_not_write(self):
        for image in ('bad', base64.b64encode(b'not PNG').decode(), png(4097, 1)):
            with self.subTest(image=image[:20]), self.assertRaises(UserError):
                self.service.import_preview_card(dict(name='Bad', role='intro', image=image))
        self.assertFalse((self.store.root / 'preview-cards').exists())
        first = self.card()
        with self.assertRaises(UserError):
            self.service.import_preview_card(
                dict(id=first['id'], revision=0, name='Bad', role='intro', image=png(8, 8))
            )
        self.assertEqual(len(list((self.store.root / 'preview-cards').rglob('*.png'))), 1)

    def test_concurrent_replacement_only_one_current_revision_wins(self):
        first = self.card()

        def replace():
            try:
                return self.service.import_preview_card(
                    dict(id=first['id'], revision=1, name='Updated', role='intro', image=png(40, 30))
                )['revision']
            except UserError:
                return 'stale'

        with concurrent.futures.ThreadPoolExecutor(2) as executor:
            results = list(executor.map(lambda _: replace(), range(2)))
        self.assertCountEqual(results, [2, 'stale'])
        self.assertEqual(len(list((self.store.root / 'preview-cards').rglob('*.png'))), 2)

    def test_defaults_noop_reset_stale_save_and_role_guard(self):
        first = self.card()
        original = self.service.preview_defaults()
        count = self.store.db.execute('SELECT count(*) FROM events').fetchone()[0]
        self.assertEqual(self.service.save_preview_defaults(1, {}), original)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM events').fetchone()[0], count)
        saved = self.service.save_preview_defaults(1, {'intro': dict(card=first['id'], version=1)})
        self.assertEqual(saved['revision'], 2)
        self.assertEqual(saved['values']['outro'], None)
        with self.assertRaises(UserError):
            self.service.save_preview_defaults(1, {'crossfade_ms': 200})
        with self.assertRaises(UserError):
            self.service.save_preview_defaults(2, {'outro': dict(card=first['id'], version=1)})
        with self.assertRaises(UserError):
            self.service.save_preview_defaults(2, {'intro_duration_ms': 500})
        with self.assertRaises(UserError):
            self.service.save_preview_defaults(2, {'audio_fade_ms': True})
        self.assertEqual(self.service.preview_defaults(), saved)
        self.service.hide_preview_card(first['id'], 1)
        self.assertEqual(self.service.preview_defaults(), saved)
        with self.assertRaises(UserError):
            self.service.save_preview_defaults(2, {'crossfade_ms': 100})
        self.service.save_preview_defaults(2, {'intro': None})

    def test_changed_missing_and_symlink_card_bytes_are_not_adopted(self):
        first = self.card()
        path = self.service.preview_card_path(first['id'], 1)
        path.write_bytes(base64.b64decode(png(8, 8)))
        with self.assertRaises(UserError):
            self.service.preview_card_image(first['id'], 1)
        path.unlink()
        with self.assertRaises(UserError):
            self.service.preview_card_image(first['id'], 1)
        path.symlink_to(Path(self.temp.name) / 'outside.png')
        with self.assertRaises(UserError):
            self.service.preview_card_image(first['id'], 1)

    def test_failed_file_write_does_not_advertise_card(self):
        with patch('curator.preview_cards.os.open', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.card()
        self.assertEqual(self.service.preview_cards()['cards'], [])
