"""Bounded hints are read-only and optional; the reviewed interval stays explicit."""

import copy
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_curator
from test_preview_render import media
from curator import tools
from curator.errors import UserError
from curator.preview_boundaries import WINDOW_MS, nearby_cut, suggest_boundaries, _scan_slot
from curator.preview_cards import DEFAULTS


class BoundaryReview(unittest.TestCase):
    setUp = test_curator.Workflows.setUp
    tearDown = test_curator.Workflows.tearDown

    def request(self):
        info = self.service.preview_info(self.asset['id'])
        return dict(
            asset=self.asset['id'],
            asset_version=info['asset_version'],
            start_ms=2000,
            values={**copy.deepcopy(DEFAULTS), 'requested_duration_ms': 4000},
        )

    @patch('curator.preview_review.tools.executable', return_value='/synthetic/ffmpeg')
    @patch('curator.preview_render.tools.probe', return_value=media())
    def test_proposal_preserves_original_range_and_does_not_create_jobs_or_modify_files(self, probe, executable):
        before = self.file.read_bytes()
        tasks_before = self.store.all('tasks')
        request = self.request()
        with patch(
            'curator.preview_review.suggest_boundaries',
            return_value=dict(start_ms=2100, end_ms=6300, found=dict(start=True, end=True)),
        ):
            result = self.service.preview_boundaries(request)
        self.assertEqual((result['original']['start_ms'], result['original']['end_ms']), (2000, 6000))
        self.assertEqual((result['proposed']['start_ms'], result['proposed']['end_ms']), (2100, 6300))
        self.assertTrue(result['changed'])
        self.assertEqual(result['window_ms'], 3000)
        self.assertEqual(self.store.all('tasks'), tasks_before)
        self.assertFalse(self.plex.writes)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertNotIn('local_path', str(result))

    @patch('curator.preview_review.tools.executable', return_value='/synthetic/ffmpeg')
    @patch('curator.preview_render.tools.probe', return_value=media())
    def test_no_cuts_and_invalid_shortened_interval_keep_manual_selection(self, probe, executable):
        request = self.request()
        for suggestion in [
            dict(start_ms=2000, end_ms=6000, found=dict(start=False, end=False)),
            dict(start_ms=3900, end_ms=4000, found=dict(start=True, end=True)),
        ]:
            with patch('curator.preview_review.suggest_boundaries', return_value=suggestion):
                result = self.service.preview_boundaries(request)
            self.assertFalse(result['changed'])
            self.assertEqual(result['original'], result['proposed'])
            self.assertIn('manual interval', result['note'])

    @patch('curator.preview_review.tools.executable', return_value='/synthetic/ffmpeg')
    @patch('curator.preview_render.tools.probe', return_value=media())
    def test_changed_source_and_stale_requests_never_return_an_adoptable_hint(self, probe, executable):
        request = self.request()
        with patch('curator.preview_review.suggest_boundaries') as scan:
            with self.assertRaises(UserError):
                self.service.preview_boundaries({**request, 'asset_version': 'old'})
            scan.assert_not_called()

        def replace(*args):
            self.file.write_bytes(b'replaced source')
            return dict(start_ms=2100, end_ms=6300, found=dict(start=True, end=True))

        with patch('curator.preview_review.suggest_boundaries', side_effect=replace), self.assertRaises(UserError):
            self.service.preview_boundaries(request)

    @patch('curator.preview_render.tools.probe', return_value=media())
    def test_invalid_manual_interval_is_rejected_before_scanning(self, probe):
        request = self.request()
        with patch('curator.preview_review.suggest_boundaries') as scan:
            for start in [-1, True, 20000]:
                with self.assertRaises(UserError):
                    self.service.preview_boundaries({**request, 'start_ms': start})
            scan.assert_not_called()


class BoundedDetection(unittest.TestCase):
    def test_relative_timestamps_bounds_and_nearest_tie_are_deterministic(self):
        completed = subprocess.CompletedProcess([], 0, b'', b'pts_time:1 pts_time:3 pts_time:99 pts_time:1e999')
        with patch('curator.preview_boundaries.subprocess.run', return_value=completed) as run:
            self.assertEqual(nearby_cut('/ffmpeg', '/source', 5000, 20000, 2), 5000)
            command = run.call_args.args[0]
            self.assertEqual(command[command.index('-ss') + 1], '2.0')
            self.assertEqual(command[command.index('-t') + 1], '6.0')
            self.assertEqual(command[command.index('-map') + 1], '0:2')
            self.assertEqual(run.call_args.kwargs['timeout'], 20)
            self.assertEqual(nearby_cut('/ffmpeg', '/source', 11000, 12000, 0), 11000)
            command = run.call_args.args[0]
            self.assertEqual(command[command.index('-t') + 1], '4.0')

    def test_timeout_and_concurrent_scans_leave_the_manual_workflow_available(self):
        with patch('curator.preview_boundaries.subprocess.run', side_effect=subprocess.TimeoutExpired('ffmpeg', 20)):
            with self.assertRaisesRegex(UserError, 'manual interval'):
                suggest_boundaries('/ffmpeg', '/source', 2000, 4000, 10000, 0)
        self.assertTrue(_scan_slot.acquire(blocking=False))
        try:
            with self.assertRaisesRegex(UserError, 'Another scene search'):
                suggest_boundaries('/ffmpeg', '/source', 2000, 4000, 10000, 0)
        finally:
            _scan_slot.release()

    def test_actual_synthetic_cuts_and_static_source(self):
        try:
            ffmpeg = tools.executable({}, 'ffmpeg')
        except UserError:
            self.skipTest('FFmpeg is unavailable')
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'cuts.mp4'
            command = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error']
            for color in ['black', 'white', 'black']:
                command += ['-f', 'lavfi', '-i', f'color=c={color}:s=320x180:r=30:d=2']
            subprocess.run(
                command
                + [
                    '-filter_complex',
                    '[0:v][1:v][2:v]concat=n=3:v=1:a=0',
                    '-c:v',
                    'mpeg4',
                    str(source),
                ],
                capture_output=True,
                timeout=30,
                check=True,
            )
            before = tools.digest(source)
            suggestion = suggest_boundaries(ffmpeg, source, 1700, 4300, 6000, 0)
            self.assertEqual(suggestion['found'], dict(start=True, end=True))
            self.assertAlmostEqual(suggestion['start_ms'], 2000, delta=100)
            self.assertAlmostEqual(suggestion['end_ms'], 4000, delta=100)
            self.assertLessEqual(abs(suggestion['start_ms'] - 1700), WINDOW_MS)
            self.assertEqual(tools.digest(source), before)
            static = Path(folder) / 'static.mp4'
            subprocess.run(
                [
                    ffmpeg,
                    '-nostdin',
                    '-hide_banner',
                    '-loglevel',
                    'error',
                    '-f',
                    'lavfi',
                    '-i',
                    'color=c=black:s=320x180:r=30:d=6',
                    '-c:v',
                    'mpeg4',
                    str(static),
                ],
                capture_output=True,
                timeout=30,
                check=True,
            )
            self.assertEqual(
                suggest_boundaries(ffmpeg, static, 0, 6000, 6000, 0)['found'], dict(start=False, end=False)
            )
