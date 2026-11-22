"""Curator selection is atomic, verified and separate from movie/Plex publication."""

import concurrent.futures
import hashlib
import http.cookiejar
import json
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPCookieProcessor, Request
from curator import tools
from curator.errors import UserError
from curator.preview_review import video_range
from curator.web import App
import test_preview_render


class PreviewReview(unittest.TestCase):
    setUp = test_preview_render.PreviewPlans.setUp
    tearDown = test_preview_render.PreviewPlans.tearDown
    plan = test_preview_render.PreviewPlans.plan

    def candidate(self, content=b'0123456789'):
        import uuid

        plan = self.plan()
        queued = self.service.generate_preview(plan['id'], uuid.uuid4().hex)
        task = self.service.get_task(queued['id'])
        path = self.store.root / 'preview-outputs' / task['id'] / 'test' / 'candidate.mp4'
        path.parent.mkdir(parents=True)
        path.write_bytes(content)
        digest = tools.digest(path)
        result = dict(width=320, height=180, duration_seconds=3, codec='h264', streams=[])
        with self.store.transaction():
            task.update(status='awaiting_review', output_hash=digest, result=result)
            self.store.put('tasks', task['id'], task)
            self.store.put(
                'settings',
                'preview-output:' + task['id'],
                dict(
                    path=str(path), sha256=digest, source_hash=tools.digest(self.file), plan=plan['id'], result=result
                ),
            )
        return task, path

    def test_explicit_selection_noop_previous_retention_and_generic_guards(self):
        first, path = self.candidate()
        self.assertIsNone(self.service.preview_selection(first['asset'])['job'])
        selected = self.service.select_preview(first['id'], 1, 0)
        self.assertEqual(selected['job'], first['id'])
        self.assertEqual(selected['revision'], 1)
        events = self.store.db.execute('SELECT count(*) FROM events').fetchone()[0]
        self.assertEqual(self.service.select_preview(first['id'], 1, 1), selected)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM events').fetchone()[0], events)
        for action in ('delete', 'reject'):
            with self.subTest(action=action), self.assertRaises(UserError):
                self.service.action(first['id'], action, 1)
        second, other = self.candidate(b'another candidate')
        self.assertEqual(self.service.preview_selection(first['asset']), selected)
        self.service.select_preview(second['id'], 1, 1)
        self.assertEqual(path.read_bytes(), b'0123456789')
        self.assertEqual(other.read_bytes(), b'another candidate')
        self.assertEqual(self.file.read_bytes(), b'original-video')
        self.assertFalse(self.plex.writes)

    def test_conflict_tamper_and_source_change_keep_existing_selection(self):
        first, _ = self.candidate()
        selected = self.service.select_preview(first['id'], 1, 0)
        second, path = self.candidate()
        with self.assertRaises(UserError):
            self.service.select_preview(second['id'], 1, 0)
        path.write_bytes(b'changed')
        with self.assertRaises(UserError):
            self.service.select_preview(second['id'], 1, 1)
        self.assertEqual(self.service.preview_selection(first['asset']), selected)
        third, _ = self.candidate()
        self.file.write_bytes(b'changed source')
        with self.assertRaises(UserError):
            self.service.select_preview(third['id'], 1, 1)
        self.assertEqual(self.service.preview_selection(first['asset']), selected)

    def test_two_concurrent_selections_only_one_revision_wins(self):
        first, _ = self.candidate()
        second, _ = self.candidate()

        def select(identity):
            try:
                return self.service.select_preview(identity, 1, 0)['job']
            except UserError:
                return 'conflict'

        with concurrent.futures.ThreadPoolExecutor(2) as executor:
            results = list(executor.map(select, [first['id'], second['id']]))
        self.assertEqual(results.count('conflict'), 1)
        self.assertEqual(self.service.preview_selection(first['asset'])['revision'], 1)

    def test_discard_retains_bytes_and_never_changes_saved_preview(self):
        first, _ = self.candidate()
        selected = self.service.select_preview(first['id'], 1, 0)
        second, path = self.candidate()
        self.service.discard_preview(second['id'], 1)
        self.assertEqual(path.read_bytes(), b'0123456789')
        self.assertEqual(self.service.preview_selection(first['asset']), selected)
        self.assertEqual(self.service.get_task(second['id'])['status'], 'rejected')
        with self.assertRaises(UserError):
            self.service.select_preview(second['id'], 2, 1)
        with self.assertRaises(UserError):
            self.service.discard_preview(first['id'], 1)

    def test_job_payload_has_no_private_paths(self):
        task, _ = self.candidate()
        job = self.service.preview_job(task['id'])
        self.assertNotIn(str(self.store.root), json.dumps(job))
        self.assertNotIn(str(self.file), json.dumps(job))
        self.assertIn('/api/preview/video?', job['candidate']['url'])
        self.assertEqual(job['plan']['timing']['total_ms'], 3000)

    def test_stream_byte_ranges_and_authentication(self):
        task, _ = self.candidate()
        server = App(('127.0.0.1', 0), self.service)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        browser = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        url = base + '/api/preview/video?job=' + task['id']
        with self.assertRaises(HTTPError) as unauthorized:
            browser.open(url)
        unauthorized.exception.close()
        with browser.open(base + '/') as response:
            response.read()
        for header, expected in [('bytes=2-5', b'2345'), ('bytes=-3', b'789'), ('bytes=7-', b'789')]:
            with browser.open(Request(url, headers={'Range': header})) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(response.read(), expected)
                self.assertEqual(response.headers['Accept-Ranges'], 'bytes')
        with self.assertRaises(HTTPError) as error:
            browser.open(Request(url, headers={'Range': 'bytes=99-'}))
        self.assertEqual(error.exception.code, 416)
        error.exception.close()


class VideoRanges(unittest.TestCase):
    def test_full_suffix_bounds_and_invalid_multiple_ranges(self):
        self.assertEqual(video_range(None, 10), (0, 9, False))
        self.assertEqual(video_range('bytes=2-100', 10), (2, 9, True))
        self.assertEqual(video_range('bytes=-100', 10), (0, 9, True))
        for header in ('bytes=0-1,3-5', 'bytes=-0', 'bytes=9-2', 'bytes=10-', 'bytes=-', 'wrong'):
            with self.subTest(header=header), self.assertRaises(UserError):
                video_range(header, 10)
