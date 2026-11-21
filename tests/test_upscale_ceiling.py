import copy
import unittest
from unittest.mock import patch

import test_curator
from curator.quality import assess
from curator.service import identifier
from curator.tools import upscale_output_geometry, validate_upscale_target


FILTER = 'tvai_up=model=prob-4:scale=2:w=0:h=0'


class UpscaleGeometry(unittest.TestCase):
    def test_reviewed_dynamic_scales_preserve_display_geometry(self):
        for width, height, scale, expected in [
            (1920, 1080, 2, (3840, 2160)),
            (1080, 1920, 2, (2160, 3840)),
            (404, 720, 4, (1616, 2880)),
        ]:
            settings = {'topaz_filter': FILTER.replace('scale=2', f'scale={scale}')}
            source = dict(width=width, height=height)
            self.assertEqual(upscale_output_geometry(source, settings), expected)
            validate_upscale_target(source, settings)
        anamorphic = dict(
            width=1440,
            height=1080,
            streams=[dict(codec_type='video', sample_aspect_ratio='4:3', side_data_list=[dict(rotation=90)])],
        )
        self.assertEqual(upscale_output_geometry(anamorphic, {'topaz_filter': FILTER}), (2160, 3840))

    def test_oversized_landscape_and_portrait_are_refused(self):
        for width, height in [(3840, 2160), (2160, 3840), (2560, 1440)]:
            with self.subTest(width=width), self.assertRaisesRegex(ValueError, 'above the 4K ceiling'):
                validate_upscale_target(dict(width=width, height=height), {'topaz_filter': FILTER})
        validate_upscale_target(dict(width=2048, height=1080), {'topaz_filter': FILTER})

    def test_complex_explicit_and_unknown_filters_are_not_guessed(self):
        for vf in [
            FILTER + ',scale=1920:1080',
            FILTER.replace('w=0', 'w=1920'),
            FILTER.replace('scale=2', 'scale=0'),
            FILTER + ':scale=4',
            '',
        ]:
            self.assertIsNone(upscale_output_geometry(dict(width=3840, height=2160), {'topaz_filter': vf}))

    def test_4k_sources_do_not_receive_fresh_upscale_recommendations(self):
        for width, height in [(3840, 2160), (2160, 3840), (3840, 1600), (4096, 2160), (7680, 4320)]:
            self.assertNotIn('upscale', [f['kind'] for f in assess(dict(width=width, height=height))])
        findings = assess(dict(width=3840, height=2160, bitrate=80_000_000, duration_seconds=60))
        self.assertEqual([f['kind'] for f in findings], ['optimize'])


class UpscaleCeilingWorkflow(unittest.TestCase):
    setUp = test_curator.Workflows.setUp
    tearDown = test_curator.Workflows.tearDown

    def make_upscale(self, width=3840, height=2160):
        self.asset['technical'] = dict(width=width, height=height, duration_seconds=60, streams=[])
        task = dict(self.task, id=identifier(self.asset['id'], 'upscale'), kind='upscale', plan={})
        with self.store.transaction():
            self.store.put('assets', self.asset['id'], self.asset)
            self.store.put('tasks', task['id'], task)
        self.service.save_config({'topaz_filter': FILTER})
        return task

    def test_queue_refuses_known_8k_output_before_approval(self):
        task = self.make_upscale()
        with patch('curator.tools.executable', return_value='/synthetic/ffmpeg'):
            with self.assertRaisesRegex(ValueError, '7680 × 4320'):
                self.service.action(task['id'], 'queue', task['version'])
        saved = self.service.get_task(task['id'])
        self.assertEqual(saved['status'], 'recommendation')
        self.assertNotIn('approval', saved)

    def test_1080_to_4k_can_still_be_queued(self):
        task = self.make_upscale(1920, 1080)
        with patch('curator.tools.executable', return_value='/synthetic/ffmpeg'):
            saved = self.service.action(task['id'], 'queue', task['version'])
        self.assertEqual(saved['status'], 'queued')
        self.assertEqual(saved['tool_settings']['topaz_filter'], FILTER)

    def test_legacy_queued_8k_plan_is_blocked_before_process_and_retains_output(self):
        task = self.make_upscale()
        retained = self.root / 'retained-output.mkv'
        retained.write_bytes(b'previous retained output')
        task.update(
            status='queued',
            approval=task['version'],
            source=self.asset['fingerprint'],
            tool_settings={'topaz_filter': FILTER},
            output=str(retained),
        )
        with self.store.transaction():
            self.store.put('tasks', task['id'], task)
        with patch('curator.service.subprocess.Popen') as launch:
            self.service._execute(task['id'])
            launch.assert_not_called()
        saved = self.service.get_task(task['id'])
        self.assertEqual(saved['status'], 'blocked')
        self.assertIn('above the 4K ceiling', saved['error'])
        self.assertEqual(retained.read_bytes(), b'previous retained output')
        self.assertFalse((self.store.root / 'outputs' / task['id']).exists())

    def test_rematched_finished_4k_asset_does_not_start_an_upscale_cycle(self):
        task = self.make_upscale()
        task.update(status='applied', published=True)
        rematched = copy.deepcopy(self.asset)
        rematched['id'] = 'new-identity'
        with self.store.transaction():
            self.store.put('tasks', task['id'], task)
            self.store.put('assets', rematched['id'], rematched)
            self.service.reconcile_findings(rematched, assess(rematched['technical']))
        self.assertIsNone(self.store.get('tasks', identifier(rematched['id'], 'upscale')))
        self.assertEqual(self.service.get_task(task['id'])['status'], 'applied')
