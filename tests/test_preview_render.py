"""Preview plans, queue isolation, source/card provenance and local rendering."""

import base64
import copy
import hashlib
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
import test_curator
from test_artwork_managers import png
from curator import tools
from curator.errors import UserError
from curator.preview_render import FPS, render_command, timing, output_profile
from curator.preview_cards import DEFAULTS
from curator.service import Service
from curator.store import Store


def media(duration=12, audio=True):
    streams = [dict(index=0, codec_type='video', codec_name='h264', width=320, height=180, avg_frame_rate='30/1')]
    if audio:
        streams.append(dict(index=1, codec_type='audio', codec_name='aac', channels=2, sample_rate='48000'))
    return dict(width=320, height=180, codec='h264', duration_seconds=duration, size_bytes=1000, streams=streams)


class PreviewPlans(unittest.TestCase):
    setUp = test_curator.Workflows.setUp
    tearDown = test_curator.Workflows.tearDown

    def plan(self, start=0, values=None, identity=None):
        identity = identity or self.asset['id']
        self.service.preview_tools = lambda: dict(
            ffmpeg=__file__,
            ffprobe=__file__,
            encoder='libx264',
            ffmpeg_identity=tools.fingerprint(__file__),
            ffprobe_identity=tools.fingerprint(__file__),
        )
        with patch('curator.preview_render.tools.probe', return_value=media()):
            info = self.service.preview_info(identity)
            return self.service.create_preview_plan(
                dict(
                    asset=identity,
                    asset_version=info['asset_version'],
                    start_ms=start,
                    values=values or {**DEFAULTS, 'requested_duration_ms': 3000},
                    audio_stream=1,
                    defaults_revision=info['defaults']['revision'],
                )
            )

    def test_timing_shortens_at_end_without_shifting_and_validates_overlap(self):
        values = copy.deepcopy(DEFAULTS)
        t = timing(10000, 30000, 12000, values)
        self.assertEqual((t['start_ms'], t['end_ms']), (10000, 12000))
        self.assertTrue(t['shortened'])
        self.assertEqual(t['total_ms'], 2000)
        for start, length in [(12000, 30000), (-1, 30000), (0, True), (0, 0)]:
            with self.assertRaises(UserError):
                timing(start, length, 12000, values)
        with self.assertRaises(UserError):
            timing(0, 500, 12000, values)
        values.update(intro=dict(card='intro', version=1), outro=dict(card='outro', version=1))
        self.assertEqual(timing(0, 30000, 60000, values)['total_ms'], 35000)

    def test_geometry_no_upscale_unknown_fps_refused(self):
        self.assertEqual(output_profile(media())['width'], 320)
        large = media()
        large.update(width=3840, height=2160)
        self.assertEqual((output_profile(large)['width'], output_profile(large)['height']), (1280, 720))
        large['streams'][0]['avg_frame_rate'] = '0/0'
        with self.assertRaises(UserError):
            output_profile(large)

    def test_plan_private_paths_not_returned_idempotent_generate_does_not_start_queue(self):
        plan = self.plan()
        self.assertNotIn('source', plan)
        self.assertNotIn('tools', plan)
        request = uuid.uuid4().hex
        first = self.service.generate_preview(plan['id'], request)
        self.assertEqual(self.service.generate_preview(plan['id'], request)['id'], first['id'])
        self.assertEqual(self.service.get_task(first['id'])['status'], 'queued')
        self.assertEqual(self.service.active, set())
        self.assertEqual(self.service.task_queues(self.store.all('tasks'), [self.lib])[0]['kind'], 'optimize')
        self.assertEqual([t['id'] for t in self.service.waiting_tasks(kind='optimize')], [first['id']])
        with self.assertRaises(UserError):
            self.service.generate_preview(self.plan()['id'], request)
        with self.assertRaises(UserError):
            self.service.review(first['id'], 1, 'accept')
        with self.assertRaises(UserError):
            self.service.action(first['id'], 'queue', 1)

    def test_stale_source_defaults_and_hidden_card_reject_submission(self):
        plan = self.plan()
        self.service.save_preview_defaults(1, {'audio_fade_ms': 200})
        with self.assertRaises(UserError):
            self.service.generate_preview(plan['id'], uuid.uuid4().hex)
        card = self.service.import_preview_card(dict(name='Intro', role='intro', image=png(64, 36)))
        values = {**DEFAULTS, 'intro': dict(card=card['id'], version=1), 'requested_duration_ms': 3000}
        plan = self.plan(values=values)
        self.service.hide_preview_card(card['id'], 1)
        with self.assertRaises(UserError):
            self.service.generate_preview(plan['id'], uuid.uuid4().hex)
        plan = self.plan()
        self.file.write_bytes(b'changed file')
        with self.assertRaises(UserError):
            self.service.generate_preview(plan['id'], uuid.uuid4().hex)

    def test_queued_plan_keeps_old_card_bytes_when_replaced_and_hidden(self):
        card = self.service.import_preview_card(dict(name='Intro', role='intro', image=png(64, 36)))
        plan = self.plan(values={**DEFAULTS, 'intro': dict(card=card['id'], version=1), 'requested_duration_ms': 3000})
        queued = self.service.generate_preview(plan['id'], uuid.uuid4().hex)
        self.service.import_preview_card(
            dict(id=card['id'], revision=1, name='Changed', role='intro', image=png(32, 18))
        )
        self.service.hide_preview_card(card['id'], 2)
        frozen = self.service.preview_plan(plan['id'])
        _, paths = self.service.check_preview_plan(frozen)
        self.assertEqual(hashlib.sha256(paths['intro'].read_bytes()).hexdigest(), frozen['cards']['intro']['sha256'])
        self.assertEqual(self.service.get_task(queued['id'])['status'], 'queued')
        command = render_command(frozen, paths, self.root / 'candidate.mp4')
        self.assertIn('xfade=', ' '.join(command))
        self.assertNotIn('HandBrake', ' '.join(command))
        self.assertIn('adelay=2500:all=1', ' '.join(command))

    def test_pause_alias_cancel_and_restart_do_not_replay(self):
        plan = self.plan()
        task = self.service.generate_preview(plan['id'], uuid.uuid4().hex)
        self.service.pause_queues(kind='preview_render')
        self.assertTrue(self.store.get('settings', 'queue-paused:global:optimize'))
        self.assertEqual(self.service.pause_key(None, 'optimize'), self.service.pause_key(None, 'preview_render'))
        self.service.action(task['id'], 'cancel', 1)
        self.assertEqual(self.service.get_task(task['id'])['status'], 'cancelled')
        second = self.service.generate_preview(plan['id'], uuid.uuid4().hex)
        with self.store.transaction():
            row = self.service.get_task(second['id'])
            row['status'] = 'running'
            self.store.put('tasks', row['id'], row)
        root = self.store.root
        self.store.close()
        self.store = Store(root)
        self.service = Service(self.store)
        self.assertEqual(self.service.get_task(second['id'])['status'], 'blocked')
        self.assertFalse(self.service.queue_running())

    def test_shared_encoding_pool_handles_mixed_queue_in_order(self):
        second_file = self.media / 'second.mkv'
        second_file.write_bytes(b'second source')
        second_asset = {
            **self.asset,
            'id': 'b' * 24,
            'rating_key': '20',
            'plex_path': '/plex/second.mkv',
            'local_path': str(second_file.resolve()),
            'fingerprint': tools.fingerprint(second_file),
        }
        with self.store.transaction():
            self.store.put('assets', second_asset['id'], second_asset)
            optimization = dict(
                id='optimization',
                asset=self.asset['id'],
                library=self.lib['id'],
                kind='optimize',
                title='First',
                status='queued',
                version=1,
                approval=1,
                source=self.asset['fingerprint'],
                plan={},
            )
            self.store.put('tasks', optimization['id'], optimization)
        preview = self.service.generate_preview(self.plan(identity=second_asset['id'])['id'], uuid.uuid4().hex)
        entered, release = threading.Event(), threading.Event()
        order = []

        def optimize(task, asset):
            order.append(task['id'])
            entered.set()
            release.wait(5)
            self.service._save(task, status='awaiting_review')

        def render(task):
            order.append(task['id'])
            self.service._save(task, status='awaiting_review')

        with (
            patch.object(self.service, '_process', side_effect=optimize),
            patch.object(self.service, 'execute_preview', side_effect=render),
        ):
            self.service.start(kind='preview_render')
            self.assertTrue(entered.wait(3))
            self.assertEqual(order, ['optimization'])
            self.assertEqual(set(self.service.queue_workers), {'optimize'})
            self.assertEqual(self.service.queue_limit('preview_render'), 1)
            release.set()
            for _ in range(100):
                if not self.service.queue_running():
                    break
                time.sleep(0.03)
        self.assertEqual(order, ['optimization', preview['id']])
        self.assertEqual(self.service.get_task(preview['id'])['status'], 'awaiting_review')


class PreviewMedia(unittest.TestCase):
    def setUp(self):
        try:
            self.ffmpeg = tools.executable({}, 'ffmpeg')
            tools.executable({}, 'ffprobe')
        except UserError:
            self.skipTest('FFmpeg/ffprobe unavailable')
        test_curator.Workflows.setUp(self)
        self.addCleanup(test_curator.Workflows.tearDown, self)
        try:
            self.service.preview_tools()
        except UserError:
            self.skipTest('H264/AAC preview encoders unavailable')

    def source(self, audio='stereo'):
        import subprocess

        command = [
            self.ffmpeg,
            '-hide_banner',
            '-loglevel',
            'error',
            '-y',
            '-f',
            'lavfi',
            '-i',
            'testsrc2=s=320x180:r=30',
        ]
        if audio != 'silent':
            command += ['-f', 'lavfi', '-i', 'sine=frequency=600:sample_rate=48000']
        command += ['-t', '3', '-c:v', 'mpeg4']
        if audio != 'silent':
            command += ['-c:a', 'aac', '-ac', '6' if audio == 'multichannel' else '2']
        subprocess.run(command + [str(self.file)], check=True, capture_output=True)
        self.asset.update(fingerprint=tools.fingerprint(self.file), technical=tools.probe(self.file, {}))
        with self.store.transaction():
            self.store.put('assets', self.asset['id'], self.asset)

    def render(self, values, start=500):
        info = self.service.preview_info(self.asset['id'])
        plan = self.service.create_preview_plan(
            dict(
                asset=self.asset['id'],
                asset_version=info['asset_version'],
                start_ms=start,
                values=values,
                audio_stream=info['default_audio'],
                defaults_revision=1,
            )
        )
        queued = self.service.generate_preview(plan['id'], uuid.uuid4().hex)
        self.service._execute(queued['id'])
        task = self.service.get_task(queued['id'])
        self.assertEqual(task['status'], 'awaiting_review', task.get('error'))
        output = self.store.get('settings', 'preview-output:' + task['id'])
        self.assertAlmostEqual(output['result']['duration_seconds'], plan['timing']['total_ms'] / 1000, delta=0.1)
        self.assertEqual(output['result']['codec'], 'h264')
        return Path(output['path']), output['result']

    def test_real_cards_audio_alignment_and_source_preservation(self):
        import struct
        import subprocess

        self.source()
        original = tools.digest(self.file)
        intro = self.service.import_preview_card(dict(name='Intro', role='intro', image=png(160, 90)))
        outro = self.service.import_preview_card(dict(name='Outro', role='outro', image=png(90, 160)))
        output, result = self.render(
            {
                **DEFAULTS,
                'requested_duration_ms': 2000,
                'intro': dict(card=intro['id'], version=1),
                'outro': dict(card=outro['id'], version=1),
            }
        )
        self.assertEqual((result['width'], result['height']), (320, 180))
        rms = []
        for start in (1, 3.2, 6):
            decoded = subprocess.run(
                [
                    self.ffmpeg,
                    '-v',
                    'error',
                    '-ss',
                    str(start),
                    '-i',
                    str(output),
                    '-t',
                    '0.3',
                    '-map',
                    '0:a:0',
                    '-f',
                    'f32le',
                    '-ac',
                    '1',
                    '-ar',
                    '48000',
                    '-',
                ],
                check=True,
                capture_output=True,
            ).stdout
            samples = struct.unpack('<' + 'f' * (len(decoded) // 4), decoded)
            rms.append((sum(value * value for value in samples) / len(samples)) ** 0.5)
        self.assertLess(rms[0], 0.001)
        self.assertGreater(rms[1], 0.01)
        self.assertLess(rms[2], 0.001)
        self.assertEqual(tools.digest(self.file), original)

    def test_real_silent_and_multichannel_zero_overlap(self):
        intro = self.service.import_preview_card(dict(name='Intro', role='intro', image=png(160, 90, alpha=0)))
        for audio in ('silent', 'multichannel'):
            with self.subTest(audio=audio):
                self.source(audio)
                original = tools.digest(self.file)
                _, result = self.render(
                    {
                        **DEFAULTS,
                        'requested_duration_ms': 2000,
                        'intro': dict(card=intro['id'], version=1),
                        'crossfade_ms': 0,
                    }
                )
                tracks = [s for s in result['streams'] if s.get('codec_type') == 'audio']
                self.assertEqual(len(tracks), 0 if audio == 'silent' else 1)
                if tracks:
                    self.assertEqual(tracks[0]['channels'], 2)
                self.assertEqual(tools.digest(self.file), original)

    def test_delayed_source_audio_keeps_its_offset(self):
        import subprocess
        import struct

        subprocess.run(
            [
                self.ffmpeg,
                '-v',
                'error',
                '-y',
                '-f',
                'lavfi',
                '-i',
                'testsrc2=s=320x180:r=30',
                '-itsoffset',
                '0.7',
                '-f',
                'lavfi',
                '-i',
                'sine=frequency=600:sample_rate=48000',
                '-t',
                '3',
                '-c:v',
                'mpeg4',
                '-c:a',
                'aac',
                '-ac',
                '2',
                str(self.file),
            ],
            check=True,
            capture_output=True,
        )
        self.asset.update(fingerprint=tools.fingerprint(self.file), technical=tools.probe(self.file, {}))
        with self.store.transaction():
            self.store.put('assets', self.asset['id'], self.asset)
        output, _ = self.render({**DEFAULTS, 'requested_duration_ms': 2000, 'audio_fade_ms': 0}, start=0)
        rms = []
        for start in (0.2, 1.1):
            raw = subprocess.run(
                [
                    self.ffmpeg,
                    '-v',
                    'error',
                    '-ss',
                    str(start),
                    '-i',
                    str(output),
                    '-t',
                    '0.2',
                    '-map',
                    '0:a:0',
                    '-f',
                    'f32le',
                    '-ac',
                    '1',
                    '-ar',
                    '48000',
                    '-',
                ],
                check=True,
                capture_output=True,
            ).stdout
            samples = struct.unpack('<' + 'f' * (len(raw) // 4), raw)
            rms.append((sum(value * value for value in samples) / len(samples)) ** 0.5)
        self.assertLess(rms[0], 0.001)
        self.assertGreater(rms[1], 0.01)


class PreviewCancellation(unittest.TestCase):
    setUp = PreviewPlans.setUp
    tearDown = PreviewPlans.tearDown
    plan = PreviewPlans.plan

    def test_running_cancel_terminates_renderer_and_keeps_original(self):
        plan = self.plan()
        queued = self.service.generate_preview(plan['id'], uuid.uuid4().hex)
        entered = threading.Event()

        class Process:
            returncode = None

            def poll(self):
                entered.set()
                return self.returncode

            def terminate(self):
                self.returncode = -15

            def kill(self):
                self.returncode = -9

            def wait(self, timeout=None):
                return self.returncode

        process = Process()
        with patch('curator.preview_render.subprocess.Popen', return_value=process):
            thread = threading.Thread(target=self.service._execute, args=(queued['id'],))
            thread.start()
            self.assertTrue(entered.wait(3))
            self.service.action(queued['id'], 'cancel', 1)
            thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(self.service.get_task(queued['id'])['status'], 'cancelled')
        self.assertEqual(self.file.read_bytes(), b'original-video')
        self.assertIsNone(self.store.get('settings', 'preview-output:' + queued['id']))
