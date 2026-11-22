import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

import test_curator
from test_maintenance_policy import rule
from curator.errors import UserError
from curator.history import acting
from curator.maintenance import MaintenanceRules
from curator.maintenance_arrivals import MaintenanceArrivals
from curator.service import Service
from curator.tools import fingerprint


class Harness(Service):
    def maintenance_tool_snapshot(self, values, captured=None):
        return {'fixture': 'verified'}

    def validate_maintenance_permission(self, record):
        return record


STANDARD = dict(
    kind='movie',
    revision=0,
    type_revision=0,
    type_digest='type',
    effective_digest='effective',
    encoding_thresholds={'fixture': True},
)


class Rules(unittest.TestCase):
    setUp = test_curator.Workflows.setUp
    tearDown = test_curator.Workflows.tearDown

    def harness(self):
        self.service = Harness(self.store, lambda *args: self.plex)
        self.values = rule(library=self.lib['id'], roots=['/plex'], excluded_paths=[])
        self.clock = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
        self.service.maintenance_clock = lambda: self.clock

    def save(self):
        with acting('operator'):
            return self.service.save_maintenance_rule(None, 0, self.values)

    def caps(self):
        value = dict(limits=self.values['limits'], timezone=self.values['timezone'])
        with acting('operator'):
            self.service.save_maintenance_caps(None, 0, value)
            self.service.save_maintenance_caps(self.lib['id'], 0, value)

    def test_drafts_are_disabled_and_no_actor_can_infer_permission(self):
        self.harness()
        with acting('ai'), self.assertRaises(UserError):
            self.service.save_maintenance_rule(None, 0, self.values)
        saved = self.save()
        self.assertFalse(saved['enabled'])
        self.assertIsNone(saved['approval'])
        self.assertTrue(self.service.maintenance_paused(self.lib['id']))
        with acting('operator'), self.assertRaisesRegex(UserError, 'review is pending'):
            self.service.preview_maintenance_enable(saved['id'], saved['revision'])
        self.assertEqual(self.plex.writes, [])
        self.assertFalse(self.service.file_jobs())

    def test_machine_library_caps_baseline_and_exact_review_are_all_required(self):
        self.harness()
        saved = self.save()
        with (
            patch('curator.maintenance.POLICY_ACCEPTED', True),
            patch('curator.maintenance.standard_identity', return_value=STANDARD),
            acting('operator'),
        ):
            with self.assertRaisesRegex(UserError, 'machine and shared library limits'):
                self.service.preview_maintenance_enable(saved['id'], 1)
            self.caps()
            with self.assertRaisesRegex(UserError, 'baseline scan'):
                self.service.preview_maintenance_enable(saved['id'], 1)
            self.service.observe_maintenance_scan(self.lib['id'], [self.asset['id']])
            preview = self.service.preview_maintenance_enable(saved['id'], 1)
            with self.assertRaises(UserError):
                self.service.enable_maintenance_rule(preview['preview'], preview['digest'], 'process_encode')
            enabled = self.service.enable_maintenance_rule(preview['preview'], preview['digest'], 'scan')
            self.assertTrue(enabled['enabled'])
            self.assertEqual(enabled['approval']['initiator'], 'operator')
            self.assertTrue(self.service.maintenance_paused(self.lib['id']))
            with self.assertRaises(UserError):
                self.service.enable_maintenance_rule(preview['preview'], preview['digest'], 'scan')
        self.assertEqual(self.plex.writes, [])

    def test_scope_and_baseline_change_stales_enable_preview(self):
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
            self.clock += timedelta(seconds=60)
            self.service.observe_maintenance_scan(self.lib['id'], [self.asset['id']])
            with self.assertRaisesRegex(UserError, 'changed'):
                self.service.enable_maintenance_rule(preview['preview'], preview['digest'], 'scan')

    def test_disable_and_edits_revoke_only_unstarted_rule_jobs(self):
        self.harness()
        saved = self.save()
        queued = dict(self.task, status='queued', maintenance={'rule': saved['id']})
        running = dict(queued, id='running-rule-job', status='running')
        manual = dict(self.task, id='manual-job', status='queued')
        with self.store.transaction():
            for task in (queued, running, manual):
                self.store.put('tasks', task['id'], task)
        with acting('operator'):
            disabled = self.service.change_maintenance_state(saved['id'], 1, 'disable')
        self.assertEqual(disabled['revision'], 2)
        self.assertFalse(disabled['enabled'])
        self.assertEqual(self.store.get('tasks', queued['id'])['status'], 'blocked')
        self.assertEqual(self.store.get('tasks', running['id'])['status'], 'running')
        self.assertEqual(self.store.get('tasks', manual['id'])['status'], 'queued')

    def test_failed_audit_rolls_back_permission_change(self):
        self.harness()
        with (
            acting('operator'),
            patch.object(self.store, 'record', side_effect=RuntimeError('synthetic audit unavailable')),
        ):
            with self.assertRaises(RuntimeError):
                self.service.save_maintenance_rule(None, 0, self.values)
        self.assertFalse(self.service.maintenance_rules())

    def test_baseline_never_backfills_and_new_arrival_waits_for_stable_second_scan(self):
        self.harness()
        baseline = self.service.observe_maintenance_scan(self.lib['id'], [self.asset['id']])
        self.assertTrue(baseline['baseline'])
        self.assertFalse(self.service.maintenance_arrivals(self.lib['id']))
        path = self.media / 'new.mp4'
        path.write_bytes(b'new-synthetic-video')
        asset = dict(
            self.asset,
            id='new-asset',
            rating_key='99',
            plex_path='/plex/new.mp4',
            local_path=str(path.resolve()),
            fingerprint=fingerprint(path),
            item=dict(ratingKey='99', guid='new-guid'),
        )
        with self.store.transaction():
            self.store.put('assets', asset['id'], asset)
        self.clock += timedelta(seconds=60)
        self.service.observe_maintenance_scan(self.lib['id'], [self.asset['id'], asset['id']])
        self.assertEqual(self.service.maintenance_arrivals(self.lib['id'])[0]['phase'], 'observing')
        self.clock += timedelta(seconds=60)
        self.service.observe_maintenance_scan(self.lib['id'], [self.asset['id'], asset['id']])
        arrivals = self.service.maintenance_arrivals(self.lib['id'])
        self.assertEqual(len(arrivals), 1)
        self.assertEqual(arrivals[0]['phase'], 'ready')
        self.clock += timedelta(seconds=60)
        self.service.observe_maintenance_scan(self.lib['id'], [self.asset['id'], asset['id']])
        self.assertEqual(len(self.service.maintenance_arrivals(self.lib['id'])), 1)

    def test_renamed_or_rematched_baseline_file_is_not_an_arrival(self):
        self.harness()
        self.service.observe_maintenance_scan(self.lib['id'], [self.asset['id']])
        renamed = dict(self.asset, id='different-id', rating_key='different-key', plex_path='/plex/new-name.mkv')
        with self.store.transaction():
            self.store.put('assets', renamed['id'], renamed)
        self.clock += timedelta(seconds=60)
        self.service.observe_maintenance_scan(self.lib['id'], [renamed['id']])
        self.assertFalse(self.service.maintenance_arrivals(self.lib['id']))
