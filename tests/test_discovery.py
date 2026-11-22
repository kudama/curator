"""Local movie discovery: deterministic facts, typed identities and reversible feedback."""

import copy
from datetime import datetime, timezone
import http.cookiejar
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor

from curator.discovery import rating_signals, resolve_feedback, movie_catalogue, typed_identity, discovery_version
from curator.errors import UserError
from curator.service import Service
from curator.store import Store
from curator.web import App

AT = '2026-11-20T21:00:00Z'
CLOCK = datetime.fromisoformat(AT.replace('Z', '+00:00')).timestamp()


def asset(identity, *, rating=8, added=3, library='movies', watched=0, genre='Action', guid=None, **fields):
    item = dict(
        ratingKey=identity,
        type='movie',
        title='Sample Film ' + identity,
        viewCount=watched,
        viewOffset=0,
        addedAt=int(CLOCK - added * 86400),
        Genre=[{'tag': genre}],
        Guid=[{'id': guid or 'tmdb://' + identity}],
        rating=rating,
    )
    item.update(fields)
    return dict(
        id=identity, library=library, title=item['title'], rating_key=identity, item=item, present=True, scanned=AT
    )


class Discovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'state')
        self.addCleanup(self.store.close)
        self.service = Service(self.store, plex_factory=lambda *args: self.fail('Discovery must not call Plex'))
        self.clock = patch('curator.discovery.now', return_value=AT)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.libraries = [
            dict(id='movies', server='server', key='1', type='movie', profile='commercial', title='Films'),
            dict(id='copies', server='server', key='2', type='movie', profile='commercial', title='Copies'),
            dict(id='shows', server='server', key='3', type='show', profile='commercial', title='TV'),
            dict(id='home', server='server', key='4', type='movie', profile='home', title='Family'),
        ]
        with self.store.transaction():
            for library in self.libraries:
                self.store.put('libraries', library['id'], library)

    def put(self, *rows):
        with self.store.transaction():
            for row in rows:
                self.store.put('assets', row['id'], row)

    def vote(self, identity, value):
        return self.service.discovery_feedback(
            dict(
                asset=identity,
                feedback=value,
                revision=self.service.discovery_feedback_state()['revision'],
                asset_version=discovery_version(
                    self.store.get('assets', identity),
                    self.service.library(self.store.get('assets', identity)['library']),
                ),
            )
        )

    def test_rating_precedence_half_up_feedback_and_unrated_fallback(self):
        self.put(
            asset('101', rating=8.2, audienceRating=7),
            asset('105', rating=7.5, audienceRating=8, added=200),
            asset('106', rating=9.5, audienceRating=9.1, added=40, genre='Drama'),
            asset(
                '107',
                rating=1,
                added=10,
                genre='Drama',
                Rating=[{'type': 'critic', 'value': 9}, {'type': 'audience', 'value': 8}],
            ),
            asset('103', rating=None, added=5),
            asset('102', watched=1, rating=10),
        )
        self.vote('105', 'more')
        new = self.service.discovery('new')
        picked = self.service.discovery('picked')
        self.assertEqual([(r['asset'], r['score']) for r in new['items']], [('107', 85), ('101', 76), ('103', None)])
        self.assertEqual(
            [(r['asset'], r['score']) for r in picked['items']],
            [('106', 93), ('105', 88), ('101', 86), ('107', 85), ('103', None)],
        )
        self.assertIn('No rating in Plex', [f['text'] for f in new['items'][-1]['why']])
        self.assertEqual(rating_signals({'rating': 10, 'Rating': []}), {})
        self.assertFalse(new['stale'])
        self.assertTrue(all(f['observed_at'] for r in new['items'] for f in r['why']))

    def test_movies_only_verified_items_deduplicate_parts_but_not_copies(self):
        original = asset('10')
        part = {**copy.deepcopy(original), 'id': 'part-2'}
        self.put(
            original,
            part,
            asset('11', library='copies', guid='tmdb://10'),
            asset('12', library='shows', type='episode'),
            asset('13', library='home'),
            asset('14', present=False),
            {**asset('15'), 'present': False},
            asset('16', ratingKey='wrong'),
        )
        # present is an asset fact, not a Plex metadata field.
        missing = self.store.get('assets', '14')
        missing['present'] = False
        self.put(missing)
        rows = self.service.discovery()['items']
        self.assertEqual(len(rows), 2)
        self.assertEqual({r['library'] for r in rows}, {'movies', 'copies'})
        self.assertTrue(all(r['media_type'] == 'movie' for r in rows))
        self.vote(rows[0]['asset'], 'hide')
        self.assertEqual(self.service.discovery()['total'], 1)

    def test_typed_reattachment_refuses_wrong_type_and_ambiguous_copies(self):
        self.put(asset('20', guid='tmdb://900005'))
        libraries, assets, catalogue = self.service._discovery_context()
        record = dict(asset='gone', identity=dict(media_type='show', server='server', guids=['tmdb://900005']))
        self.assertEqual(resolve_feedback(record, assets, catalogue, libraries), (None, 'detached'))
        record['identity']['media_type'] = 'movie'
        self.assertEqual(resolve_feedback(record, assets, catalogue, libraries)[0]['id'], '20')
        self.put(asset('21', library='copies', guid='tmdb://900005'))
        libraries, assets, catalogue = self.service._discovery_context()
        self.assertEqual(resolve_feedback(record, assets, catalogue, libraries), (None, 'ambiguous'))

    def test_feedback_scope_conflict_clear_and_no_provider_or_media_writes(self):
        self.put(asset('30'), asset('31', library='copies', guid='tmdb://30'))
        self.vote('30', 'hide')
        self.assertEqual([r['asset'] for r in self.service.discovery()['items']], ['31'])
        with self.assertRaises(UserError):
            self.service.discovery_feedback(dict(asset='31', feedback='more', revision=1))
        self.vote('30', 'clear')
        self.assertEqual(self.service.discovery()['total'], 2)
        self.assertEqual(self.store.all('tasks'), [])
        self.assertEqual(list(Path(self.temp.name).rglob('*.mp4')), [])

    def test_stale_future_and_unknown_observations_are_honest(self):
        old = asset('40', added=-3)
        old['scanned'] = '2020-01-01T00:00:00Z'
        unknown = asset('41')
        unknown['scanned'] = None
        unknown['item'].pop('viewCount')
        self.put(old, unknown)
        self.service.plex_failure = 'private provider detail must not be echoed'
        result = self.service.discovery('new')
        self.assertEqual([r['asset'] for r in result['items']], ['41'])
        self.assertTrue(result['stale'])
        self.assertIn('Viewing state unavailable', [f['text'] for f in result['items'][0]['why']])
        self.assertNotIn('private provider', json.dumps(result))
        self.assertNotIn('Not watched yet', [f['text'] for f in result['items'][0]['why']])

    def test_detached_retention_and_unique_rematch_without_cross_copy_feedback(self):
        first = asset('50')
        self.put(first)
        self.vote('50', 'hide')
        first['present'] = False
        self.put(first)
        self.service.reconcile_discovery_feedback()
        record = self.service.discovery_feedback_state()['entries']['50']
        self.assertEqual(record['detached_since'], AT)
        self.put(asset('51', guid='tmdb://50'))
        self.service.reconcile_discovery_feedback()
        self.assertEqual(self.service.discovery()['total'], 0)
        replacement = self.store.get('assets', '51')
        replacement['present'] = False
        self.put(replacement)
        self.service.reconcile_discovery_feedback()
        with patch('curator.discovery.now', return_value='2027-03-01T00:00:00Z'):
            self.service.reconcile_discovery_feedback()
        self.assertEqual(self.service.discovery_feedback_state()['entries'], {})

    def test_original_identity_change_does_not_transfer_feedback(self):
        first = asset('60')
        self.put(first)
        self.vote('60', 'hide')
        first['item']['Guid'] = [{'id': 'tmdb://61'}]
        self.put(first)
        result = self.service.discovery()
        self.assertEqual(result['total'], 1)
        self.assertEqual(self.service.discovery_feedback_list()['entries'][0]['status'], 'identity_changed')

    def test_reused_plex_key_cannot_transfer_feedback_to_another_movie(self):
        old = asset('61')
        self.put(old)
        self.vote('61', 'hide')
        old['present'] = False
        replacement = {**asset('62', guid='tmdb://62'), 'rating_key': '61'}
        replacement['item']['ratingKey'] = '61'
        self.put(old, replacement)
        self.assertEqual([r['asset'] for r in self.service.discovery()['items']], ['62'])

    def test_expired_feedback_is_not_revived_by_a_late_rematch(self):
        old = asset('63')
        self.put(old)
        self.vote('63', 'hide')
        old['present'] = False
        self.put(old)
        self.service.reconcile_discovery_feedback()
        self.put(asset('64', guid='tmdb://63'))
        with patch('curator.discovery.now', return_value='2027-03-01T00:00:00Z'):
            self.service.reconcile_discovery_feedback()
        self.assertEqual(self.service.discovery_feedback_state()['entries'], {})

    def test_stale_feedback_identity_snapshot_is_rejected(self):
        original = asset('65')
        self.put(original)
        pick = self.service.discovery()['items'][0]
        original['item']['Guid'] = [{'id': 'tmdb://66'}]
        self.put(original)
        with self.assertRaises(UserError):
            self.service.discovery_feedback(
                dict(asset='65', feedback='hide', revision=1, asset_version=pick['asset_version'])
            )
        self.assertEqual(self.service.discovery_feedback_state()['entries'], {})

    def test_invalid_optional_metadata_does_not_break_other_picks(self):
        malformed = asset('66')
        malformed['item']['Genre'] = None
        invalid_title = asset('67')
        invalid_title['title'] = None
        self.put(malformed, invalid_title)
        self.assertEqual([r['asset'] for r in self.service.discovery()['items']], ['66'])

    def test_settings_off_noop_and_stale_revision(self):
        self.put(asset('70'))
        self.assertEqual(self.service.save_discovery_settings(1, {}), self.service.discovery_settings())
        saved = self.service.save_discovery_settings(1, {'enabled': False})
        self.assertEqual(self.service.discovery()['empty_reason'], 'Discovery is off')
        self.assertEqual(self.service.discovery()['items'], [])
        with self.assertRaises(UserError):
            self.service.save_discovery_settings(1, {'enabled': True})
        self.assertEqual(saved['revision'], 2)
        self.service.save_discovery_settings(2, {'enabled': True})
        library = self.service.library('movies')
        library['kind'] = 'other_videos'
        with self.store.transaction():
            self.store.put('libraries', 'movies', library)
        self.assertEqual(self.service.discovery()['items'], [])

    def test_get_is_read_only_and_api_mutations_require_session_origin(self):
        self.put(asset('80'))
        before = self.store.db.total_changes
        self.service.discovery()
        self.service.discovery()
        self.assertEqual(self.store.db.total_changes, before)
        server = App(('127.0.0.1', 0), self.service)
        self.addCleanup(server.server_close)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        browser = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        with self.assertRaises(HTTPError) as error:
            browser.open(base + '/api/discovery')
        error.exception.close()
        with browser.open(base + '/') as response:
            response.read()
        with browser.open(base + '/api/discovery') as response:
            self.assertEqual(json.load(response)['items'][0]['asset'], '80')
        request = Request(
            base + '/api/discovery/feedback',
            data=json.dumps(
                dict(
                    asset='80',
                    feedback='hide',
                    revision=1,
                    asset_version=discovery_version(self.store.get('assets', '80'), self.service.library('movies')),
                )
            ).encode(),
            headers={'Content-Type': 'application/json'},
        )
        with self.assertRaises(HTTPError) as error:
            browser.open(request)
        error.exception.close()
        request.add_header('Origin', base)
        request.add_header('X-Curator-Request', '1')
        with browser.open(request) as response:
            self.assertEqual(json.load(response)['feedback'], 'hide')
