from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from curator.history import acting
from curator.maintenance_policy import digest
from curator.maintenance_projection import next_window
from test_maintenance_policy import rule
import test_maintenance_rules as rules_fixture

STANDARD = rules_fixture.STANDARD


class Projection(unittest.TestCase):
    setUp = rules_fixture.Rules.setUp
    tearDown = rules_fixture.Rules.tearDown
    harness = rules_fixture.Rules.harness
    caps = rules_fixture.Rules.caps
    save = rules_fixture.Rules.save

    def test_read_only_counts_remaining_allowance_and_next_window_do_not_dispatch(self):
        self.harness()
        self.caps()
        saved = self.save()
        self.service.observe_maintenance_scan(self.lib['id'], [self.asset['id']])
        queued = dict(self.task, id='queued-projection', status='queued', maintenance={'rule': saved['id']})
        running = dict(queued, id='running-projection', status='running')
        review = dict(queued, id='review-projection', status='awaiting_review')
        blocked = dict(queued, id='blocked-projection', status='blocked')
        day = self.clock.astimezone(__import__('zoneinfo').ZoneInfo(self.values['timezone'])).date().isoformat()
        key = 'maintenance-day:' + digest(('machine', day))
        with self.store.transaction():
            for task in (queued, running, review, blocked):
                self.store.put('tasks', task['id'], task)
            self.store.put('settings', key, dict(id=key, record_type='maintenance_usage', items=1, output_bytes=123))
        before = len(self.store.all('settings'))
        with (
            patch.object(self.service, 'client') as client,
            patch.object(self.service, 'start_pending_maintenance') as dispatch,
        ):
            result = self.service.maintenance_configuration()
        summary = result['rules'][0]['operational']
        self.assertEqual(summary['counts'], dict(queued=1, running=1, waiting=1, review=1, blocked=1))
        self.assertTrue(summary['held'])
        self.assertEqual(summary['next_permitted_window'], self.clock.isoformat())
        self.assertEqual(summary['remaining'][0]['daily_items'], self.values['limits']['items_per_day'] - 1)
        self.assertEqual(
            summary['remaining'][0]['daily_output_bytes'], self.values['limits']['output_bytes_per_day'] - 123
        )
        self.assertEqual(len(self.store.all('settings')), before)
        client.assert_not_called()
        dispatch.assert_not_called()

    def test_unchanged_save_disabled_draft_revokes_enabled_permission_and_waiting_jobs(self):
        self.harness()
        self.caps()
        self.service.observe_maintenance_scan(self.lib['id'], [self.asset['id']])
        saved = self.save()
        with (
            patch('curator.maintenance.POLICY_ACCEPTED', True),
            patch('curator.maintenance.standard_identity', return_value=STANDARD),
            acting('operator'),
        ):
            preview = self.service.preview_maintenance_enable(saved['id'], 1)
            enabled = self.service.enable_maintenance_rule(preview['preview'], preview['digest'], 'scan')
            with self.store.transaction():
                self.store.put(
                    'tasks', self.task['id'], dict(self.task, status='queued', maintenance={'rule': saved['id']})
                )
            disabled = self.service.save_maintenance_rule(enabled['id'], 1, self.values)
        self.assertFalse(disabled['enabled'])
        self.assertIsNone(disabled['approval'])
        self.assertEqual(disabled['revision'], 2)
        self.assertEqual(self.service.get_task(self.task['id'])['status'], 'blocked')
        with acting('operator'):
            no_op = self.service.save_maintenance_rule(disabled['id'], 2, self.values)
        self.assertEqual(no_op['revision'], 2)

    def test_preview_retains_exact_permission_and_all_reviewed_scope_caps(self):
        self.harness()
        self.caps()
        self.service.observe_maintenance_scan(self.lib['id'], [self.asset['id']])
        saved = self.save()
        with (
            patch('curator.maintenance.POLICY_ACCEPTED', True),
            patch('curator.maintenance.standard_identity', return_value=STANDARD),
            acting('operator'),
        ):
            result = self.service.preview_maintenance_enable(saved['id'], 1)
        snapshot = result['snapshot']
        self.assertEqual(snapshot['permission'], self.values)
        self.assertEqual(
            [row['scope'] for row in snapshot['allowances']],
            ['machine', 'library:' + self.lib['id'], 'rule:' + saved['id']],
        )
        self.assertTrue(all(row['limits'] == self.values['limits'] for row in snapshot['allowances']))
        self.assertEqual(self.service.maintenance_rule(saved['id'])['enabled'], False)

    def test_baseline_scope_change_refuses_preview_before_tool_or_media_access(self):
        import copy

        self.harness()
        self.caps()
        self.service.observe_maintenance_scan(self.lib['id'], [self.asset['id']])
        saved = self.save()
        for field, value in [
            ('mappings', [dict(plex_root='/plex', local_root=str(self.media / 'other'))]),
            ('profile', 'home'),
            ('agent', 'different-agent'),
        ]:
            library = copy.deepcopy(self.lib)
            library[field] = value
            with self.store.transaction():
                self.store.put('libraries', library['id'], library)
            with (
                patch('curator.maintenance.POLICY_ACCEPTED', True),
                patch('curator.maintenance.standard_identity', return_value=STANDARD),
                patch.object(self.service, 'maintenance_tool_snapshot') as tools,
                patch.object(self.service, 'client') as client,
                acting('operator'),
            ):
                with (
                    self.subTest(field=field),
                    self.assertRaisesRegex(ValueError, 'scope changed since the authoritative baseline'),
                ):
                    self.service.preview_maintenance_enable(saved['id'], 1)
                tools.assert_not_called()
                client.assert_not_called()
            with self.store.transaction():
                self.store.put('libraries', self.lib['id'], self.lib)
        self.assertEqual(self.service.file_jobs(), [])


class WindowProjection(unittest.TestCase):
    def test_next_boundary_after_quiet_hours_and_dst_gap_is_finite_and_permitted(self):
        values = rule(
            windows=[dict(days=[0], start='09:00', end='12:00')], quiet=[dict(days=[0], start='09:00', end='10:00')]
        )
        before = datetime(2026, 11, 23, 16, 30, tzinfo=timezone.utc)
        self.assertEqual(next_window(values, before), '2026-11-23T18:00:00+00:00')
        values = rule(windows=[dict(days=[6], start='02:30', end='03:30')])
        before = datetime(2026, 3, 8, 9, tzinfo=timezone.utc)
        self.assertEqual(next_window(values, before), '2026-03-15T09:30:00+00:00')
