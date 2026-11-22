import base64
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import test_curator
from test_artwork_managers import png
from curator.errors import UserError
from curator.nfo_export import movie_xml, parse_nfo
from curator.service import Service


class NfoPackage(unittest.TestCase):
    setUp = test_curator.Workflows.setUp
    tearDown = test_curator.Workflows.tearDown

    def art(self, kinds=('cover', 'background', 'square', 'logo')):
        for kind in kinds:
            field = dict(cover='thumb', background='art', square='squareArt', logo='clearLogo')[kind]
            self.plex.rows[0][field] = '/library/metadata/10/' + kind
        self.asset['item'] = copy.deepcopy(self.plex.rows[0])
        with self.store.transaction():
            self.store.put('assets', self.asset['id'], self.asset)
        self.plex.image = lambda key, kind: base64.b64decode(
            png(16 if kind == 'background' else 10, 9 if kind == 'background' else 15 if kind == 'cover' else 10)
        )

    def preview(self, **options):
        return self.service.create_nfo_preview(
            dict(library=self.lib['id'], scope='selected', assets=[self.asset['id']], **options), background=False
        )

    def queue(self, plan, updates=None):
        with patch.object(self.service, 'start_file_queue') as start:
            result = self.service.queue_nfo_export(
                dict(id=plan['id'], revision=plan['review_revision'], assets=[self.asset['id']], updates=updates or [])
            )
        start.assert_not_called()
        return result

    def execute(self, plan):
        queued = self.queue(plan)
        result = self.service.execute_nfo_export(queued['id'])
        return self.service.nfo_manifest(result['manifest'])

    def test_fresh_saved_metadata_and_all_selected_images_package(self):
        self.plex.rows[0].update(
            title='Family & pets',
            summary='Saved <description>',
            Role=[dict(tag='Person', role='Self')],
            Genre=[dict(tag='Home')],
        )
        self.art()
        before = sorted(p.name for p in self.media.iterdir())
        plan = self.preview()
        self.assertEqual(plan['phase'], 'ready')
        self.assertEqual(sorted(p.name for p in self.media.iterdir()), before)
        self.assertEqual(self.plex.writes, [])
        self.assertEqual(
            [f['kind'] for f in plan['items'][0]['files']], ['nfo', 'cover', 'background', 'logo', 'square']
        )
        result = self.execute(plan)
        self.assertEqual(result['phase'], 'complete')
        xml = ET.fromstring((self.media / 'film.nfo').read_bytes())
        self.assertEqual(xml.findtext('title'), 'Family & pets')
        self.assertEqual(xml.findtext('plot'), 'Saved <description>')
        self.assertEqual(xml.findtext('actor/name'), 'Person')
        for name in ['poster.png', 'background.png', 'square.png', 'logo.png']:
            self.assertTrue((self.media / name).read_bytes().startswith(b'\x89PNG'))
        self.assertEqual(self.file.read_bytes(), b'original-video')
        self.assertEqual(self.plex.writes, [])
        self.assertEqual(self.execute(self.preview())['phase'], 'complete')

    def test_changed_live_metadata_blocks_instead_of_exporting_stale_values(self):
        self.plex.rows[0]['summary'] = 'New live value'
        plan = self.preview()
        self.assertEqual(plan['items'][0]['phase'], 'blocked')
        self.assertIn('differs', plan['items'][0]['reason'])
        self.assertFalse((self.media / 'film.nfo').exists())

    def test_source_artwork_or_mapping_change_after_review_refused(self):
        self.art()
        plan = self.preview()
        self.plex.rows[0]['thumb'] += '/changed'
        with self.assertRaisesRegex(UserError, 'source changed'):
            self.queue(plan)
        self.plex.rows[0]['thumb'] = self.asset['item']['thumb']
        queued = self.queue(plan)
        self.plex.image = lambda *a: base64.b64decode(png(20, 20))
        result = self.service.execute_nfo_export(queued['id'])
        row = self.service.nfo_manifest(result['manifest'])['items'][0]
        self.assertEqual(row['phase'], 'failed')
        self.assertTrue((self.media / 'film.nfo').exists())
        self.assertFalse((self.media / 'poster.png').exists())

    def test_existing_third_party_nfo_and_art_kept(self):
        self.art()
        original = b'<?xml version="1.0"?><movie><title>Other tool</title><custom>keep</custom></movie>'
        (self.media / 'film.nfo').write_bytes(original)
        (self.media / 'poster.png').write_bytes(b'other-tool-image')
        plan = self.preview()
        self.assertEqual(plan['items'][0]['files'][0]['action'], 'kept')
        self.assertEqual(self.execute(plan)['phase'], 'partial')
        self.assertEqual((self.media / 'film.nfo').read_bytes(), original)
        self.assertEqual((self.media / 'poster.png').read_bytes(), b'other-tool-image')

    def test_own_nfo_update_requires_separate_approval_and_retains_original(self):
        self.art()
        self.execute(self.preview())
        original = (self.media / 'film.nfo').read_bytes()
        self.plex.rows[0]['summary'] = 'Saved edit'
        self.art()
        plan = self.preview()
        self.assertEqual(plan['items'][0]['files'][0]['action'], 'update')
        self.execute(plan)
        self.assertEqual((self.media / 'film.nfo').read_bytes(), original)
        plan = self.preview()
        queued = self.queue(plan, updates=[self.asset['id']])
        self.service.execute_nfo_export(queued['id'])
        self.assertEqual(ET.fromstring((self.media / 'film.nfo').read_bytes()).findtext('plot'), 'Saved edit')
        self.assertEqual(next(self.media.glob('.curator-retained-*/reviewed-original')).read_bytes(), original)

    def test_shared_folder_blocks_art_but_allows_filename_matched_nfo(self):
        self.art()
        (self.media / 'unscanned.mp4').write_bytes(b'other')
        plan = self.preview()
        self.assertTrue(all(f['action'] == 'blocked' for f in plan['items'][0]['files'][1:]))
        self.assertEqual(self.execute(plan)['phase'], 'partial')
        self.assertTrue((self.media / 'film.nfo').exists())
        self.assertFalse((self.media / 'poster.png').exists())

    def test_new_shared_folder_and_alternate_art_after_preview_blocked(self):
        self.art()
        plan = self.preview()
        queued = self.queue(plan)
        (self.media / 'poster.jpg').write_bytes(b'foreign')
        result = self.service.execute_nfo_export(queued['id'])
        self.assertEqual(self.service.nfo_manifest(result['manifest'])['items'][0]['phase'], 'failed')
        self.assertFalse((self.media / 'poster.png').exists())
        self.assertEqual((self.media / 'poster.jpg').read_bytes(), b'foreign')

    def test_restart_holds_job_and_manifest_without_replay(self):
        queued = self.queue(self.preview())
        service = Service(self.store, lambda *args: self.plex)
        self.assertEqual(service.nfo_manifest(queued['id'])['phase'], 'interrupted')
        self.assertEqual(service.file_operation(queued['job'])['phase'], 'interrupted')
        self.assertFalse((self.media / 'film.nfo').exists())
        with self.assertRaises(UserError):
            service.execute_nfo_export(queued['id'])

    def test_tv_multipart_wrong_identity_missing_mount_are_visible_blocks(self):
        for change in [
            dict(type='episode'),
            dict(ratingKey='11'),
            dict(Media=[{'Part': [{'file': '/plex/film.mkv'}, {'file': '/plex/part2.mkv'}]}]),
        ]:
            original = copy.deepcopy(self.plex.rows[0])
            self.plex.rows[0].update(change)
            self.assertEqual(self.preview()['items'][0]['phase'], 'blocked')
            self.plex.rows[0] = original
        self.file.unlink()
        self.assertEqual(self.preview()['items'][0]['phase'], 'blocked')

    def test_queue_repeated_approval_is_not_duplicated_and_stale_revision_rejected(self):
        plan = self.preview()
        with self.assertRaises(UserError):
            self.service.queue_nfo_export(dict(id=plan['id'], revision='stale', assets=[self.asset['id']]))
        self.queue(plan)
        with self.assertRaises(UserError):
            self.queue(plan)
        self.assertEqual(len([j for j in self.service.file_jobs() if j['operation'] == 'nfo_export']), 1)

    def test_scope_filters_and_cast_omission_are_explicit(self):
        self.plex.rows[0]['Role'] = [dict(tag='Person', role='Self', thumb='/library/metadata/10/thumb')]
        self.art(kinds=('cover',))
        plan = self.preview()
        self.assertTrue(any('Portrait' in warning for warning in plan['items'][0]['warnings']))
        self.execute(plan)
        self.assertEqual(self.preview(filter='missing')['items'][0]['phase'], 'skipped')
        self.assertEqual(
            self.service.create_nfo_preview(
                dict(library=self.lib['id'], scope='folder', folder='/plex'), background=False
            )['phase'],
            'ready',
        )
        self.assertEqual(
            self.service.create_nfo_preview(dict(library=self.lib['id'], scope='library'), background=False)['phase'],
            'ready',
        )


class XmlSafety(unittest.TestCase):
    def test_deterministic_utf8_escaping_unknown_xml_and_identifiers_preserved(self):
        item = dict(
            title='Café <&>', summary='Saved', Role=[dict(tag='Person', role='Self')], Guid=[dict(id='imdb://tt123')]
        )
        previous = b'<movie><title>Old</title><uniqueid type="tmdb">42</uniqueid><custom test="1">untouched</custom><!--keep--></movie>'
        raw = movie_xml(item, previous)
        self.assertEqual(raw, movie_xml(item, previous))
        root = ET.fromstring(raw)
        self.assertEqual(root.findtext('custom'), 'untouched')
        self.assertEqual(
            [(e.get('type'), e.text) for e in root.findall('uniqueid')], [('tmdb', '42'), ('imdb', 'tt123')]
        )
        self.assertIn(b'<!--keep-->', raw)
        self.assertEqual(root.findtext('title'), 'Café <&>')
        with self.assertRaises(UserError):
            movie_xml(dict(Guid=[dict(id='tmdb://43')]), previous)

    def test_dtd_entities_utf16_and_control_characters_rejected(self):
        bad = '<!DOCTYPE movie [<!ENTITY x "expand">]><movie><title>&x;</title></movie>'
        for raw in [bad.encode(), bad.encode('utf-16'), b'<movie>incomplete', b'<tvshow/>']:
            with self.subTest(raw=raw[:10]), self.assertRaises(UserError):
                parse_nfo(raw)
        with self.assertRaises(UserError):
            movie_xml(dict(title='bad\x01'))
