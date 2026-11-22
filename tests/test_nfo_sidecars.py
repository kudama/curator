import base64
import errno
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from curator.errors import UserError
from curator.exclusive_install import install_exclusive_at
from curator.nfo_sidecars import image_info, image_name, plan_sidecar, write_sidecar
from test_artwork_managers import png


class Sidecars(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name).resolve()
        self.target = self.folder / 'movie.nfo'

    def test_preview_read_only_create_and_idempotence(self):
        plan = plan_sidecar(self.folder, 'movie.nfo', b'new')
        self.assertEqual(list(self.folder.iterdir()), [])
        self.assertEqual(write_sidecar(plan, b'new')['state'], 'created')
        self.assertEqual(self.target.read_bytes(), b'new')
        self.assertEqual(write_sidecar(plan_sidecar(self.folder, 'movie.nfo', b'new'), b'new')['state'], 'unchanged')
        self.assertEqual(write_sidecar(plan_sidecar(self.folder, 'movie.nfo', b'other'), b'other')['state'], 'kept')
        self.assertEqual(self.target.read_bytes(), b'new')

    def test_update_retains_exact_reviewed_bytes(self):
        self.target.write_bytes(b'original')
        plan = plan_sidecar(self.folder, 'movie.nfo', b'new', update=True)
        result = write_sidecar(plan, b'new')
        self.assertEqual(result['state'], 'updated')
        self.assertEqual(self.target.read_bytes(), b'new')
        self.assertEqual((self.folder / result['retention'] / 'reviewed-original').read_bytes(), b'original')
        self.assertEqual((self.folder / result['retention'] / 'observed-original').read_bytes(), b'original')

    def test_stale_destination_and_source_refused(self):
        plan = plan_sidecar(self.folder, 'movie.nfo', b'new')
        self.target.write_bytes(b'foreign')
        with self.assertRaises(UserError):
            write_sidecar(plan, b'new')
        self.assertEqual(self.target.read_bytes(), b'foreign')
        with self.assertRaises(UserError):
            write_sidecar(plan, b'different')

    def test_source_change_before_install_leaves_no_sidecar(self):
        plan = plan_sidecar(self.folder, 'movie.nfo', b'new')

        def verify():
            if list(self.folder.iterdir()):
                raise UserError('source changed')

        with self.assertRaisesRegex(UserError, 'source changed'):
            write_sidecar(plan, b'new', verify)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_competing_create_at_atomic_install_is_never_overwritten(self):
        plan = plan_sidecar(self.folder, 'movie.nfo', b'new')

        def race(fd, src, dst):
            self.target.write_bytes(b'foreign')
            return install_exclusive_at(fd, src, dst)

        with patch('curator.nfo_sidecars.install_exclusive_at', side_effect=race), self.assertRaises(UserError):
            write_sidecar(plan, b'new')
        self.assertEqual(self.target.read_bytes(), b'foreign')

    def test_competing_update_after_retention_preserves_both(self):
        self.target.write_bytes(b'original')
        plan = plan_sidecar(self.folder, 'movie.nfo', b'new', update=True)

        def race(fd, src, dst):
            self.target.write_bytes(b'foreign')
            return install_exclusive_at(fd, src, dst)

        with patch('curator.nfo_sidecars.install_exclusive_at', side_effect=race), self.assertRaises(UserError):
            write_sidecar(plan, b'new')
        self.assertEqual(self.target.read_bytes(), b'foreign')
        self.assertEqual((self.folder / plan['retention'] / 'reviewed-original').read_bytes(), b'original')

    def test_unsupported_no_overwrite_filesystem_fails_explicitly_without_fallback(self):
        plan = plan_sidecar(self.folder, 'movie.nfo', b'new')
        with patch('curator.nfo_sidecars.install_exclusive_at', side_effect=OSError(errno.ENOTSUP, 'unsupported')):
            with self.assertRaisesRegex(UserError, 'filesystem does not support safe no-overwrite'):
                write_sidecar(plan, b'new')
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_directory_swap_inside_install_refuses_success_and_leaves_new_folder_untouched(self):
        sub = self.folder / 'title'
        sub.mkdir()
        plan = plan_sidecar(sub, 'movie.nfo', b'new')
        retained = self.folder / 'previous'

        def swap(fd, source, destination):
            sub.rename(retained)
            sub.mkdir()
            return install_exclusive_at(fd, source, destination)

        with patch('curator.nfo_sidecars.install_exclusive_at', side_effect=swap):
            with self.assertRaisesRegex(UserError, 'pathname changed'):
                write_sidecar(plan, b'new')
        self.assertEqual(list(sub.iterdir()), [])
        self.assertEqual((retained / 'movie.nfo').read_bytes(), b'new')

    def test_directory_swap_before_unchanged_receipt_is_refused(self):
        sub = self.folder / 'title'
        sub.mkdir()
        (sub / 'movie.nfo').write_bytes(b'existing')
        plan = plan_sidecar(sub, 'movie.nfo', b'existing')

        def swap():
            sub.rename(self.folder / 'previous')
            sub.mkdir()

        with self.assertRaisesRegex(UserError, 'pathname changed'):
            write_sidecar(plan, b'existing', swap)
        self.assertEqual(list(sub.iterdir()), [])
        self.assertEqual((self.folder / 'previous' / 'movie.nfo').read_bytes(), b'existing')

    def test_symlinks_case_collisions_and_traversal_rejected(self):
        external = self.folder / 'other'
        external.write_bytes(b'untouched')
        self.target.symlink_to(external)
        with self.assertRaises(UserError):
            plan_sidecar(self.folder, 'movie.nfo', b'new')
        self.target.unlink()
        (self.folder / 'MOVIE.NFO').write_bytes(b'foreign')
        with self.assertRaises(UserError):
            plan_sidecar(self.folder, 'movie.nfo', b'new')
        with self.assertRaises(UserError):
            plan_sidecar(self.folder, '../other', b'new')
        self.assertEqual(external.read_bytes(), b'untouched')

    def test_directory_replacement_refused(self):
        sub = self.folder / 'title'
        sub.mkdir()
        plan = plan_sidecar(sub, 'movie.nfo', b'new')
        sub.rename(self.folder / 'previous')
        sub.mkdir()
        with self.assertRaises(UserError):
            write_sidecar(plan, b'new')
        self.assertEqual(list(sub.iterdir()), [])

    def test_format_names_match_bytes_and_corrupt_art_rejected(self):
        data = base64.b64decode(png(16, 9))
        info = image_info(data)
        self.assertEqual(image_name('cover', info), 'poster.png')
        self.assertEqual(image_name('background', info), 'background.png')
        self.assertEqual(image_name('square', info), 'square.png')
        self.assertEqual(image_name('logo', info), 'logo.png')
        self.assertEqual((info['width'], info['height']), (16, 9))
        for bad in (b'html', data[:-4], data[:30] + b'x' + data[31:], b'\xff\xd8\xff\xff\xff\xff'):
            with self.subTest(data=bad[:10]), self.assertRaises(UserError):
                image_info(bad)
        with self.assertRaises(UserError):
            image_name('logo', dict(extension='jpg'))
