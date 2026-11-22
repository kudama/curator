import copy
from pathlib import Path
import tempfile
import unittest

from curator.errors import UserError
from curator.library_types import observe_library, suggested_kind
from curator.service import Service
from curator.standards import DEFAULTS, type_digest
from curator.store import Store
from test_standards import Plex, section


class Compatibility(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'state'
        self.store = Store(self.root)
        self.addCleanup(lambda: self.store.close())
        self.rows = [section('1', 'movie', 'tv.plex.agents.none')]
        self.service = Service(self.store, lambda *args: Plex(self.rows))
        self.service.connect()

    def test_first_connect_hint_does_not_change_raw_observation_or_tv_type(self):
        for scanner in ('Plex Video Files', 'Plex Video Files Scanner', ' PLEX   Video Files '):
            fresh = dict(section('2', 'movie', 'nfo-agent'), scanner=scanner)
            row = observe_library(fresh)
            self.assertEqual((row['observed_kind'], row['standard_kind']), ('movie', 'other_videos'))
            self.assertEqual(suggested_kind(dict(fresh, type='show')), 'show')
        self.assertEqual(suggested_kind(dict(fresh, scanner='Plex Movie')), 'movie')

    def test_agent_reconnect_and_location_refresh_keep_chosen_standard_and_overrides(self):
        self.service.save_library_overrides('srv:1', 0, {'cast': {'enabled': False}})
        before = self.service.library_standard('srv:1')
        self.rows[0].update(agent='nfo-agent', scanner='Plex Video Files')
        self.service.connect()
        self.service.refresh_library_locations('srv:1')
        after = self.service.library_standard('srv:1')
        self.assertEqual(after['kind'], 'other_videos')
        self.assertEqual(after['observed_kind'], 'movie')
        self.assertEqual(after['values'], before['values'])
        self.assertEqual(after['revision'], before['revision'])

    def test_profile_migration_preserves_tv_type_custom_fields_overrides_and_receipts(self):
        custom = copy.deepcopy(DEFAULTS['show'])
        custom['metadata']['required'] = ['studio']
        custom['encoding']['max_mbps_1080'] = 35
        library = dict(
            section('2', 'show', 'tv.plex.agents.series'),
            kind='show',
            profile='home',
            standard_overrides={'cast': {'enabled': False}},
            standard_revision=4,
        )
        receipt = dict(
            id='retained',
            asset='a',
            library='srv:2',
            kind='upscale',
            status='queued',
            version=7,
            approval=7,
            plan={'target': 'old-reviewed-target'},
            output_hash='retained-hash',
        )
        with self.store.transaction():
            self.store.put(
                'settings',
                'standard:show',
                dict(id='standard:show', record_type='library_standard', kind='show', revision=3, values=custom),
            )
            self.store.put('libraries', library['id'], library)
            self.store.put('tasks', receipt['id'], receipt)
            self.store.db.execute('DELETE FROM schema_version WHERE version > 4')
        self.store.close()
        self.store = Store(self.root)
        self.assertIsNotNone(self.store.migration_backup)
        saved = self.store.get('libraries', 'srv:2')
        self.assertEqual(saved['standard_kind'], 'show')
        self.assertEqual(saved['standard_overrides']['cast']['enabled'], False)
        self.assertEqual(saved['standard_overrides']['artwork']['enabled'], True)
        self.assertEqual(saved['standard_overrides']['metadata'], {'local_ai_suggestions': True})
        self.assertEqual(saved['standard_overrides']['encoding'], {'preserve_originals': True})
        self.assertEqual(saved['standard_revision'], 5)
        self.assertEqual(self.store.get('settings', 'standard:show')['values'], custom)
        self.assertEqual(self.store.get('tasks', receipt['id']), receipt)
        self.store.close()
        self.store = Store(self.root)
        self.assertIsNone(self.store.migration_backup)
        self.assertEqual(self.store.get('libraries', 'srv:2'), saved)

    def test_movie_home_migration_creates_overrides_without_reclassifying(self):
        with self.store.transaction():
            self.store.put(
                'libraries', 'srv:3', dict(section('3', 'movie', 'tv.plex.agents.movie'), kind='movie', profile='home')
            )
            self.store.db.execute('DELETE FROM schema_version WHERE version > 4')
        self.store.close()
        self.store = Store(self.root)
        row = self.store.get('libraries', 'srv:3')
        self.assertEqual((row['standard_kind'], row['kind']), ('movie', 'movie'))
        self.assertTrue(row['standard_overrides']['metadata']['local_ai_suggestions'])
        self.assertEqual(row['standard_overrides']['metadata']['required'], ['summary', 'originally_available_at'])

    def change_data(self, kind='movie'):
        before = self.service.library_standard('srv:1')
        parent = self.service.type_standard(kind)
        return dict(
            library='srv:1',
            revision=before['revision'],
            before_kind=before['kind'],
            before_type_revision=before['type_revision'],
            before_type_digest=before['type_digest'],
            kind=kind,
            type_revision=parent['revision'],
            type_digest=type_digest(parent['values']),
        )

    def test_explicit_type_review_preserves_overrides_and_noop_history(self):
        self.service.save_library_overrides('srv:1', 0, {'cast': {'enabled': False}})
        data = self.change_data()
        result = self.service.save_library_standard_kind(data)
        self.assertEqual(result['kind'], 'movie')
        self.assertEqual(result['revision'], data['revision'] + 1)
        self.assertEqual(result['overrides'], {'cast': {'enabled': False}})
        count = len(self.store.curator_history())
        self.service.save_library_standard_kind(self.change_data())
        self.assertEqual(len(self.store.curator_history()), count)
        with self.assertRaises(UserError):
            self.service.save_library_standard_kind(data)

    def test_either_parent_change_or_override_change_refuses_type_review(self):
        for target in ('movie', 'other_videos'):
            data = self.change_data()
            parent = self.service.type_standard(target)
            values = copy.deepcopy(parent['values'])
            values['metadata']['required'] = ['studio']
            self.service.save_type_standard(target, parent['revision'], values)
            with self.assertRaisesRegex(UserError, 'reviewed standard changed'):
                self.service.save_library_standard_kind(data)
            self.assertEqual(self.service.library_standard('srv:1')['kind'], 'other_videos')
        data = self.change_data()
        self.service.save_library_overrides('srv:1', 0, {'cast': {'enabled': False}})
        with self.assertRaises(UserError):
            self.service.save_library_standard_kind(data)

    def test_malformed_type_review_does_not_write(self):
        data = self.change_data()
        for field in data:
            partial = dict(data)
            partial.pop(field)
            with self.assertRaises(UserError):
                self.service.save_library_standard_kind(partial)
        bad = dict(data, revision=True)
        with self.assertRaises(UserError):
            self.service.save_library_standard_kind(bad)
        self.assertEqual(self.service.library_standard('srv:1')['kind'], 'other_videos')
