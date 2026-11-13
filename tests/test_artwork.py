import json
import unittest
from pathlib import Path
from unittest.mock import patch

from curator import branding
from curator.plex import Plex
import test_curator


class Artwork(unittest.TestCase):
    def setUp(self):
        test_curator.Workflows.setUp(self)
        self.media = self.media.resolve()
        self.root = self.root.resolve()
    tearDown = test_curator.Workflows.tearDown

    def home(self):
        self.lib['profile'] = 'home'
        with self.store.transaction():
            self.store.put('libraries', self.lib['id'], self.lib)

    def template(self, **values):
        return dict(version=1, creator='Example creator', colors='blue and gold',
                    backdrop='clean abstract design', style='editorial', logo='', **values)

    def test_home_cover_ratio_and_unescaped_title(self):
        self.home()
        prompt = self.service.cover_prompt(self.task['id'], 'A "quoted" title')
        self.assertIn('16:9', prompt)
        self.assertIn('A "quoted" title', prompt)
        self.assertNotIn('portrait', prompt)

    def test_commercial_cover_ratio(self):
        self.assertIn('2:3 portrait', self.service.cover_prompt(self.task['id'], 'Title'))

    def test_save_discover_confirm_and_invalidate_changed_template(self):
        self.home()
        key = self.task['id']
        info = self.service.save_branding(key, str(self.media), self.template(), None)
        self.assertFalse(info['confirmed'])
        self.assertTrue((self.media / branding.NAME).exists())
        revision = info['suggested']['revision']
        self.assertTrue(self.service.confirm_branding(key, str(self.media), revision)['confirmed'])
        value = self.template();value['colors'] = 'green'
        info = self.service.save_branding(key, str(self.media), value, revision)
        self.assertFalse(info['confirmed'])
        with self.assertRaises(ValueError):
            self.service.confirm_branding(key, str(self.media), revision)

    def test_individual_override_is_remembered(self):
        self.home()
        key = self.task['id']
        self.service.save_branding(key, str(self.media), self.template(), None)
        info = self.service.confirm_branding(key, None, None, False)
        self.assertTrue(info['declined'])
        self.assertFalse(info['confirmed'])
        self.assertTrue(self.service.folder_branding(key)['declined'])

    def test_inherit_nearest_parent_without_crossing_root(self):
        self.home()
        child = self.media / 'creator' / 'series';child.mkdir(parents=True)
        moved = child / 'film.mkv';self.file.rename(moved)
        self.asset.update(local_path=str(moved), plex_path='/plex/creator/series/film.mkv', fingerprint=test_curator.fingerprint(moved))
        with self.store.transaction():
            self.store.put('assets', self.asset['id'], self.asset)
        branding.write(self.media, self.template(), None)
        info = self.service.folder_branding(self.task['id'])
        self.assertEqual(info['suggested']['folder'], str(self.media))
        branding.write(child.parent, self.template(), None)
        self.assertEqual(self.service.folder_branding(self.task['id'])['suggested']['folder'], str(child.parent))
        self.assertNotIn(str(self.root), [r['folder'] for r in info['folders']])

    def test_outside_folder_and_stale_save_rejected(self):
        self.home()
        key = self.task['id']
        with self.assertRaises(ValueError):
            self.service.save_branding(key, str(self.root), self.template(), None)
        self.service.save_branding(key, str(self.media), self.template(), None)
        with self.assertRaises(ValueError):
            self.service.save_branding(key, str(self.media), self.template(), None)

    def test_invalid_or_symlink_sidecar_reported_without_overwrite(self):
        self.home()
        path = self.media / branding.NAME
        path.write_text('invalid')
        with self.assertRaises(ValueError):
            self.service.folder_branding(self.task['id'])
        path.unlink();path.symlink_to(self.root / 'outside.json')
        with self.assertRaises(ValueError):
            self.service.save_branding(self.task['id'], str(self.media), self.template(), None)

    def test_logo_reference_cannot_escape_folder(self):
        self.home()
        value = self.template();value['logo'] = '../logo.png'
        with self.assertRaises(ValueError):
            self.service.save_branding(self.task['id'], str(self.media), value, None)

    def test_logo_saved_and_retrieved(self):
        self.home()
        image = b'\x89PNG\r\n\x1a\nexample'
        info = self.service.save_branding(self.task['id'], str(self.media), self.template(), None, image)
        path = self.service.branding_logo(self.task['id'], str(self.media))
        self.assertEqual(path.read_bytes(), image)
        self.assertEqual(info['suggested']['template']['logo'], path.name)

    def test_artwork_endpoints_upload_select_and_verify(self):
        plex = Plex('http://localhost:32400', 'test')
        for kind, endpoint, field in [('cover', 'posters', 'poster'), ('background', 'arts', 'art'), ('logo', 'clearLogos', 'clearLogo'), ('square', 'squareArts', 'squareArt')]:
            with self.subTest(kind=kind), patch.object(plex, 'request', side_effect=[
                {'Metadata': [{'ratingKey': 'old'}]}, {},
                {'Metadata': [{'ratingKey': 'old'}, {'ratingKey': 'upload://new', 'selected': False}]}, {},
                {'Metadata': [{'ratingKey': 'upload://new', 'selected': True}]}
            ]) as request, patch.object(plex, 'item', return_value={'art': '/art', 'thumb': '/thumb', 'Image': [{'type': 'clearLogo', 'url': '/logo'}, {'type': 'backgroundSquare', 'url': '/square'}]}):
                plex.artwork('10', b'image', kind)
                calls = request.call_args_list
                self.assertEqual(calls[1].args, ('/library/metadata/10/' + endpoint, 'POST'))
                self.assertEqual(calls[1].kwargs['data'], b'image')
                self.assertTrue(calls[1].kwargs['ignore_body'])
                self.assertEqual(calls[3].args, ('/library/metadata/10/' + field, 'PUT'))
                self.assertEqual(calls[3].kwargs['params'], {'url': 'upload://new'})
        with self.assertRaises(ValueError):
            plex.artwork('10', b'image', 'invalid')

    def test_existing_artwork_field_cannot_falsely_verify_upload(self):
        plex = Plex('http://localhost:32400', 'test')
        old = {'Metadata': [{'ratingKey': 'upload://old', 'selected': True}]}
        with patch.object(plex, 'request', side_effect=[old, {}, old]) as request:
            with self.assertRaisesRegex(ValueError, 'did not identify'):
                plex.artwork('10', b'image')
        self.assertEqual(request.call_count, 3)

    def test_uploaded_but_not_selected_reports_failure(self):
        plex = Plex('http://localhost:32400', 'test')
        rows = {'Metadata': [{'ratingKey': 'upload://new', 'selected': False}]}
        with patch.object(plex, 'request', side_effect=[{}, {}, rows, {}, rows]):
            with self.assertRaisesRegex(ValueError, 'did not confirm'):
                plex.artwork('10', b'image')

    def test_successful_upload_response_does_not_require_json(self):
        import io
        plex = Plex('http://localhost:32400', 'test', transport=lambda *args, **kwargs: io.BytesIO(b'<Response code="200"/>'))
        self.assertEqual(plex.request('/library/metadata/10/posters', 'POST', data=b'image', ignore_body=True), {})

    def test_service_caches_artwork_and_does_not_require_media_mount(self):
        image = b'\x89PNG\r\n\x1a\nexample'
        self.plex.artwork = lambda *args: {'art': '/art', 'thumb': '/thumb', 'title': 'Film'}
        self.file.unlink()
        result = self.service.apply_cover(self.task['id'], image, 'background')
        self.assertTrue(result['selected'])
        self.assertEqual(self.store.get('assets', self.asset['id'])['item']['art'], '/art')
        self.assertEqual(json.loads(self.store.db.execute('SELECT data FROM events ORDER BY id DESC LIMIT 1').fetchone()[0])['action'], 'background uploaded and selected')

    def test_service_reports_and_records_artwork_failure(self):
        image = b'\x89PNG\r\n\x1a\nexample'
        self.plex.artwork = lambda *args: {'thumb': '/thumb'}
        with self.assertRaisesRegex(ValueError, 'requested artwork field'):
            self.service.apply_cover(self.task['id'], image, 'background')
        self.assertEqual(json.loads(self.store.db.execute('SELECT data FROM events ORDER BY id DESC LIMIT 1').fetchone()[0])['action'], 'background upload failed')

    def test_service_rejects_non_image_before_plex_write(self):
        with self.assertRaisesRegex(ValueError, 'JPEG or PNG'):
            self.service.apply_cover(self.task['id'], b'not an image')

    def test_settings_publish_five_editable_presets_and_validate_count(self):
        presets = self.service.state()['config']['branding_presets']
        self.assertEqual(len(presets), 5)
        changed = json.loads(json.dumps(presets));changed[0]['details'] = 'Custom prompt details'
        self.service.save_config({'branding_presets': changed[:4]})
        self.assertEqual(self.service.state()['config']['branding_presets'][0]['details'], 'Custom prompt details')
        self.service.save_config({'branding_presets': changed[:1]})
        with self.assertRaisesRegex(ValueError, 'one and fifty'):
            self.service.save_config({'branding_presets': []})
        duplicate = changed.copy();duplicate[-1] = changed[0]
        with self.assertRaisesRegex(ValueError, 'unique'):
            self.service.save_config({'branding_presets': duplicate})

    def test_remember_preset_in_parent_folder_migrates_legacy_creator(self):
        self.home()
        key = self.task['id']
        old = self.service.save_branding(key, str(self.media), self.template(), None)
        info = self.service.save_branding_choice(key, dict(folder=str(self.media), revision=old['suggested']['revision'],
            preset_id='sunlit', remember=True, creator='Example creator', use_folder=True))
        value = branding.read(self.media)
        self.assertEqual(value['version'], 2)
        self.assertEqual(value['preset_id'], 'sunlit')
        self.assertEqual(value['creator'], 'Example creator')
        self.assertTrue(info['confirmed'])
        self.assertNotIn('colors', value)

    def test_preset_override_does_not_change_folder_defaults(self):
        self.home()
        key = self.task['id']
        old = self.service.save_branding(key, str(self.media), self.template(), None)
        before = (self.media / branding.NAME).read_bytes()
        info = self.service.save_branding_choice(key, dict(folder=str(self.media), revision=old['suggested']['revision'],
            preset_id='minimal', remember=False, creator='Example creator', use_folder=False))
        self.assertEqual(info['preset_override'], 'minimal')
        self.assertFalse(info['confirmed'])
        self.assertEqual((self.media / branding.NAME).read_bytes(), before)

    def test_changed_or_removed_preset_reference_is_rejected(self):
        self.home()
        key = self.task['id']
        with self.assertRaisesRegex(ValueError, 'preset changed'):
            self.service.save_branding_choice(key, dict(folder=str(self.media), revision=None,
                preset_id='removed', remember=True, creator='', use_folder=False))
        with self.assertRaisesRegex(ValueError, 'defaults changed'):
            self.service.save_branding_choice(key, dict(folder=str(self.media), revision='old',
                preset_id='gritty', remember=True, creator='', use_folder=False))
        self.assertFalse((self.media / branding.NAME).exists())

    def test_folder_logo_reference_survives_preset_migration(self):
        self.home()
        key = self.task['id'];image = b'\x89PNG\r\n\x1a\nexample'
        old = self.service.save_branding(key, str(self.media), self.template(), None, image)
        logo = old['suggested']['template']['logo']
        self.service.save_branding_choice(key, dict(folder=str(self.media), revision=old['suggested']['revision'],
            preset_id='editorial', remember=True, creator='Example creator', use_folder=True))
        self.assertEqual(branding.read(self.media)['logo'], logo)
        self.assertEqual(self.service.branding_logo(key, str(self.media)).read_bytes(), image)

    def test_current_artwork_proxy_does_not_accept_remote_urls(self):
        import io
        image = b'\x89PNG\r\n\x1a\nexample'
        plex = Plex('http://localhost:32400', 'private', transport=lambda *a, **kw: io.BytesIO(image))
        with patch.object(plex, 'item', return_value={'thumb': '/library/metadata/10/thumb/1'}):
            self.assertEqual(plex.image('10', 'cover'), image)
        with patch.object(plex, 'item', return_value={'thumb': 'https://other.example/image'}):
            with self.assertRaisesRegex(ValueError, 'No current artwork'):
                plex.image('10', 'cover')

    def test_logo_and_square_metadata_paths_read_from_image_records(self):
        item={'Image':[{'type':'clearLogo','url':'/library/metadata/10/clearLogo/1'},
                       {'type':'backgroundSquare','url':'/library/metadata/10/squareArt/2'}]}
        self.assertEqual(Plex.artwork_path(item,'logo'),'/library/metadata/10/clearLogo/1')
        self.assertEqual(Plex.artwork_path(item,'square'),'/library/metadata/10/squareArt/2')
        self.assertIsNone(Plex.artwork_path({},'logo'))

    def test_logo_and_square_uploads_cache_native_image_metadata(self):
        image=b'\x89PNG\r\n\x1a\nexample'
        for kind, image_type in [('logo','clearLogo'),('square','backgroundSquare')]:
            with self.subTest(kind=kind):
                self.plex.artwork=lambda *args: {'title':'Film','Image':[{'type':image_type,'url':'/native/image'}]}
                result=self.service.apply_cover(self.task['id'],image,kind)
                self.assertEqual(result['observed_artwork'],'/native/image')
                self.assertEqual(self.store.get('assets',self.asset['id'])['item']['Image'][0]['type'],image_type)

    def test_logo_proxy_preserves_png_bytes(self):
        import io
        image=b'\x89PNG\r\n\x1a\ntransparent-png'
        plex=Plex('http://localhost:32400','token',transport=lambda *a,**kw:io.BytesIO(image))
        with patch.object(plex,'item',return_value={'Image':[{'type':'clearLogo','url':'/library/metadata/10/clearLogo/1'}]}):
            self.assertEqual(plex.image('10','logo'),image)

    def test_style_defaults_round_trip_without_changing_defaults_or_receipts(self):
        from copy import deepcopy
        defaults=deepcopy(branding.DEFAULT_PRESETS)
        receipt=deepcopy(self.service.get_task(self.task['id']))
        style=dict(defaults[0],id='custom-style',name='Custom',negative_prompt='No borders',model='mango-v3',ratio='16:9',resolution='1K')
        self.service.save_config({'branding_presets':defaults+[style]})
        self.assertEqual(self.service.state()['config']['branding_presets'][-1],style)
        self.service.save_config({'branding_presets':[dict(style,name='Renamed')]})
        self.assertEqual(self.service.get_task(self.task['id']),receipt)
        self.assertEqual(branding.DEFAULT_PRESETS,defaults)

    def test_invalid_style_defaults_are_rejected_before_storage(self):
        for override in [dict(ratio='invalid'),dict(resolution='8K'),dict(model=[]),dict(negative_prompt=1),dict(secret='not-allowed')]:
            with self.subTest(override=override),self.assertRaises(ValueError):
                self.service.save_config({'branding_presets':[dict(branding.DEFAULT_PRESETS[0],**override)]})
        self.assertEqual(self.service.state()['config']['branding_presets'],branding.DEFAULT_PRESETS)
