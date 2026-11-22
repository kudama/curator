"""Offline Seerr contract checks: no live endpoints, credentials or catalog writes."""

import copy
import io
import json
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, parse_qs
from unittest.mock import patch
from curator.errors import UserError
from curator.seerr_client import SeerrClient, SeerrError, REQUEST_VIEW, normalize_request
from curator.seerr_arrivals import arrivals_view, cached_arrivals_view
import test_curator


def request(identity=1, kind='movie', status=2, media_status=5, external=123, created='2020-01-01T00:00:00Z'):
    return dict(
        id=identity,
        type=kind,
        status=status,
        is4k=False,
        createdAt=created,
        requestedBy=dict(displayName='PRIVATE USER'),
        media=dict(mediaType=kind, status=media_status, tmdbId=external, tvdbId=None),
    )


class Response(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(json.dumps(data).encode())
        self.url = url

    def geturl(self):
        return self.url


class Transport:
    def __init__(self, rows=(), user=None):
        self.rows = list(rows)
        self.user = user or dict(id=7, permissions=REQUEST_VIEW)
        self.calls = []

    def __call__(self, req, timeout):
        parts = urlsplit(req.full_url)
        path = parts.path.removeprefix('/api/v1')
        query = parse_qs(parts.query)
        self.calls.append((req.get_method(), path, query, req.headers, req.data))
        if path == '/status':
            data = dict(version='fixture-v1')
        elif path == '/auth/me':
            data = self.user
        elif path == '/auth/local':
            data = dict(id=7)
        elif path == '/request':
            kind = query['mediaType'][0]
            rows = [r for r in self.rows if r['type'] == kind]
            skip = int(query['skip'][0])
            data = dict(results=rows[skip : skip + 100], pageInfo=dict(results=len(rows)))
        else:
            raise AssertionError('allowlist escaped')
        return Response(data, req.full_url)


def client(transport, **kwargs):
    return SeerrClient(
        'http://fixture.invalid', expected_user=7, verified_versions={'fixture-v1'}, transport=transport, **kwargs
    )


class SeerrClientTests(unittest.TestCase):
    def test_typed_complete_two_pass_snapshot_and_requester_redaction(self):
        transport = Transport([request(2), request(1, 'tv')])
        snapshot = client(transport).snapshot()
        self.assertEqual(len(snapshot['requests']), 2)
        self.assertEqual([r['type'] for r in snapshot['requests']], ['movie', 'tv'])
        self.assertNotIn('PRIVATE USER', str(snapshot))
        self.assertEqual(len([c for c in transport.calls if c[1] == '/request']), 4)
        self.assertTrue(all(c[0] == 'GET' for c in transport.calls))
        self.assertFalse(any('X-api-key' in c[3] or 'X-api-user' in c[3] for c in transport.calls))

    def test_forbidden_operations_rejected_before_transport(self):
        transport = Transport()
        adapter = client(transport)
        for path, method in [
            ('/request', 'POST'),
            ('/request/1/approve', 'POST'),
            ('/request/1', 'DELETE'),
            ('/settings/main', 'GET'),
            ('/auth/plex', 'POST'),
            ('/auth/local', 'POST'),
            ('/request?filter=all', 'GET'),
        ]:
            with self.subTest(path=path, method=method), self.assertRaises(SeerrError):
                adapter.request(path, method=method)
        self.assertFalse(transport.calls)
        with self.assertRaises(SeerrError):
            adapter.request('/request', params=dict(mediaType='all'))
        self.assertFalse(transport.calls)

    def test_view_only_exact_user_no_management_or_admin_or_extra_permissions(self):
        for permissions in [2, 16, REQUEST_VIEW | 2, REQUEST_VIEW | 16, REQUEST_VIEW | 32, 0]:
            transport = Transport(user=dict(id=7, permissions=permissions))
            with self.subTest(permissions=permissions), self.assertRaises(SeerrError):
                client(transport).snapshot()
            self.assertEqual([c[1] for c in transport.calls], ['/status', '/auth/me'])
        with self.assertRaises(SeerrError):
            client(Transport(user=dict(id=8, permissions=REQUEST_VIEW))).snapshot()

    def test_two_pages_old_requests_not_truncated_by_age(self):
        rows = [request(i) for i in range(101, 0, -1)]
        transport = Transport(rows)
        result = client(transport).snapshot()
        self.assertEqual(len(result['requests']), 101)
        self.assertEqual(result['requests'][-1]['id'], 1)
        self.assertIn('100', [c[2]['skip'][0] for c in transport.calls if c[1] == '/request'])

    def test_same_counts_different_id_set_is_partial_not_complete(self):
        transport = Transport([request(1)])
        original = transport.__call__
        passes = 0

        def changed(req, timeout):
            nonlocal passes
            if '/request?' in req.full_url and 'mediaType=movie' in req.full_url:
                passes += 1
                if passes == 2:
                    transport.rows = [request(2)]
            return original(req, timeout)

        with self.assertRaises(SeerrError) as error:
            client(changed).snapshot()
        self.assertEqual(error.exception.state, 'partial')

    def test_wrong_typed_namespace_and_malformed_or_unknown_enum_incompatible(self):
        for change in ('wrong_type', 'missing_media', 'unknown_status'):
            row = request()
            if change == 'wrong_type':
                row['media']['mediaType'] = 'tv'
            elif change == 'missing_media':
                row.pop('media')
            else:
                row['media']['status'] = 99
            with self.subTest(change=change), self.assertRaises(SeerrError):
                client(Transport([row])).snapshot()

    def test_redirect_and_unsupported_version_never_follow_or_sync(self):
        class Redirect(Transport):
            def __call__(self, req, timeout):
                return Response({'version': 'fixture-v1'}, 'http://other.invalid/')

        with self.assertRaises(SeerrError):
            client(Redirect()).snapshot()
        transport = Transport()
        with self.assertRaises(SeerrError):
            SeerrClient('http://fixture.invalid', expected_user=7, transport=transport).snapshot()
        self.assertEqual([c[1] for c in transport.calls], ['/status'])

    def test_one_explicit_401_session_renewal_and_no_403_loop(self):
        for status in [401, 403]:
            transport = Transport()
            original = transport.__call__
            attempts = 0

            def unauthorized(req, timeout):
                nonlocal attempts
                if req.full_url.endswith('/auth/me'):
                    attempts += 1
                    if attempts == 1:
                        raise HTTPError(req.full_url, status, 'synthetic', {}, io.BytesIO())
                return original(req, timeout)

            adapter = client(unauthorized, allow_sign_in=True)
            if status == 401:
                self.assertEqual(
                    adapter.snapshot(dict(email='fixture@example.invalid', password='synthetic-pass'))['version'],
                    'fixture-v1',
                )
                self.assertEqual(len([c for c in transport.calls if c[0] == 'POST']), 1)
            else:
                with self.assertRaises(SeerrError):
                    adapter.snapshot(dict(email='fixture@example.invalid', password='synthetic-pass'))
                self.assertFalse(any(c[0] == 'POST' for c in transport.calls))

    def test_bounds_duplicates_and_order_changes_partial(self):
        for result, total in [([request(1), request(1)], 2), ([request(1)], 5001), ([request(1), request(2)], 2)]:
            transport = Transport()
            original = transport.__call__

            def malformed(req, timeout):
                if '/request?' in req.full_url:
                    return Response(dict(results=result, pageInfo=dict(results=total)), req.full_url)
                return original(req, timeout)

            with self.subTest(total=total), self.assertRaises(SeerrError) as error:
                client(malformed).snapshot()
            self.assertEqual(error.exception.state, 'partial')

    def test_repeated_401_stops_after_one_explicit_sign_in(self):
        transport = Transport()
        original = transport.__call__
        counts = {'auth': 0, 'signin': 0}

        def expired(req, timeout):
            if req.full_url.endswith('/auth/me'):
                counts['auth'] += 1
                raise HTTPError(req.full_url, 401, 'synthetic', {}, io.BytesIO())
            if req.full_url.endswith('/auth/local'):
                counts['signin'] += 1
            return original(req, timeout)

        with self.assertRaises(SeerrError):
            client(expired, allow_sign_in=True).snapshot(
                dict(email='fixture@example.invalid', password='synthetic-pass')
            )
        self.assertEqual(counts, {'auth': 2, 'signin': 1})

    def test_timeout_and_server_errors_are_unreachable_without_body_leak(self):
        for failure in [
            URLError('private upstream URL'),
            TimeoutError('private timeout'),
            HTTPError('http://fixture.invalid', 500, 'private body', {}, io.BytesIO()),
        ]:

            def failed(req, timeout):
                raise failure

            with self.subTest(kind=type(failure).__name__), self.assertRaises(SeerrError) as error:
                client(failed).snapshot()
            self.assertEqual(error.exception.state, 'unreachable')
            self.assertNotIn('private', str(error.exception))

    def test_permission_change_during_snapshot_prevents_accepting_it(self):
        transport = Transport([request()])
        original = transport.__call__
        checks = 0

        def elevated(req, timeout):
            nonlocal checks
            if req.full_url.endswith('/auth/me'):
                checks += 1
                if checks == 2:
                    return Response(dict(id=7, permissions=REQUEST_VIEW | 2), req.full_url)
            return original(req, timeout)

        with self.assertRaises(SeerrError) as error:
            client(elevated).snapshot()
        self.assertEqual(error.exception.state, 'not_authorized')
        self.assertEqual(checks, 2)


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.library = dict(id='movies', type='movie', profile='commercial', agent='tv.plex.agents.movie')
        self.asset = dict(
            id='asset',
            library='movies',
            rating_key='10',
            present=True,
            title='Synthetic movie',
            item=dict(type='movie', Guid=[{'id': 'tmdb://123'}], addedAt=1700000000),
        )

    def view(self, row, assets=None, **kwargs):
        return arrivals_view(
            [normalize_request(row, row['type'])],
            assets if assets is not None else [self.asset],
            [self.library],
            clock=1700000100,
            **kwargs,
        )[0]

    def test_approved_state_precedence_even_when_shared_media_is_available(self):
        for status in [1, 3, 4, 5]:
            row = self.view(request(status=status))
            self.assertNotIn(row['state'], {'landed', 'partly_landed', 'ambiguous'})
        self.assertEqual(self.view(request())['state'], 'landed')

    def test_match_by_typed_ids_not_title_and_distinguish_duplicates(self):
        self.assertEqual(self.view(request(), assets=[])['state'], 'available_not_scanned')
        wrong = {**self.asset, 'item': dict(type='episode', Guid=[{'id': 'tmdb://123'}], addedAt=1700000000)}
        self.assertEqual(self.view(request(), assets=[wrong])['state'], 'available_not_scanned')
        copy_asset = {**copy.deepcopy(self.asset), 'id': 'other', 'rating_key': '20'}
        self.assertEqual(self.view(request(), assets=[self.asset, copy_asset])['state'], 'ambiguous')
        same_item = {**copy.deepcopy(self.asset), 'id': 'same-item-other-part'}
        self.assertEqual(self.view(request(), assets=[self.asset, same_item])['state'], 'landed')

    def test_old_request_new_landing_recent_and_already_in_plex(self):
        self.assertTrue(self.view(request())['recent'])
        self.assertEqual(self.view(request(created='2025-01-01T00:00:00Z'))['state'], 'already_in_plex')
        self.assertFalse(
            self.view(request(), assets=[{**self.asset, 'item': {**self.asset['item'], 'addedAt': 1}}])['recent']
        )

    def test_4k_removed_and_blocklisted_excluded_without_confusing_enum(self):
        row = request()
        row['is4k'] = True
        self.assertEqual(self.view(row)['state'], '4k_excluded')
        self.assertEqual(self.view(request(media_status=6))['state'], 'blocklisted')
        self.assertEqual(self.view(request(media_status=7))['state'], 'removed')

    def test_tv_unavailable_until_verified_series_index_not_episode_guid(self):
        self.assertEqual(self.view(request(kind='tv'))['state'], 'tv_unavailable')
        library = dict(id='shows', type='show', profile='commercial')
        episode = dict(
            id='episode',
            library='shows',
            rating_key='40',
            present=True,
            item=dict(type='episode', grandparentRatingKey='30', addedAt=1700000000, Guid=[{'id': 'tmdb://123'}]),
        )
        series = dict(
            library='shows',
            rating_key='30',
            item=dict(type='show', Guid=[{'id': 'tmdb://123'}], title='Synthetic series'),
        )
        normalized = normalize_request(request(kind='tv', media_status=4), 'tv')
        self.assertEqual(
            arrivals_view([normalized], [episode], [library], tv_verified=True, series=[])[0]['state'],
            'available_not_scanned',
        )
        result = arrivals_view([normalized], [episode], [library], tv_verified=True, series=[series])[0]
        self.assertEqual(result['state'], 'partly_landed')
        self.assertEqual(result['matches'][0]['asset'], 'episode')

    def test_stale_snapshot_age_retains_partial_then_hides_counts_after_24_hours(self):
        record = dict(
            status='partial',
            last_success='2023-11-14T22:13:20Z',
            snapshot=dict(requests=[normalize_request(request(), 'movie')], consistency='two_matching_bounded_passes'),
        )
        fresh = cached_arrivals_view(record, [self.asset], [self.library], clock=1700000100)
        self.assertTrue(fresh['stale'])
        self.assertTrue(fresh['counts_visible'])
        self.assertEqual(fresh['recent_count'], 1)
        expired = cached_arrivals_view(record, [self.asset], [self.library], clock=1700000000 + 86401)
        self.assertFalse(expired['counts_visible'])
        self.assertIsNone(expired['recent_count'])
        self.assertFalse(expired['rows'])
        refused = cached_arrivals_view(
            {**record, 'status': 'incompatible'}, [self.asset], [self.library], clock=1700000100
        )
        self.assertFalse(refused['rows'])

    def test_missing_guid_and_null_agent_are_unavailable_not_guessed(self):
        self.library['agent'] = None
        self.asset['item']['Guid'] = None
        self.assertEqual(self.view(request())['state'], 'available_not_scanned')
        self.asset['item']['Guid'] = [{'id': 'tmdb://123'}]
        self.assertEqual(self.view(request())['state'], 'landed')
        self.library['agent'] = 'com.plexapp.agents.none'
        self.assertEqual(self.view(request())['state'], 'available_not_scanned')


class OfflineSnapshots(unittest.TestCase):
    setUp = test_curator.Workflows.setUp
    tearDown = test_curator.Workflows.tearDown

    def test_partial_and_outage_keep_last_complete_snapshot_and_deduplicate_events(self):
        adapter = client(Transport([request()]))
        first = self.service.refresh_seerr_fixture(adapter)
        with patch.object(adapter, 'snapshot', side_effect=SeerrError('partial', 'private upstream body')):
            partial = self.service.refresh_seerr_fixture(adapter)
            events = self.store.db.execute('SELECT count(*) FROM events').fetchone()[0]
            repeated = self.service.refresh_seerr_fixture(adapter)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM events').fetchone()[0], events)
        self.assertEqual(partial['snapshot'], first['snapshot'])
        self.assertEqual(partial['last_success'], first['last_success'])
        self.assertEqual(repeated['snapshot'], partial['snapshot'])
        self.assertNotIn('private upstream body', str(partial))
        self.assertFalse(self.service.seerr_arrivals()['enabled'])
        self.assertFalse(self.plex.writes)
        self.assertEqual(len(self.store.all('tasks')), 1)

    def test_live_transport_and_imported_enable_flags_cannot_activate_connection(self):
        adapter = SeerrClient('http://fixture.invalid', expected_user=7, verified_versions={'fixture-v1'})
        with self.assertRaises(UserError):
            self.service.refresh_seerr_fixture(adapter)
        with self.store.transaction():
            self.store.put(
                'settings', 'seerr', dict(enabled=True, url='http://fixture.invalid', password='not-a-real-secret')
            )
        self.assertFalse(self.service.seerr_status()['enabled'])
