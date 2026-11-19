import base64
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import test_curator
from test_artwork_managers import png
from curator.mage_catalog import models, resolve, request_body
from curator.mage import Mage
from curator.image_contract import editor_png


def catalog():
    props = {
        'prompt': {'type': 'string'},
        'model_id': {'enum': ['mango-v4', 'mango-v2', 'mango-v3']},
        'aspect_ratio': {'enum': ['2:3', '16:9', '1:1']},
        'resolution': {'enum': ['1K', '2K', '3K', '4K']},
    }
    return {
        'architectures': [
            {
                'id': 'mango',
                'name': 'Mango',
                'type': 'image',
                'input_schema': {'properties': props},
                'base_config': {'model_id': 'mango-v4', 'aspect_ratio': '2:3', 'resolution': '2K'},
                'gems': 42,
                'options_by_model': {
                    'mango-v2': {'resolution': ['2K', '3K', '4K']},
                    'mango-v3': {'resolution': ['1K', '2K']},
                },
            },
            {
                'id': 'other_image',
                'name': 'Other image',
                'type': 'image',
                'input_schema': {
                    'required': ['prompt'],
                    'properties': {
                        'prompt': {'type': 'string'},
                        'aspect_ratio': {'enum': ['1:1', '2:3']},
                        'reference_image': {'type': 'string'},
                    },
                },
                'image_inputs': {'references': {'field': 'reference_image'}},
                'max_images': 1,
                'base_config': {'aspect_ratio': '1:1'},
                'gems': 5,
            },
            {'id': 'video', 'type': 'video', 'input_schema': {'properties': props}},
            {
                'id': 'sized_image',
                'name': 'Sized image',
                'type': 'image',
                'input_schema': {
                    'required': ['prompt', 'width', 'height'],
                    'properties': {
                        'prompt': {'type': 'string'},
                        'width': {'type': 'integer', 'minimum': 256, 'maximum': 2048, 'multipleOf': 8},
                        'height': {'type': 'integer', 'minimum': 256, 'maximum': 2048, 'multipleOf': 8},
                    },
                },
            },
        ]
    }


class ApprovedArtworkEditors(unittest.TestCase):
    setUp = test_curator.Workflows.setUp
    tearDown = test_curator.Workflows.tearDown

    def test_catalog_is_image_only_prioritizes_mango_and_uses_per_model_options(self):
        rows = models(catalog())
        self.assertEqual([r['id'] for r in rows[:3]], ['mango-v2', 'mango-v3', 'mango-v4'])
        self.assertNotIn('video', [r['id'] for r in rows])
        self.assertEqual(rows[0]['resolutions'], ['2K', '3K', '4K'])
        architecture, row = resolve(catalog(), 'mango-v2')
        with self.assertRaisesRegex(ValueError, 'resolution'):
            request_body(architecture, row, {'prompt': 'Test', 'ratio': '2:3', 'resolution': '1K'}, [])
        body = request_body(architecture, row, {'prompt': 'Test', 'ratio': '2:3', 'resolution': '4K'}, [])
        self.assertEqual(body['model_id'], 'mango-v2')
        self.assertEqual(body['resolution'], '4K')

    def test_other_models_keep_their_architecture_and_reference_field_in_quote(self):
        provider = Mage(self.store.root)
        provider.save_key('fixture')
        provider.get = lambda path: catalog()
        with patch('curator.mage_mcp.MagePricing') as pricing:
            pricing.return_value.quote.return_value = {'gems': 6, 'body': {}, 'architecture': 'other_image'}
            provider.quote(
                {'model': 'other_image', 'prompt': 'Test', 'ratio': '2:3', 'resolution': '', 'negative_prompt': ''},
                1,
                ['data:image/png;base64,fixture'],
            )
            body, architecture = pricing.return_value.quote.call_args.args
        self.assertEqual(architecture, 'other_image')
        self.assertEqual(body['reference_image'], 'data:image/png;base64,fixture')
        self.assertNotIn('image', body)
        self.assertNotIn('model_id', body)
        self.assertNotIn('resolution', body)

    def test_width_height_models_preserve_ratio_and_schema_bounds(self):
        architecture, row = resolve(catalog(), 'sized_image')
        body = request_body(architecture, row, {'prompt': 'Test', 'ratio': '2:3', 'resolution': ''}, [])
        self.assertEqual(body['width'] * 3, body['height'] * 2)
        self.assertLessEqual(body['height'], 2048)
        self.assertEqual(body['width'] % 8, 0)
        with self.assertRaises(ValueError):
            resolve(catalog(), 'unknown')

    def test_style_save_is_versioned_and_never_rewrites_existing_plans(self):
        task = self.service.artwork_plan([self.asset['id']], 'cover', 'gritty')['tasks'][0]
        before = self.service.artwork_style_guides()
        styles = copy.deepcopy(before['styles'])
        styles[0]['name'] = 'Changed style'
        styles[0]['details'] = 'New future prompt'
        saved = self.service.save_artwork_style_guides(before['revision'], styles)
        self.assertNotEqual(saved['revision'], before['revision'])
        self.assertEqual(self.service.get_task(task['id'])['plan'], task['plan'])
        self.assertFalse(self.plex.writes)
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.service.save_artwork_style_guides(before['revision'], styles)
        with self.assertRaises(ValueError):
            self.service.save_artwork_style_guides(saved['revision'], [])

    def test_person_generation_and_save_belong_to_profile_not_credits(self):
        created = self.service.create_cast_profile('Test Person')
        person = self.service.person_artwork_target(created['profile_id'], self.lib['id'])['asset']
        original = self.store.all('assets')
        task = self.service.artwork_preview([person['id']], 'square', '1:1', {person['id']: png(12, 12)})['tasks'][0]
        self.service.publish_artwork(task, person)
        self.assertEqual(self.service.get_task(task['id'])['status'], 'applied')
        self.assertEqual(self.service.cast_profiles()[0]['revision'], 2)
        self.assertFalse(self.plex.writes)
        self.assertEqual(original, self.store.all('assets'))
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.service.publish_artwork(task, person)
        generated = self.service.artwork_plan([person['id']], 'square', 'gritty')['tasks'][0]
        self.assertEqual(generated['plan']['profile_revision'], 2)
        self.assertEqual(generated['plan']['settings']['ratio'], '1:1')
        with self.assertRaisesRegex(ValueError, 'square'):
            self.service.artwork_plan([person['id']], 'cover', 'gritty')

    def test_shared_background_rejects_changed_current_image_before_publication(self):
        with self.assertRaisesRegex(ValueError, 'changed after display'):
            self.service.shared_artwork_preview([self.asset['id']], png(16, 9), expected={self.asset['id']: 'f' * 64})
        self.assertFalse(self.plex.writes)
        retained = [t for t in self.store.all('tasks') if t['kind'] == 'artwork']
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0]['status'], 'awaiting_review')
        folder = next(f for f in self.service.folder_nodes() if f['direct_count'])
        result = self.service.folder_artwork_scope(folder['id'], False)
        self.assertEqual(result['assets'][0]['id'], self.asset['id'])
        with self.assertRaises(ValueError):
            self.service.folder_artwork_scope(folder['id'], 'true')
        with self.assertRaises(ValueError):
            self.service.shared_artwork_preview(
                ['outside'], png(16, 9), scope={'folder': folder['id'], 'recursive': False}
            )

    def test_local_render_is_queued_and_rejects_unknown_font_before_any_work(self):
        with (
            patch('curator.local_artwork.magick', return_value='/fixture/magick'),
            patch.object(self.service, 'local_font_paths', return_value={'HostFont': '/fixture/font.ttf'}),
            patch.object(self.service, 'start_file_queue') as start,
        ):
            with self.assertRaisesRegex(ValueError, 'font'):
                self.service.local_artwork(
                    {
                        'mode': 'logo_text',
                        'asset': self.asset['id'],
                        'text': 'Test',
                        'font': '/etc/passwd',
                        'color': '#ffffff',
                    }
                )
            start.assert_not_called()
            result = self.service.local_artwork(
                {'mode': 'logo_text', 'asset': self.asset['id'], 'text': 'Test', 'font': 'HostFont', 'color': '#ffffff'}
            )
            self.assertEqual(result['phase'], 'waiting')
            self.assertEqual(result['operation'], 'local_artwork')
            start.assert_called_once()
        self.assertFalse(self.plex.writes)

    def test_portrait_derivative_retains_original_and_square_geometry(self):
        source = self.service._folder_photo(encoded=png(12, 20))
        commands = []

        def render(command):
            commands.append(command)
            Path(command[-1].removeprefix('PNG32:')).write_bytes(base64.b64decode(png(24, 24)))
            return b''

        with (
            patch('curator.local_artwork.magick', return_value='/fixture/magick'),
            patch('curator.local_artwork.execute', side_effect=render),
        ):
            result = self.service.render_local_artwork({'mode': 'portrait', 'source': source})
        self.assertEqual(result['original'], source)
        self.assertEqual(result['width'], result['height'])
        self.assertIn('-extent', commands[0])
        self.assertNotIn('-crop', commands[0])
        self.assertEqual(self.service.folder_image(source), base64.b64decode(png(12, 20)))
        self.assertFalse(self.plex.writes)

    def test_text_is_literal_file_input_and_font_paths_are_not_caller_controlled(self):
        commands = []

        def render(command):
            commands.append(command)
            literal = next(v for v in command if v.startswith('label:@'))
            self.assertEqual(Path(literal[7:]).read_text(), '@private % title')
            Path(command[-1].removeprefix('PNG32:')).write_bytes(base64.b64decode(png(30, 12, 128)))
            return b''

        with (
            patch('curator.local_artwork.magick', return_value='/fixture/magick'),
            patch.object(self.service, 'local_font_paths', return_value={'HostFont': '/fixture/font.ttf'}),
            patch('curator.local_artwork.execute', side_effect=render),
        ):
            result = self.service.render_local_artwork(
                {'mode': 'logo_text', 'font': 'HostFont', 'text': '@private % title', 'color': '#ffffff'}
            )
        self.assertEqual(commands[0][commands[0].index('-font') + 1], '/fixture/font.ttf')
        self.assertEqual(result['font'], 'HostFont')
        self.assertEqual(result['text'], '@private % title')
        with self.assertRaisesRegex(ValueError, 'visible pixels'):
            editor_png(png(10, 10, 0), logo=True)
