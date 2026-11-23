"""Synthetic Plex only: reviewed collection rows, receipts and capability guards."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from curator.errors import UserError
from curator.plex import Plex
from curator.service import Service
from curator.store import Store
from test_discovery import asset, AT


class FakeRows(Plex):
    def __init__(self):
        self.root = dict(machineIdentifier='server', ownerFeatures=['pass'], readOnlyLibraries=0)
        self.movies = {key: {**asset(key)['item'], 'librarySectionID': '1'} for key in ['101', '102', '103']}
        self.groups = {'900': dict(title='Unrelated', keys=['103'])}
        self.hubs = [
            dict(identifier='recentlyAdded', promotedToRecommended=1, promotedToOwnHome=1, promotedToSharedHome=0)
        ]
        self.calls, self.writes = [], []
        self.fail_visibility = self.lose_create = False

    def request(self, endpoint, method='GET', params=None, **kw):
        self.calls.append((endpoint, method, copy.deepcopy(params)))
        if method != 'GET':
            self.writes.append((endpoint, method, copy.deepcopy(params)))
        if endpoint == '/identity':
            return dict(machineIdentifier='server')
        if endpoint == '/':
            return copy.deepcopy(self.root)
        if endpoint == '/library/sections/1/collections':
            rows = [
                dict(ratingKey=k, type='collection', title=g['title'], smart=0, childCount=len(g['keys']))
                for k, g in self.groups.items()
            ]
            return dict(Metadata=rows, totalSize=len(rows))
        if endpoint == '/hubs/sections/1/manage' and method == 'GET':
            return dict(Hub=copy.deepcopy(self.hubs), totalSize=len(self.hubs))
        if endpoint.startswith('/hubs/sections/1/manage'):
            if self.fail_visibility:
                raise OSError('synthetic lost response')
            identity = (
                endpoint.rsplit('/', 1)[1] if method == 'PUT' else 'custom.collection.1.' + params['metadataItemId']
            )
            hub = next((h for h in self.hubs if h['identifier'] == identity), None)
            if hub is None:
                hub = dict(identifier=identity)
                self.hubs.append(hub)
            hub.update({k: v for k, v in params.items() if k != 'metadataItemId'})
            return {}
        if endpoint == '/library/collections' and method == 'POST':
            self.groups['901'] = dict(title=params['title'], keys=params['uri'].rsplit('/', 1)[1].split(','))
            if self.lose_create:
                raise OSError('synthetic lost create response')
            return dict(Metadata=[dict(ratingKey='901')])
        if endpoint.startswith('/library/metadata/'):
            tail = endpoint.removeprefix('/library/metadata/').split('/')
            key = tail[0]
            if len(tail) == 1:
                if key in self.movies:
                    return dict(Metadata=[copy.deepcopy(self.movies[key])])
                group = self.groups[key]
                return dict(
                    Metadata=[
                        dict(type='collection', ratingKey=key, librarySectionID='1', title=group['title'], smart=0)
                    ]
                )
            group = self.groups[key]
            if tail[1] == 'children':
                return dict(
                    Metadata=[dict(type='movie', ratingKey=k, librarySectionID='1') for k in group['keys']],
                    totalSize=len(group['keys']),
                )
            if tail[1] == 'items' and method == 'DELETE':
                group['keys'].remove(tail[2])
                return {}
            if tail[1] == 'items' and method == 'PUT':
                group['keys'] += params['uri'].rsplit('/', 1)[1].split(',')
                return {}
        raise AssertionError((endpoint, method, params))


class DiscoveryRowsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'state')
        self.addCleanup(self.store.close)
        self.plex = FakeRows()
        self.service = Service(self.store, plex_factory=lambda *args: self.plex)
        with self.store.transaction():
            self.store.put(
                'libraries',
                'movies',
                dict(id='movies', server='server', key='1', type='movie', kind='movie', profile='commercial'),
            )
            for key in ['101', '102', '103']:
                self.store.put('assets', key, asset(key))
        clock = patch('curator.discovery.now', return_value=AT)
        clock.start()
        self.addCleanup(clock.stop)

    def plan(self, **changes):
        data = dict(
            library='movies',
            row='picked',
            title='Curator picks',
            visibility=dict(recommended=True, home=False, shared=False),
            limit=2,
            revision=self.service.discovery_row('movies', 'picked')['revision'],
        )
        data.update(changes)
        return self.service.discovery_row_preview(data)

    def apply(self, plan):
        return self.service.apply_discovery_row(plan['id'], plan['token'], True)

    def test_preview_is_read_only_and_success_is_exact_and_idempotent(self):
        before = copy.deepcopy(self.plex.groups['900'])
        other = copy.deepcopy(self.plex.hubs[0])
        self.service.discovery_rows('movies')
        self.assertEqual(self.plex.calls, [])
        plan = self.plan()
        self.assertEqual(self.plex.writes, [])
        self.assertEqual(plan['keys'], ['101', '102'])
        receipt = self.apply(plan)
        self.assertEqual(receipt['status'], 'verified')
        self.assertEqual(self.plex.groups['901']['keys'], ['101', '102'])
        self.assertEqual(self.plex.groups['900'], before)
        self.assertEqual(self.plex.hubs[0], other)
        count = len(self.plex.writes)
        self.assertEqual(self.apply(plan), receipt)
        self.assertEqual(len(self.plex.writes), count)

    def test_capability_and_unmanaged_title_fail_closed(self):
        for field, value in [('ownerFeatures', []), ('readOnlyLibraries', 1), ('readOnlyLibraries', None)]:
            with self.subTest(field=field, value=value):
                original = copy.deepcopy(self.plex.root)
                self.plex.root[field] = value
                with self.assertRaises(UserError):
                    self.plan()
                self.plex.root = original
        with self.assertRaises(UserError):
            self.plan(title='Unrelated')
        self.plex.hubs[0].pop('promotedToOwnHome')
        with self.assertRaises(UserError):
            self.plan()
        self.assertEqual(self.plex.writes, [])

    def test_explicit_approval_and_stale_feedback_and_movie_guid(self):
        plan = self.plan()
        with self.assertRaises(UserError):
            self.service.apply_discovery_row(plan['id'], plan['token'], False)
        with self.assertRaises(UserError):
            self.service.apply_discovery_row(plan['id'], 'wrong', True)
        self.plex.movies['101']['Guid'] = []
        with self.assertRaises(UserError):
            self.apply(plan)
        self.assertEqual(self.plex.writes, [])
        with self.assertRaises(UserError):
            self.plan()
        self.plex.movies['101']['Guid'] = [{'id': 'tmdb://101'}]
        with self.store.transaction():
            self.store.put('settings', 'discovery-feedback', dict(revision=2, entries={}))
        with self.assertRaises(UserError):
            self.apply(plan)

    def test_updates_owned_membership_and_hides_without_deletion(self):
        self.apply(self.plan())
        self.plex.writes.clear()
        with self.store.transaction():
            self.store.put('assets', '101', {**asset('101'), 'present': False})
        plan = self.plan()
        self.assertEqual(set(plan['before']['keys']), {'101', '102'})
        self.assertEqual(self.apply(plan)['status'], 'verified')
        self.assertEqual(set(self.plex.groups['901']['keys']), {'102', '103'})
        plan = self.plan(visibility=dict(recommended=False, home=False, shared=False))
        self.assertEqual(self.apply(plan)['status'], 'verified')
        self.assertEqual(set(self.plex.groups['901']['keys']), {'102', '103'})
        self.assertFalse(any(method == 'DELETE' and path.endswith('/901') for path, method, _ in self.plex.writes))

    def test_external_membership_and_visibility_edits_are_not_overwritten(self):
        self.apply(self.plan())
        plan = self.plan()
        self.plex.writes.clear()
        self.plex.groups['901']['keys'] = ['103']
        with self.assertRaises(UserError):
            self.apply(plan)
        self.assertEqual(self.plex.writes, [])

    def test_partial_write_receipt_blocks_retry_and_can_be_inspected(self):
        plan = self.plan()
        self.plex.fail_visibility = True
        receipt = self.apply(plan)
        self.assertEqual(receipt['status'], 'needs_inspection')
        count = len(self.plex.writes)
        with self.assertRaises(UserError):
            self.apply(plan)
        with self.assertRaises(UserError):
            self.plan()
        self.plex.fail_visibility = False
        observed = self.service.inspect_discovery_row(plan['id'])
        self.assertFalse(observed['inspection']['matches_approved'])
        accepted = self.service.inspect_discovery_row(plan['id'], True)
        self.assertEqual(accepted['status'], 'inspected_partial')
        self.assertEqual(len(self.plex.writes), count)
        self.assertFalse(self.service.discovery_row('movies', 'picked')['uncertain'])
        self.plan()

    def test_unknown_create_never_adopts_by_title(self):
        plan = self.plan()
        self.plex.lose_create = True
        receipt = self.apply(plan)
        self.assertEqual(receipt['status'], 'needs_inspection')
        self.assertIsNone(receipt['collection'])
        with self.assertRaises(UserError):
            self.service.inspect_discovery_row(plan['id'], True)
        self.assertIsNone(self.service.discovery_row('movies', 'picked')['collection'])
        del self.plex.groups['901']  # Synthetic operator resolution, not a Curator deletion.
        result = self.service.inspect_discovery_row(plan['id'], True)
        self.assertEqual(result['status'], 'inspected_no_collection')
        self.assertFalse(self.service.discovery_row('movies', 'picked')['uncertain'])

    def test_stale_local_identity_settings_and_standard_reject_before_write(self):
        plan = self.plan()
        with self.store.transaction():
            self.store.put('assets', '101', {**asset('101'), 'fingerprint': 'changed'})
        with self.assertRaises(UserError):
            self.apply(plan)
        with self.store.transaction():
            self.store.put('assets', '101', asset('101'))
            self.store.put('settings', 'discovery-settings', dict(revision=2, enabled=True, detached_days=90))
        with self.assertRaises(UserError):
            self.apply(plan)
        library = self.service.library('movies')
        with self.store.transaction():
            self.store.put('libraries', 'movies', {**library, 'standard_kind': 'home'})
        with self.assertRaises(UserError):
            self.plan()
        self.assertEqual(self.plex.writes, [])

    def test_previews_do_not_grant_cross_row_ownership_or_overwrite_visibility(self):
        one = self.plan()
        two = self.plan(row='new')
        self.apply(one)
        count = len(self.plex.writes)
        with self.assertRaises(UserError):
            self.apply(two)
        self.assertEqual(len(self.plex.writes), count)
        plan = self.plan()
        self.plex.hubs[-1]['promotedToOwnHome'] = 1
        with self.assertRaises(UserError):
            self.apply(plan)
        self.assertEqual(len(self.plex.writes), count)

    def test_restart_marks_incomplete_receipt_uncertain(self):
        plan = self.plan()
        receipt = dict(
            id='discovery-row-receipt:' + plan['id'],
            record_type='discovery_row_receipt',
            plan=plan['id'],
            library='movies',
            row='picked',
            status='applying',
            created=AT,
            collection=None,
        )
        with self.store.transaction():
            self.store.put('settings', receipt['id'], receipt)
        self.service.recover_discovery_rows()
        self.assertTrue(self.service.discovery_row('movies', 'picked')['uncertain'])
        with self.assertRaises(UserError):
            self.plan()


if __name__ == '__main__':
    unittest.main()
