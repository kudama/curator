import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from curator import tools


class FrameCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'input.mp4'
        self.source.write_bytes(b'input')
        self.folder = self.root / 'frames'
        self.runner = patch('curator.tools.subprocess.run', side_effect=self.fake_run).start()
        self.addCleanup(patch.stopall)
        patch('curator.tools.executable', return_value='ffmpeg').start()

    def fake_run(self, cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b'jpeg')
        return SimpleNamespace(returncode=0)

    def frames(self, path=None):
        return tools.frames(path or self.source, self.folder, {'duration_seconds': 100}, {})

    def test_cache_reuses_same_input(self):
        self.frames()
        self.frames()
        self.assertEqual(self.runner.call_count, 4)

    def test_different_path_with_same_identity_invalidates_cache(self):
        other = self.root / 'other.mp4'
        os.link(self.source, other)
        self.frames()
        self.frames(other)
        self.assertEqual(self.runner.call_count, 8)

    def test_changed_input_and_legacy_cache_regenerate(self):
        self.folder.mkdir()
        (self.folder / '0.jpg').write_bytes(b'stale')
        unrelated = self.folder / 'keep.jpg'
        unrelated.write_bytes(b'keep')
        self.frames()
        self.source.write_bytes(b'changed input')
        self.frames()
        self.assertEqual(self.runner.call_count, 8)
        self.assertEqual(unrelated.read_bytes(), b'keep')

    def test_symlink_is_rejected_without_changing_target(self):
        self.folder.mkdir()
        other = self.root / 'keep'
        other.write_bytes(b'keep')
        (self.folder / '0.jpg').symlink_to(other)
        with self.assertRaises(ValueError):
            self.frames()
        self.assertEqual(other.read_bytes(), b'keep')
        self.runner.assert_not_called()

    def test_partial_extraction_is_not_certified_or_reused(self):
        def partial(cmd, **kwargs):
            if Path(cmd[-1]).name == '1.jpg':
                return SimpleNamespace(returncode=1)
            return self.fake_run(cmd, **kwargs)

        self.runner.side_effect = partial
        self.assertEqual(len(self.frames()), 3)
        self.assertFalse((self.folder / '.manifest.json').exists())
        self.runner.side_effect = self.fake_run
        self.frames()
        self.assertEqual(self.runner.call_count, 8)
