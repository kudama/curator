import copy
import unittest
from unittest.mock import patch

from curator.errors import UserError
from curator.maintenance_inventory import verified_inventory
from test_maintenance_policy import rule


class InventoryClient:
    def __init__(self):
        self.rows = [dict(ratingKey=str(i), title=f'Synthetic {i}') for i in range(3)]
        self.calls = []
        self.edit = None

    def request(self, path, params=None, timeout=None, max_bytes=None):
        self.calls.append(dict(path=path, params=params, timeout=timeout, max_bytes=max_bytes))
        if path == '/identity':
            return dict(machineIdentifier='fixture-server')
        start, size = params['X-Plex-Container-Start'], params['X-Plex-Container-Size']
        block = dict(totalSize=len(self.rows), offset=start, Metadata=copy.deepcopy(self.rows[start : start + size]))
        return self.edit(block, len(self.calls)) if self.edit else block


class Inventory(unittest.TestCase):
    def setUp(self):
        self.client = InventoryClient()
        self.library = dict(server='fixture-server', key='1', type='movie')
        self.options = rule()['options']
        self.options.update(page_size=2, max_pages=2)
        self.guards = 0

    def guard(self):
        self.guards += 1

    def run_inventory(self):
        return verified_inventory(self.client, self.library, self.options, self.guard)

    def test_two_complete_matching_passes_with_every_request_bounded(self):
        result = self.run_inventory()
        self.assertEqual(result['count'], 3)
        self.assertEqual(result['requests'], 5)
        self.assertEqual(self.guards, 6)
        self.assertTrue(
            all(0 < call['timeout'] <= self.options['request_timeout_seconds'] for call in self.client.calls)
        )
        self.assertTrue(all(call['max_bytes'] <= self.options['response_limit_bytes'] for call in self.client.calls))

    def test_excessive_unknown_incomplete_repeated_and_changed_inventory_refused(self):
        edits = [
            lambda block, n: dict(block, totalSize=10001),
            lambda block, n: {k: v for k, v in block.items() if k != 'totalSize'},
            lambda block, n: dict(block, Metadata=[]),
            lambda block, n: dict(block, Metadata=[dict(ratingKey='same'), dict(ratingKey='same')]),
            lambda block, n: dict(block, totalSize=3 if n == 2 else 4),
            lambda block, n: dict(block, offset=99),
        ]
        for edit in edits:
            self.client = InventoryClient()
            self.client.edit = edit
            with self.subTest(edit=edit), self.assertRaises(UserError):
                self.run_inventory()
            self.assertLessEqual(len(self.client.calls), 3)

    def test_changed_second_verification_pass_never_returns_candidates(self):
        self.client.edit = lambda block, n: (
            dict(block, Metadata=[dict(row, title='Changed') for row in block['Metadata']]) if n >= 4 else block
        )
        with self.assertRaisesRegex(UserError, 'inventories differ'):
            self.run_inventory()

    def test_page_cap_and_memory_cap_abort_before_any_further_fetch(self):
        self.options['max_pages'] = 1
        with self.assertRaisesRegex(UserError, 'page-request cap'):
            self.run_inventory()
        self.assertEqual(len(self.client.calls), 2)
        self.client = InventoryClient()
        self.options['max_pages'] = 2
        with (
            patch('curator.maintenance_inventory.MAX_INVENTORY_BYTES', 10),
            self.assertRaisesRegex(UserError, 'memory bound'),
        ):
            self.run_inventory()
        self.assertEqual(len(self.client.calls), 2)

    def test_revocation_between_pages_stops_before_next_request(self):
        def revoke():
            self.guard()
            if self.guards == 3:
                raise UserError('revoked')

        with self.assertRaisesRegex(UserError, 'revoked'):
            verified_inventory(self.client, self.library, self.options, revoke)
        self.assertEqual(len(self.client.calls), 2)

    def test_expired_deadline_does_not_contact_plex(self):
        with self.assertRaisesRegex(UserError, 'deadline reached'):
            verified_inventory(self.client, self.library, self.options, self.guard, deadline=0)
        self.assertEqual(self.client.calls, [])
