import copy
import concurrent.futures
import http.cookiejar
import json
import sqlite3
import tempfile
import unittest
import threading
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPCookieProcessor, Request
from pathlib import Path

from curator import migrations
from curator.errors import UserError
from curator.rules import library_kind
from curator.service import Service
from curator.standards import DEFAULTS, DIMENSIONS
from curator.store import Store
from curator.web import App


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

    def test_portrait_upgrade_preserves_other_preferences_and_job_receipts(self):
        store = Store(self.root)
        values = copy.deepcopy(DEFAULTS['other_videos'])
        values['artwork']['poster_ratio'] = '16:9'
        values['cast']['enabled'] = False
        record = dict(
            id='standard:other_videos', record_type='library_standard', kind='other_videos', values=values, revision=2
        )
        library = dict(
            section('1', 'movie', 'tv.plex.agents.none'),
            profile='home',
            standard_overrides={'artwork': {'poster_ratio': '16:9', 'enabled': False}},
            standard_revision=5,
        )
        receipt = dict(
            id='old',
            kind='mage_generation',
            status='recommendation',
            plan={'kind': 'cover', 'settings': {'ratio': '16:9'}},
        )
        with store.transaction():
            store.put('settings', record['id'], record)
            store.put('libraries', library['id'], library)
            store.put('tasks', receipt['id'], receipt)
            store.db.execute('DELETE FROM schema_version WHERE version > 3')
        store.close()
        store = Store(self.root)
        saved = store.get('settings', record['id'])
        self.assertEqual(saved['values']['artwork']['poster_ratio'], '2:3')
        self.assertFalse(saved['values']['cast']['enabled'])
        self.assertEqual(saved['revision'], 3)
        saved_library = store.get('libraries', library['id'])
        self.assertEqual(saved_library['standard_overrides']['artwork'], {'poster_ratio': '2:3', 'enabled': False})
        self.assertEqual(saved_library['standard_revision'], 6)
        self.assertEqual(saved_library['profile'], 'home')
        self.assertEqual(store.get('tasks', 'old'), receipt)
        self.assertIsNotNone(store.migration_backup)
        store.close()
        store = Store(self.root)
        self.assertIsNone(store.migration_backup)
        self.assertEqual(store.get('settings', record['id'])['revision'], 3)
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
        store.db.execute('DELETE FROM schema_version WHERE version > 1')
        store.db.commit()
        store.close()

        def broken(store):
            store.put('settings', 'partial', True)
            raise RuntimeError('boom')

        original = migrations.MIGRATIONS
        migrations.MIGRATIONS = (original[0], (2, broken))
        try:
            with self.assertRaises(RuntimeError):
                Store(self.root)
        finally:
            migrations.MIGRATIONS = original
        store = Store(self.root)
        self.assertIsNone(store.get('settings', 'partial'))
        self.assertEqual(migrations.current_version(store.db), migrations.LATEST)
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
        self.service.save_library_overrides('srv:1', 0, {'artwork': {'enabled': True}})
        self.service.connect()
        self.assertEqual(self.service.library('srv:3')['profile'], 'commercial')
        self.assertEqual(self.service.library_standard('srv:1')['overrides'], {'artwork': {'enabled': True}})

    def test_every_type_has_a_complete_valid_default(self):
        standards = self.service.standards()
        self.assertEqual(set(standards['types']), {'movie', 'show', 'other_videos'})
        for kind, row in standards['types'].items():
            self.assertEqual(row['values']['artwork']['poster_ratio'], '2:3')
            self.assertEqual(row['revision'], 0)
            self.assertFalse(row['customized'])
            self.assertEqual(tuple(row['values']), DIMENSIONS)
        for kind in ('movie', 'show'):
            self.assertFalse(standards['types'][kind]['values']['cast']['enabled'])
            self.assertFalse(standards['types'][kind]['values']['artwork']['enabled'])
        self.assertTrue(standards['types']['other_videos']['values']['cast']['enabled'])
        self.assertTrue(standards['types']['other_videos']['values']['artwork']['enabled'])
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
            {'artwork': {'required': ['poster'], 'poster_ratio': '2:3'}, 'cast': {'enabled': True}},
        )
        # The artwork values equal the type standard, so only the cast change is kept.
        self.assertEqual(result['overrides'], {'cast': {'enabled': True}})
        self.assertTrue(result['values']['cast']['enabled'])
        # A later type change still reaches fields the library did not override.
        values = self.service.standards()['types']['show']['values']
        values['cast']['mode'] = 'known_people'
        self.service.save_type_standard('show', 0, values)
        self.assertEqual(
            self.service.library_standard('srv:2')['values']['cast'], {'enabled': True, 'mode': 'known_people'}
        )
        with self.assertRaises(UserError):
            self.service.save_library_overrides('srv:2', 0, {})

    def test_rejects_invalid_standards(self):
        good = self.service.standards()['types']['movie']['values']
        bad = [
            {**good, 'extra': {}},
            {**good, 'artwork': {**good['artwork'], 'poster_ratio': '16:9'}},
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


class ReviewedStandards(unittest.TestCase):
    setUp = Standards.setUp
    tearDown = Standards.tearDown

    def snapshot(self):
        return self.service.standards()['libraries']['srv:1']

    def save(self, reviewed, overrides):
        return self.service.save_library_overrides(
            'srv:1',
            reviewed['revision'],
            overrides,
            kind=reviewed['kind'],
            type_revision=reviewed['type_revision'],
            type_digest=reviewed['type_digest'],
        )

    def test_parent_identity_and_digest_are_returned_with_effective_values(self):
        snapshot = self.service.standards()
        row = snapshot['libraries']['srv:1']
        self.assertEqual(row['type_revision'], 0)
        self.assertEqual(row['type_digest'], snapshot['types']['movie']['type_digest'])
        self.assertEqual(len(row['type_digest']), 64)
        result = self.save(row, {'cast': {'enabled': True}})
        self.assertEqual(result['revision'], 1)
        self.assertTrue(result['values']['cast']['enabled'])
        self.assertEqual(self.service.library('srv:1')['profile'], 'commercial')

    def test_parent_change_rejects_reviewed_override_and_reset_without_writes(self):
        self.save(self.snapshot(), {'cast': {'enabled': True}})
        reviewed = self.snapshot()
        values = self.service.standards()['types']['movie']['values']
        values['encoding']['max_mbps_1080'] = 12
        self.service.save_type_standard('movie', 0, values)
        for changes in [{}, {'artwork': {'enabled': True}}]:
            with self.assertRaisesRegex(UserError, 'inherited standard changed'):
                self.save(reviewed, changes)
        current = self.snapshot()
        self.assertEqual(current['revision'], reviewed['revision'])
        self.assertEqual(current['overrides'], reviewed['overrides'])

    def test_changed_built_in_values_at_revision_zero_are_not_silently_adopted(self):
        reviewed = self.snapshot()
        changed = copy.deepcopy(DEFAULTS['movie'])
        changed['metadata']['local_ai_suggestions'] = True
        with patch.dict(DEFAULTS, movie=changed):
            self.assertEqual(self.snapshot()['type_revision'], 0)
            self.assertNotEqual(self.snapshot()['type_digest'], reviewed['type_digest'])
            with self.assertRaisesRegex(UserError, 'inherited standard changed'):
                self.save(reviewed, {'artwork': {'enabled': True}})
        self.assertEqual(self.snapshot()['revision'], 0)

    def test_kind_change_is_rejected_even_when_parent_values_and_revision_match(self):
        reviewed = self.snapshot()
        with self.store.transaction():
            library = self.service.library('srv:1')
            library['standard_kind'] = 'show'
            self.store.put('libraries', library['id'], library)
        self.assertEqual(self.snapshot()['type_digest'], reviewed['type_digest'])
        with self.assertRaisesRegex(UserError, 'inherited standard changed'):
            self.save(reviewed, {'cast': {'enabled': True}})
        self.assertEqual(self.snapshot()['overrides'], {})

    def test_stale_library_and_malformed_parent_guards_are_rejected(self):
        reviewed = self.snapshot()
        self.save(reviewed, {'cast': {'enabled': True}})
        with self.assertRaisesRegex(UserError, 'library changed'):
            self.save(reviewed, {})
        for arguments in [
            dict(kind='movie'),
            dict(type_revision=0),
            dict(type_digest='x'),
            dict(kind='movie', type_revision=True, type_digest=reviewed['type_digest']),
        ]:
            with self.subTest(arguments=arguments), self.assertRaises(UserError):
                self.service.save_library_overrides('srv:1', 1, {}, **arguments)

    def test_noop_keeps_revisions_history_and_untouched_fields(self):
        before = self.store.db.execute('SELECT count(*) FROM events').fetchone()[0]
        row = self.service.standards()['types']['movie']
        self.assertEqual(self.service.save_type_standard('movie', 0, row['values'])['revision'], 0)
        self.assertEqual(self.save(self.snapshot(), {})['revision'], 0)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM events').fetchone()[0], before)
        changed = self.save(self.snapshot(), {'cast': {'enabled': True}, 'encoding': {'max_mbps_4k': 80}})
        before = self.store.db.execute('SELECT count(*) FROM events').fetchone()[0]
        self.assertEqual(self.save(changed, changed['overrides'])['revision'], 1)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM events').fetchone()[0], before)
        self.assertEqual(self.snapshot()['values']['metadata'], DEFAULTS['movie']['metadata'])

    def test_two_reviewed_writers_cannot_both_replace_the_same_revision(self):
        reviewed = self.snapshot()
        start = threading.Barrier(2)

        def save(flag):
            start.wait(timeout=5)
            try:
                return self.save(reviewed, {'metadata': {'local_ai_suggestions': flag}, 'cast': {'enabled': True}})
            except UserError:
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, [True, False]))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.snapshot()['revision'], 1)

    def test_browser_route_requires_complete_parent_guard_and_refuses_malformed_overrides(self):
        server = App(('127.0.0.1', 0), self.service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        try:
            opener.open(base + '/').close()
            row = self.snapshot()
            payload = dict(library='srv:1', revision=row['revision'], overrides={'cast': {'enabled': True}})

            def post(data):
                request = Request(
                    base + '/api/library/standard',
                    data=json.dumps(data).encode(),
                    headers={'Content-Type': 'application/json', 'X-Curator-Request': '1', 'Origin': base},
                )
                with opener.open(request) as response:
                    return json.load(response)

            for data in [payload, {**payload, 'kind': None, 'type_revision': None, 'type_digest': None}]:
                with self.assertRaises(HTTPError) as error:
                    post(data)
                self.assertEqual(error.exception.code, 400)
            payload.update(kind=row['kind'], type_revision=row['type_revision'], type_digest=row['type_digest'])
            with self.assertRaises(HTTPError) as error:
                post({**payload, 'overrides': []})
            self.assertEqual(error.exception.code, 400)
            self.assertEqual(self.snapshot()['revision'], 0)
            self.assertEqual(post(payload)['revision'], 1)
            self.assertEqual(self.store.all('tasks'), [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
