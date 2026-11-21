import copy
import unittest
from unittest.mock import patch

import test_curator
from curator import tools
from curator.errors import UserError
from curator.history import acting
from curator.upscale_recovery import processing_validation


FILTER = 'tvai_up=model=prob-4:scale=2:w=0:h=0:preblur=0'


class UpscaleRecovery(unittest.TestCase):
    setUp = test_curator.Workflows.setUp
    tearDown = test_curator.Workflows.tearDown

    def make(self, **changes):
        media = dict(width=404, height=720, duration_seconds=60, streams=[], container='matroska')
        self.asset['technical'] = media
        self.output = self.root / 'retained.mkv'
        self.output.write_bytes(b'processed')
        row = dict(
            self.task,
            kind='upscale',
            status='blocked',
            validation=[tools.RESOLUTION_FLOOR],
            output=str(self.output),
            output_hash=tools.digest(self.output),
            source_hash=tools.digest(self.file),
            tool_settings={'topaz_filter': FILTER, 'topaz_quality': 61},
            result={**media, 'width': 808, 'height': 1440},
        )
        row.update(changes)
        with self.store.transaction():
            self.store.put('assets', self.asset['id'], self.asset)
            self.store.put('tasks', row['id'], row)
        self.row = row
        return row

    def recover(self, action, preview=None):
        p = preview or self.service.upscale_recovery_preview(self.row['id'], self.row['version'])
        with acting('operator'):
            return self.service.upscale_recover(p['id'], p['version'], action, p['token'])

    def probes(self, extra=None):
        return patch(
            'curator.tools.probe', side_effect=[self.asset['technical'], {**self.row['result'], **(extra or {})}]
        )

    def test_resolution_exception_requires_independent_checks_and_keeps_strict_validation(self):
        row = self.make()
        config = self.service.config()
        with self.probes(), patch('curator.tools.output_decodes', return_value=True) as decode:
            saved = self.recover('review_resolution')
        decode.assert_called_once()
        self.assertEqual(saved['status'], 'awaiting_review')
        self.assertFalse(saved['comparison_loaded'])
        self.assertEqual(saved['validation'], [tools.RESOLUTION_FLOOR])
        self.assertFalse(processing_validation(saved))
        self.assertEqual(self.service.config(), config)
        self.assertEqual(self.file.read_bytes(), b'original-video')
        self.assertEqual(saved['resolution_exception']['output_hash'], row['output_hash'])
        # The waiver is exact-output, exact-version, exact-result; every other failure still blocks.
        for field, value in [
            ('output_hash', 'changed'),
            ('version', 99),
            ('result', {}),
            ('validation', [tools.RESOLUTION_FLOOR, 'Duration changed']),
        ]:
            changed = {**saved, field: value}
            self.assertTrue(processing_validation(changed))
        with self.assertRaisesRegex(UserError, 'Load the source/output comparison'):
            self.service.review(saved['id'], saved['version'], 'manual')

    def test_exception_can_publish_only_through_existing_review_and_preserves_original(self):
        self.make()
        with self.probes(), patch('curator.tools.output_decodes', return_value=True):
            saved = self.recover('review_resolution')
        saved['comparison_loaded'] = True
        with self.store.transaction():
            self.store.put('tasks', saved['id'], saved)
        self.service.review(saved['id'], saved['version'], 'manual')
        self.assertEqual(self.file.read_bytes(), b'processed')
        self.assertEqual(self.file.with_name('film-old.mkv').read_bytes(), b'original-video')

    def test_other_failures_decode_failure_or_changed_hash_cannot_be_waived(self):
        for issue in [
            'Duration changed',
            'Audio track/language preservation differs',
            'Independent output decode failed',
        ]:
            self.make(validation=[tools.RESOLUTION_FLOOR, issue])
            with self.assertRaises(UserError):
                self.recover('review_resolution')
        self.make()
        with self.probes({'duration_seconds': 30}), patch('curator.tools.output_decodes', return_value=True):
            with self.assertRaisesRegex(UserError, 'other validation'):
                self.recover('review_resolution')
        with self.probes(), patch('curator.tools.output_decodes', return_value=False):
            with self.assertRaisesRegex(UserError, 'other validation'):
                self.recover('review_resolution')
        self.output.write_bytes(b'changed')
        with self.assertRaisesRegex(UserError, 'changed after processing'):
            self.recover('review_resolution')

    def test_changed_source_and_task_during_revalidation_are_refused(self):
        self.make()

        def mutate(*args):
            current = self.service.get_task(self.row['id'])
            with self.store.transaction():
                self.store.put('tasks', current['id'], {**current, 'version': 99})
            return True

        with self.probes(), patch('curator.tools.output_decodes', side_effect=mutate):
            with self.assertRaisesRegex(UserError, 'changed'):
                self.recover('review_resolution')
        self.make()
        self.file.write_bytes(b'changed original')
        with self.assertRaisesRegex(UserError, 'Source or mapping changed'):
            self.service.upscale_recovery_preview(self.row['id'], self.row['version'])

    def test_4x_is_a_fresh_frozen_plan_from_original_with_previous_output_retained(self):
        self.make()
        preview = self.service.upscale_recovery_preview(self.row['id'], self.row['version'])
        self.assertEqual(preview['redo']['dimensions'], [1616, 2880])
        saved = self.recover('prepare_4x', preview)
        self.assertEqual(saved['status'], 'recommendation')
        self.assertNotIn('approval', saved)
        self.assertNotIn('output', saved)
        self.assertEqual(saved['retained_attempts'][0]['output'], str(self.output))
        self.assertEqual(self.output.read_bytes(), b'processed')
        with self.assertRaises(UserError):
            self.recover('prepare_4x', preview)
        # Changing defaults after preview cannot silently change the reviewed retry settings.
        self.service.save_config({'topaz_filter': FILTER.replace('scale=2', 'scale=1')})
        with patch('curator.tools.executable', return_value='/synthetic/tool'):
            queued = self.service.action(saved['id'], 'queue', saved['version'])
        self.assertEqual(queued['tool_settings']['topaz_filter'], FILTER.replace('scale=2', 'scale=4'))
        self.assertEqual(queued['tool_settings']['topaz_quality'], 61)
        self.assertEqual(queued['source'], self.asset['fingerprint'])
        self.assertFalse(self.service.queue_running())
        self.assertEqual(self.file.read_bytes(), b'original-video')

    def test_deleted_stale_automatic_and_changed_preview_actions_are_refused(self):
        for changes in [dict(deleted=True), dict(status='running'), dict(published=True)]:
            self.make(**changes)
            with self.assertRaises(UserError):
                self.service.upscale_recovery_preview(self.row['id'], self.row['version'])
        self.make()
        preview = self.service.upscale_recovery_preview(self.row['id'], self.row['version'])
        with self.assertRaisesRegex(UserError, 'operator'):
            self.service.upscale_recover(preview['id'], preview['version'], 'prepare_4x', preview['token'])
        with self.store.transaction():
            self.store.put(
                'tasks', self.row['id'], {**self.row, 'tool_settings': {'topaz_filter': FILTER, 'topaz_quality': 1}}
            )
        with self.assertRaisesRegex(UserError, 'preview changed'):
            self.recover('prepare_4x', preview)

    def test_geometry_floor_ceiling_unknown_and_rotation(self):
        settings = {'topaz_filter': FILTER, 'topaz_quality': 65}
        original = copy.deepcopy(settings)
        result = tools.upscale_4x_settings(dict(width=404, height=720), settings)
        self.assertEqual(settings, original)
        self.assertEqual(result['topaz_filter'], FILTER.replace('scale=2', 'scale=4'))
        for source in [dict(width=100, height=100), dict(width=1920, height=1080)]:
            with self.assertRaises(UserError):
                tools.upscale_4x_settings(source, settings)
        for vf in [FILTER + ',scale=1920:1080', FILTER.replace('w=0', 'w=100'), FILTER + ':scale=2']:
            with self.assertRaises(UserError):
                tools.upscale_4x_settings(dict(width=404, height=720), {'topaz_filter': vf})
        anamorphic = dict(
            width=360,
            height=404,
            streams=[dict(codec_type='video', sample_aspect_ratio='2:1', side_data_list=[dict(rotation=90)])],
        )
        rotated = tools.upscale_4x_settings(anamorphic, settings)
        self.assertEqual(tools.upscale_output_geometry(anamorphic, rotated), (1616, 2880))
        with self.assertRaisesRegex(UserError, 'below the 1080-class'):
            tools.validate_upscale_target(dict(width=404, height=720), settings)
