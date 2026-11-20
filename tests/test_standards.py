import sqlite3
import tempfile
import unittest
from pathlib import Path

from curator import migrations
from curator.errors import UserError
from curator.rules import library_kind
from curator.service import Service
from curator.standards import DEFAULTS, DIMENSIONS
from curator.store import Store


class Plex:
    def __init__(self, rows):
        self.rows = rows

    def libraries(self):
        return [dict(row) for row in self.rows]


def section(key, type_, agent):
    return dict(id='srv:' + key, server='srv', key=key, title='L' + key, type=type_, agent=agent, locations=[])


class LibraryKinds(unittest.TestCase):
    def test_follows_plex_library_types(self):
        self.assertEqual(library_kind(dict(type='movie', agent='tv.plex.agents.movie')), 'movie')
        self.assertEqual(library_kind(dict(type='show', agent='tv.plex.agents.series')), 'show')
        self.assertEqual(library_kind(dict(type='movie', agent='tv.plex.agents.none')), 'other_videos')
        self.assertEqual(library_kind(dict(type='movie', agent='com.plexapp.agents.none')), 'other_videos')
        self.assertEqual(library_kind(dict(type='show', agent='com.plexapp.agents.none')), 'show')


class Migrations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'state'

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_state_is_current_without_a_backup(self):
        store = Store(self.root)
        self.assertEqual(migrations.current_version(store.db), migrations.LATEST)
        self.assertIsNone(store.migration_backup)
        store.close()

    def test_pre_v2_state_is_backed_up_and_gains_library_kinds(self):
        store = Store(self.root)
        store.db.execute('DROP TABLE schema_version')
        with store.transaction():
            store.put('libraries', 'srv:1', dict(section('1', 'movie', 'tv.plex.agents.none'), profile='home'))
            store.put('libraries', 'srv:2', dict(section('2', 'show', 'tv.plex.agents.series'), profile='commercial'))
        store.close()
        store = Store(self.root)
        self.assertEqual(store.get('libraries', 'srv:1')['kind'], 'other_videos')
        self.assertEqual(store.get('libraries', 'srv:2')['kind'], 'show')
        self.assertEqual(store.get('libraries', 'srv:1')['profile'], 'home')
        backup = store.migration_backup
        self.assertTrue(backup.name.startswith('curator-schema-v0-'))
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        copy = sqlite3.connect(backup)
        self.assertNotIn('kind', copy.execute("SELECT data FROM libraries WHERE id='srv:1'").fetchone()[0])
        copy.close()
        store.close()
        store = Store(self.root)
        self.assertIsNone(store.migration_backup)
        store.close()

    def test_refuses_state_from_a_newer_curator(self):
        store = Store(self.root)
        store.db.execute('INSERT INTO schema_version VALUES(?, ?)', (migrations.LATEST + 1, 'later'))
        store.db.commit()
        store.close()
        with self.assertRaises(UserError):
            Store(self.root)

    def test_failed_migration_keeps_the_previous_version(self):
        store = Store(self.root)
        store.db.execute('DELETE FROM schema_version WHERE version = 2')
        store.db.commit()
        store.close()

        def broken(store):
            store.put('settings', 'partial', True)
            raise RuntimeError('boom')

        original = migrations.MIGRATIONS
        migrations.MIGRATIONS = ((1, migrations._baseline), (2, broken))
        try:
            with self.assertRaises(RuntimeError):
                Store(self.root)
        finally:
            migrations.MIGRATIONS = original
        store = Store(self.root)
        self.assertIsNone(store.get('settings', 'partial'))
        self.assertEqual(migrations.current_version(store.db), 2)
        store.close()


class Standards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'state')
        rows = [
            section('1', 'movie', 'tv.plex.agents.movie'),
            section('2', 'show', 'tv.plex.agents.series'),
            section('3', 'movie', 'tv.plex.agents.none'),
        ]
        self.service = Service(self.store, lambda *args: Plex(rows))
        self.service.connect()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_connect_records_kind_and_new_other_videos_start_as_home(self):
        libraries = {row['id']: row for row in self.store.all('libraries')}
        self.assertEqual([libraries[k]['kind'] for k in ('srv:1', 'srv:2', 'srv:3')], ['movie', 'show', 'other_videos'])
        self.assertEqual(
            [libraries[k]['profile'] for k in ('srv:1', 'srv:2', 'srv:3')], ['commercial', 'commercial', 'home']
        )

    def test_reconnect_keeps_operator_profile_and_overrides(self):
        self.service.save_library('srv:3', dict(profile='commercial', mappings=[], themes=[]))
        self.service.save_library_overrides('srv:1', 0, {'artwork': {'required': ['poster']}})
        self.service.connect()
        self.assertEqual(self.service.library('srv:3')['profile'], 'commercial')
        self.assertEqual(self.service.library_standard('srv:1')['overrides'], {'artwork': {'required': ['poster']}})

    def test_every_type_has_a_complete_valid_default(self):
        standards = self.service.standards()
        self.assertEqual(set(standards['types']), {'movie', 'show', 'other_videos'})
        for kind, row in standards['types'].items():
            self.assertEqual(row['revision'], 0)
            self.assertFalse(row['customized'])
            self.assertEqual(tuple(row['values']), DIMENSIONS)
        self.assertEqual(standards['types']['other_videos']['label'], 'Other Videos')
        self.assertEqual(standards['libraries']['srv:3']['values'], DEFAULTS['other_videos'])

    def test_saving_a_type_standard_applies_to_every_library_of_that_type(self):
        values = self.service.standards()['types']['movie']['values']
        values['encoding']['max_mbps_1080'] = 12
        saved = self.service.save_type_standard('movie', 0, values)
        self.assertEqual((saved['revision'], saved['customized']), (1, True))
        self.assertEqual(self.service.library_standard('srv:1')['values']['encoding']['max_mbps_1080'], 12)
        self.assertIsNone(self.service.library_standard('srv:2')['values']['encoding']['max_mbps_1080'])
        with self.assertRaises(UserError):
            self.service.save_type_standard('movie', 0, values)

    def test_library_overrides_keep_only_differences(self):
        result = self.service.save_library_overrides(
            'srv:2',
            0,
            {'artwork': {'required': ['background', 'poster'], 'poster_ratio': '2:3'}, 'cast': {'enabled': False}},
        )
        # The artwork values equal the type standard, so only the cast change is kept.
        self.assertEqual(result['overrides'], {'cast': {'enabled': False}})
        self.assertFalse(result['values']['cast']['enabled'])
        # A later type change still reaches fields the library did not override.
        values = self.service.standards()['types']['show']['values']
        values['cast']['mode'] = 'known_people'
        self.service.save_type_standard('show', 0, values)
        self.assertEqual(
            self.service.library_standard('srv:2')['values']['cast'], {'enabled': False, 'mode': 'known_people'}
        )
        with self.assertRaises(UserError):
            self.service.save_library_overrides('srv:2', 0, {})

    def test_rejects_invalid_standards(self):
        good = self.service.standards()['types']['movie']['values']
        bad = [
            {**good, 'extra': {}},
            {k: v for k, v in good.items() if k != 'cast'},
            {**good, 'cast': {'enabled': True, 'mode': 'everyone'}},
            {**good, 'metadata': {**good['metadata'], 'required': ['summary', 'rating_key']}},
            {**good, 'encoding': {**good['encoding'], 'max_mbps_4k': 0}},
            {**good, 'encoding': {**good['encoding'], 'max_mbps_4k': True}},
            {**good, 'upscaling': {**good['upscaling'], 'enabled': 'yes'}},
        ]
        for values in bad:
            with self.subTest(values=values), self.assertRaises(UserError):
                self.service.save_type_standard('movie', 0, values)
        for kind, revision in (('music', 0), ('movie', '0'), ('movie', True)):
            with self.subTest(kind=kind, revision=revision), self.assertRaises(UserError):
                self.service.save_type_standard(kind, revision, good)
        self.assertEqual(self.service.standards()['types']['movie']['revision'], 0)


if __name__ == '__main__':
    unittest.main()
