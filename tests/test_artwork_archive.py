import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import test_curator
from test_artwork_managers import png
from curator.artwork_archive import archive_root, retain


class ArtworkArchiveTests(unittest.TestCase):
    setUp = test_curator.Workflows.setUp
    tearDown = test_curator.Workflows.tearDown

    def configure(self):
        root = Path(self.tmp.name) / 'artwork-archive'
        root.mkdir()
        self.service.save_config({'artwork_archive_path': str(root)})
        return root

    def draft(self):
        with patch.object(self.service, 'queue_artwork_archive'):
            return self.service.artwork_preview([self.asset['id']], 'cover', '2:3', {self.asset['id']: png(20, 30)})[
                'tasks'
            ][0]

    def test_archive_is_append_only_and_retries_are_idempotent(self):
        root = self.configure()
        task = self.draft()
        result = self.service.archive_artwork_task(task)
        target = root / result['directory']
        manifest = json.loads((target / result['manifest']).read_text())
        self.assertEqual(manifest['files']['candidate'], manifest['files']['source_image'])
        files = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
        self.assertEqual(len(files), 2)
        self.service.archive_artwork_task(task)
        self.assertEqual(files, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()})
        self.assertTrue((root / 'Cast').is_dir())
        self.assertTrue((root / 'Collections' / 'Logos').is_dir())
        self.assertFalse(self.plex.writes)
        self.assertEqual(len(self.service.get_task(task['id'])['archive_locations']), 1)

    def test_conflicting_file_or_symlink_is_never_overwritten(self):
        root = self.configure()
        target = root / 'existing'
        target.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'different data'):
            retain(target, b'change')
        link = root / 'link'
        link.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            retain(link, b'keep')
        self.assertEqual(target.read_bytes(), b'keep')
        (root / 'Movies').symlink_to(self.root)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.service.archive_artwork_task(self.draft())
        self.assertFalse(self.plex.writes)

    def test_changed_path_keeps_previous_archive_and_unavailable_path_blocks_publish(self):
        root = self.configure()
        task = self.draft()
        self.service.archive_artwork_task(task)
        original = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
        new = root.parent / 'other-archive'
        new.mkdir()
        self.service.save_config({'artwork_archive_path': str(new)})
        self.service.archive_artwork_task(task)
        self.assertEqual(original, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()})
        self.assertEqual(len(self.service.get_task(task['id'])['archive_locations']), 2)
        new.rename(root.parent / 'offline')
        with self.assertRaises(ValueError):
            self.service.publish_artwork(task, self.asset)
        self.assertFalse(self.plex.writes)

    def test_portraits_are_flat_and_path_configuration_does_not_copy(self):
        root = self.configure()
        self.assertEqual(list(root.iterdir()), [])
        with patch.object(self.service, 'queue_portrait_archive'):
            result = self.service.create_cast_profile('Test Person', png(10, 10))
        self.service.archive_portrait(result['profile_id'], 1)
        files = list((root / 'Cast').iterdir())
        self.assertEqual(len(files), 2)
        self.assertTrue(all(p.is_file() for p in files))
        self.assertTrue(all(p.name.startswith('Test Person--') for p in files))
        with self.assertRaises(ValueError):
            archive_root('relative/path')

    def test_interrupted_copy_leaves_no_partial_final_file(self):
        root = self.configure()
        target = root / 'candidate.png'
        with patch('curator.artwork_archive.os.fsync', side_effect=OSError('Synthetic disk failure')):
            with self.assertRaises(OSError):
                retain(target, b'complete candidate')
        self.assertFalse(target.exists())
        self.assertEqual(list(root.iterdir()), [])
        retain(target, b'complete candidate')
        self.assertEqual(target.read_bytes(), b'complete candidate')
