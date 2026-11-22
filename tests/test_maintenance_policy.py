from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

from curator.errors import UserError
from curator.maintenance_policy import rule_values, permitted, excluded, limits


def rule(**changes):
    base = dict(
        name='Synthetic arrivals',
        library='fixture:1',
        action='scan',
        roots=['/synthetic'],
        excluded_paths=['/synthetic/excluded'],
        excluded_assets=['excluded-id'],
        limits=dict(
            items_per_run=2,
            items_per_day=5,
            output_bytes_per_day=32 * 1024 * 1024,
            output_bytes_per_item=8 * 1024 * 1024,
            min_free_bytes=1024,
        ),
        timezone='America/Los_Angeles',
        windows=[dict(days=list(range(7)), start='00:00', end='24:00')],
        quiet=[],
        options=dict(
            cadence_minutes=60,
            inventory_limit=1000,
            page_size=100,
            request_timeout_seconds=10,
            scan_timeout_seconds=120,
            probe_timeout_seconds=30,
            response_limit_bytes=4 * 1024 * 1024,
            probe_output_bytes=4 * 1024 * 1024,
        ),
    )
    base.update(changes)
    return rule_values(base)


class Policy(unittest.TestCase):
    def test_unknown_actions_fields_and_unlimited_caps_fail_closed(self):
        for action in ('publish', 'metadata', 'mage', 'delete', 'nfo_export', 'process_all'):
            with self.subTest(action=action), self.assertRaises(UserError):
                rule(action=action)
        for value in (0, -1, float('inf'), True, '10'):
            cap = rule()['limits']
            cap['items_per_day'] = value
            with self.subTest(value=value), self.assertRaises(UserError):
                limits(cap)
        with self.assertRaises(UserError):
            rule(unknown=True)

    def test_scope_exclusions_are_component_based(self):
        value = rule()
        self.assertFalse(excluded(value, dict(id='one', plex_path='/synthetic/title/video.mp4')))
        for asset in [
            dict(id='excluded-id', plex_path='/synthetic/title.mp4'),
            dict(id='one', plex_path='/synthetic/excluded/video.mp4'),
            dict(id='one', plex_path='/synthetic-other/video.mp4'),
        ]:
            self.assertTrue(excluded(value, asset))
        with self.assertRaises(UserError):
            rule(roots=['/synthetic/../outside'])

    def test_dst_repeated_hour_uses_restrictive_allowed_interval(self):
        value = rule(windows=[dict(days=[6], start='01:30', end='02:30')])
        # Fall-back start uses the later 01:30, never grants the first fold.
        self.assertFalse(permitted(value, datetime(2026, 11, 1, 8, 45, tzinfo=timezone.utc)))
        self.assertTrue(permitted(value, datetime(2026, 11, 1, 9, 45, tzinfo=timezone.utc)))
        value = rule(windows=[dict(days=[6], start='02:30', end='04:00')])
        self.assertFalse(permitted(value, datetime(2026, 3, 8, 10, 45, tzinfo=timezone.utc)))

    def test_quiet_ambiguous_hour_expands_and_missing_boundary_blocks_day(self):
        value = rule(quiet=[dict(days=[6], start='01:30', end='02:30')])
        self.assertFalse(permitted(value, datetime(2026, 11, 1, 8, 45, tzinfo=timezone.utc)))
        self.assertFalse(permitted(value, datetime(2026, 11, 1, 9, 45, tzinfo=timezone.utc)))
        value = rule(quiet=[dict(days=[6], start='02:30', end='04:00')])
        self.assertFalse(permitted(value, datetime(2026, 3, 8, 16, tzinfo=timezone.utc)))


@unittest.skipUnless(os.name == 'posix' and hasattr(signal, 'SIGXFSZ'), 'Hard per-file limits require POSIX')
class HardLimit(unittest.TestCase):
    def test_fast_tool_cannot_exceed_reviewed_bound_and_source_is_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'source', Path(folder) / 'retained-partial'
            source.write_bytes(b'original-synthetic-source')
            result = subprocess.run(
                [
                    sys.executable,
                    '-m',
                    'curator.limited_exec',
                    '4096',
                    '--',
                    sys.executable,
                    '-c',
                    'import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b"x"*1000000)',
                    str(output),
                ],
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(output.exists())
            self.assertLessEqual(output.stat().st_size, 4096)
            self.assertEqual(source.read_bytes(), b'original-synthetic-source')

    def test_malformed_or_unbounded_limit_never_starts_tool(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'must-not-exist'
            for bound in ('0', '-1', 'inf', '1.2', str(2**51)):
                result = subprocess.run(
                    [
                        sys.executable,
                        '-m',
                        'curator.limited_exec',
                        bound,
                        '--',
                        sys.executable,
                        '-c',
                        'import pathlib,sys; pathlib.Path(sys.argv[1]).touch()',
                        str(marker),
                    ],
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 78)
                self.assertFalse(marker.exists())
