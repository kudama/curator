import base64
import copy
import struct
import unittest
import zlib
import test_curator
from curator.image_contract import editor_png


def png(width, height, alpha=255):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b''.join(b'\0' + bytes([60, 120, 180, alpha]) * width for _ in range(height))
    data = (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress(raw))
        + chunk(b'IEND', b'')
    )
    return base64.b64encode(data).decode()


class ArtworkManagers(unittest.TestCase):
    setUp = test_curator.Workflows.setUp
    tearDown = test_curator.Workflows.tearDown

    def test_correct_shapes_and_real_alpha_logo_required(self):
        self.assertEqual(editor_png(png(20, 30), '2:3')['width'], 20)
        self.assertEqual(editor_png(png(16, 9), '16:9')['height'], 9)
        self.assertTrue(editor_png(png(10, 5, 128), logo=True)['alpha'])
        for image, ratio, logo in [(png(10, 10), '2:3', False), (png(10, 5), None, True), ('bad', None, False)]:
            with self.subTest(ratio=ratio, logo=logo), self.assertRaises(ValueError):
                editor_png(image, ratio, logo)

    def test_preview_creates_only_review_tasks_and_does_not_publish(self):
        result = self.service.artwork_preview([self.asset['id']], 'cover', '2:3', {self.asset['id']: png(20, 30)})
        self.assertEqual(result['tasks'][0]['status'], 'awaiting_review')
        self.assertEqual(self.plex.writes, [])
        with self.assertRaisesRegex(ValueError, 'correct artwork format'):
            self.service.artwork_preview([self.asset['id']], 'square', '16:9', {self.asset['id']: png(16, 9)})
        self.assertEqual(len([t for t in self.store.all('tasks') if t['kind'] == 'artwork']), 1)

    def test_collection_identity_is_separate_from_members_and_scanned_catalog(self):
        item = dict(ratingKey='50', type='collection', title='Summer', guid='collection-guid', childCount=7)
        self.plex.collections = lambda lib: [dict(key='50', title='Summer', count=7, smart=False)]
        original_item = self.plex.item
        self.plex.item = lambda key: copy.deepcopy(item) if key == '50' else original_item(key)
        before = self.store.all('assets')
        result = self.service.collection_artwork_target(self.lib['id'], '50')
        asset = result['asset']
        self.assertEqual(self.store.all('assets'), before)
        self.assertEqual(asset['artwork_target'], 'collection')
        self.assertEqual(self.service.asset({'asset': asset['id']}, check=False)['rating_key'], '50')
        with self.assertRaises(ValueError):
            self.service.asset({'asset': asset['id']})
        self.assertEqual(self.service.collection_artwork_target(self.lib['id'], '50')['asset']['id'], asset['id'])
        plan = self.service.artwork_preview([asset['id']], 'cover', '2:3', {asset['id']: png(20, 30)})['tasks'][0]
        self.assertEqual(plan['plan']['rating_key'], '50')
        self.assertEqual(self.plex.writes, [])
        with self.assertRaisesRegex(ValueError, 'correct artwork format'):
            self.service.artwork_preview([asset['id']], 'cover', '16:9', {asset['id']: png(16, 9)})
        with self.assertRaisesRegex(ValueError, 'does not belong'):
            self.service.collection_artwork_target(self.lib['id'], '999')
        self.assertEqual(self.store.all('assets'), before)

    def test_malformed_png_fails_before_any_draft(self):
        encoded = png(20, 30)
        data = bytearray(base64.b64decode(encoded))
        data[-1] ^= 1
        with self.assertRaises(ValueError):
            self.service.artwork_preview(
                [self.asset['id']], 'cover', '2:3', {self.asset['id']: base64.b64encode(data).decode()}
            )
        self.assertEqual(len(self.store.all('tasks')), 1)

    def test_opaque_logo_cannot_bypass_editor_validation_through_legacy_plan(self):
        task = self.service.artwork_plan([self.asset['id']], 'logo', 'gritty', images={self.asset['id']: png(16, 9)})[
            'tasks'
        ][0]
        with self.assertRaisesRegex(ValueError, 'opaque'):
            self.service.publish_artwork(task, self.asset)
        self.assertFalse(self.plex.writes)
