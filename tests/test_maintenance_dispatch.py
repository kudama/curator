import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import test_curator
from test_maintenance_policy import rule
from test_maintenance_rules import STANDARD
from curator.errors import UserError
from curator.history import acting
from curator.maintenance import MaintenanceRules
from curator.maintenance_arrivals import MaintenanceArrivals
from curator.maintenance_budget import MaintenanceBudgets
from curator.maintenance_dispatch import MaintenanceDispatch
from curator.maintenance_execution import MaintenanceExecution
from curator.service import Service
from curator.tools import digest as file_hash, fingerprint


class Engine(Service):
    def maintenance_tool_snapshot(self, values, captured=None):
        if captured is not None:
            return captured
        preset = self.store.root / 'synthetic-preset.json'
        preset.write_text('{"PresetList":[]}')
        return dict(
            config='synthetic-tools',
            files=[],
            settings=dict(
                handbrake=sys.executable,
                handbrake_preset='Synthetic',
                handbrake_preset_file=str(preset),
                handbrake_preset_hash=file_hash(preset),
            ),
        )

    def start_pending_maintenance(self, kind=None):
        return []  # Admission tests never start a real worker/tool.


class Dispatch(unittest.TestCase):
    setUp = test_curator.Workflows.setUp
    tearDown = test_curator.Workflows.tearDown

    def engine(self, cap=4):
        self.service = Engine(self.store, lambda *args: self.plex)
        self.clock = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
        self.service.maintenance_clock = lambda: self.clock
        self.patches = [
            patch('curator.maintenance.POLICY_ACCEPTED', True),
            patch('curator.maintenance.standard_identity', return_value=STANDARD),
            patch('curator.maintenance_dispatch.evaluated', side_effect=lambda service, asset: self.facts(asset)),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.values = rule(
            library=self.lib['id'],
            action='process_encode',
            roots=['/plex'],
            excluded_paths=[],
            options={'handbrake_preset': 'Synthetic'},
        )
        self.values['limits'].update(items_per_run=cap, items_per_day=cap)
        caps = dict(limits=self.values['limits'], timezone=self.values['timezone'])
        with acting('operator'):
            self.service.save_maintenance_caps(None, 0, caps)
            self.service.save_maintenance_caps(self.lib['id'], 0, caps)
        self.service.observe_maintenance_scan(self.lib['id'], [self.asset['id']])

    def facts(self, asset):
        return dict(
            version=1,
            standard=STANDARD,
            completion=dict(
                standard=STANDARD,
                status='needs_attention',
                observed_at=asset.get('scanned', 'fixture'),
                dimensions={'encoding': {'state': 'needs_attention'}},
            ),
            findings=[dict(kind='optimize', reason='Encoding standard requires work', evidence={'standard': STANDARD})],
        )

    def enable(self, name='Synthetic rule', action='process_encode'):
        values = copy.deepcopy(self.values)
        values.update(name=name, action=action)
        with acting('operator'):
            saved = self.service.save_maintenance_rule(None, 0, values)
            preview = self.service.preview_maintenance_enable(saved['id'], 1)
            enabled = self.service.enable_maintenance_rule(preview['preview'], preview['digest'], action)
            self.service.pause_maintenance_scope(None, False)
        return enabled

    def arrive(self, count=1):
        ids = [self.asset['id']]
        self.new_assets = []
        for number in range(count):
            path = self.media / f'arrival-{number}.mp4'
            path.write_bytes(b'synthetic-arrival' * (number + 1))
            asset = dict(
                self.asset,
                id=f'arrival-{number}',
                rating_key=f'new-{number}',
                title=f'Fixture {number}',
                plex_path=f'/plex/{path.name}',
                local_path=str(path.resolve()),
                fingerprint=fingerprint(path),
                item=dict(title=f'Fixture {number}', guid=f'new-guid-{number}'),
                scanned='fixture',
                technical=dict(width=1920, height=1080, duration_seconds=1),
            )
            with self.store.transaction():
                self.store.put('assets', asset['id'], asset)
            ids.append(asset['id'])
            self.new_assets.append(asset)
        self.clock += timedelta(seconds=60)
        self.service.observe_maintenance_scan(self.lib['id'], ids)
        self.clock += timedelta(seconds=60)
        self.service.observe_maintenance_scan(self.lib['id'], ids)

    def queued(self):
        return [task for task in self.store.all('tasks') if task.get('maintenance') and task['status'] == 'queued']

    def test_overlapping_rules_and_concurrent_scan_dispatch_admit_one_source_action(self):
        self.engine()
        self.enable('First')
        self.enable('Overlapping')
        self.arrive()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.service.dispatch_maintenance(self.lib['id']), range(2)))
        self.assertEqual(len(self.queued()), 1)
        claims = [
            row
            for row in self.store.all('settings')
            if isinstance(row, dict) and row.get('record_type') == 'maintenance_claim'
        ]
        self.assertEqual(len(claims), 1)
        self.assertEqual(self.queued()[0]['queued_by'], 'rule')
        daily = [
            row
            for row in self.store.all('settings')
            if isinstance(row, dict) and row.get('record_type') == 'maintenance_usage'
        ]
        self.assertTrue(all(row['items'] == 1 for row in daily))
        self.assertTrue(any(row['phase'] == 'skipped' for result in results for row in result))
        self.assertEqual(self.plex.writes, [])

    def test_machine_shared_cap_cannot_be_multiplied_by_rule_split(self):
        self.engine(cap=1)
        self.enable('First')
        self.enable('Second')
        self.arrive(2)
        decisions = self.service.dispatch_maintenance(self.lib['id'])
        self.assertEqual(len(self.queued()), 1)
        self.assertTrue(
            any(row['phase'] == 'exception' and 'allowance is exhausted' in row['reason'] for row in decisions)
        )

    def test_draft_preparation_never_grants_queue_or_start(self):
        self.engine()
        self.enable(action='prepare_encode')
        self.arrive()
        decisions = self.service.dispatch_maintenance(self.lib['id'])
        self.assertEqual([row['phase'] for row in decisions], ['prepared'])
        task = next(task for task in self.store.all('tasks') if task.get('maintenance_proposal'))
        self.assertEqual(task['status'], 'recommendation')
        self.assertNotIn('maintenance', task)
        self.assertIsNone(task.get('approval'))
        self.assertFalse(self.queued())

    def test_revocation_wins_before_any_subprocess_start(self):
        self.engine()
        enabled = self.enable()
        self.arrive()
        self.service.dispatch_maintenance(self.lib['id'])
        task = self.queued()[0]
        with acting('operator'):
            self.service.change_maintenance_state(enabled['id'], 1, 'disable')
        with patch('curator.maintenance_execution.subprocess.Popen') as launch, self.assertRaises(UserError):
            self.service.maintenance_start_process(task, ['never-start'], None, None)
        launch.assert_not_called()
        self.assertEqual(self.file.read_bytes(), b'original-video')

    def test_unstarted_model_options_source_and_standard_revisions_are_rechecked(self):
        self.engine()
        enabled = self.enable()
        self.arrive()
        self.service.dispatch_maintenance(self.lib['id'])
        task = self.queued()[0]
        changed = copy.deepcopy(task)
        changed['tool_settings']['handbrake_preset'] = 'Different'
        with self.store.transaction():
            self.store.put('tasks', changed['id'], changed)
        with self.assertRaisesRegex(UserError, 'options changed'):
            self.service.maintenance_start_guard(changed)
        with self.store.transaction():
            self.store.put('tasks', task['id'], task)
        self.new_assets[0]['fingerprint']['size'] += 1
        with self.store.transaction():
            self.store.put('assets', self.new_assets[0]['id'], self.new_assets[0])
        with self.assertRaises(UserError):
            self.service.maintenance_start_guard(task)

    def test_restart_holds_reserved_and_uncertain_work_without_replay(self):
        self.engine()
        enabled = self.enable()
        self.arrive()
        self.service.dispatch_maintenance(self.lib['id'])
        task = self.queued()[0]
        self.service.recover_maintenance()
        self.assertFalse(self.queued())
        self.assertEqual(self.store.get('settings', task['maintenance']['claim'])['phase'], 'interrupted_unstarted')
        self.service.dispatch_maintenance(self.lib['id'])
        self.assertFalse(self.queued())

    def test_clock_rollback_cannot_restore_allowance(self):
        self.engine()
        self.enable()
        self.arrive(2)
        arrivals = self.service.maintenance_arrivals(self.lib['id'])
        rule_record = self.service.maintenance_rules()[0]
        with self.lock_context():
            self.service.reserve_maintenance(rule_record, arrivals[0], 'one', STANDARD)
        self.clock -= timedelta(seconds=1)
        with self.lock_context(), self.assertRaisesRegex(UserError, 'Clock moved backwards'):
            self.service.reserve_maintenance(rule_record, arrivals[1], 'two', STANDARD)

    def lock_context(self):
        return self.store.transaction()

    def test_true_start_then_disable_race_has_one_durable_attempt_and_no_replay(self):
        import threading
        from types import SimpleNamespace

        self.engine()
        enabled = self.enable()
        self.arrive()
        self.service.dispatch_maintenance(self.lib['id'])
        task = self.queued()[0]
        task['status'] = 'running'
        with self.store.transaction():
            self.store.put('tasks', task['id'], task)
        entered, release, revoked = threading.Event(), threading.Event(), threading.Event()

        def launch(*args, **kwargs):
            claim = self.store.get('settings', task['maintenance']['claim'])
            self.assertEqual(claim['phase'], 'attempted')
            self.assertFalse(self.store.db.in_transaction)
            entered.set()
            self.assertTrue(release.wait(5))
            return SimpleNamespace(pid=12345)

        def disable():
            with acting('operator'):
                self.service.change_maintenance_state(enabled['id'], 1, 'disable')
            revoked.set()

        with (
            patch('curator.maintenance_execution.subprocess.Popen', side_effect=launch) as popen,
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            started = pool.submit(self.service.maintenance_start_process, task, ['synthetic-only'], None, None)
            self.assertTrue(entered.wait(5))
            disabled = pool.submit(disable)
            self.assertFalse(revoked.wait(0.05))
            release.set()
            self.assertEqual(started.result(5).pid, 12345)
            disabled.result(5)
            self.assertEqual(popen.call_count, 1)
            with self.assertRaises(UserError):
                self.service.maintenance_start_process(task, ['never'], None, None)
            self.assertEqual(popen.call_count, 1)

    def test_delayed_midnight_start_charges_new_named_day_without_refunding_old(self):
        self.engine()
        self.clock = datetime(2026, 11, 23, 7, 55, tzinfo=timezone.utc)  # Sunday 23:55 Los Angeles.
        enabled = self.enable()
        self.arrive()
        self.service.dispatch_maintenance(self.lib['id'])
        task = self.queued()[0]
        claim = self.store.get('settings', task['maintenance']['claim'])
        old = dict(claim['allocations'])
        self.clock += timedelta(minutes=10)
        with self.service.lock, self.store.transaction():
            self.service.maintenance_start_allowance(claim, enabled)
        self.assertTrue(all(claim['allocations'][key] != value for key, value in old.items()))
        self.assertTrue(all(self.store.get('settings', value)['items'] == 1 for value in old.values()))
        self.assertTrue(all(self.store.get('settings', value)['items'] == 1 for value in claim['allocations'].values()))

    def test_changed_effective_standard_blocks_actual_start_before_popen(self):
        self.engine()
        self.enable()
        self.arrive()
        self.service.dispatch_maintenance(self.lib['id'])
        task = self.queued()[0]
        task['status'] = 'running'
        with self.store.transaction():
            self.store.put('tasks', task['id'], task)
        changed = dict(STANDARD, effective_digest='new-standard-revision')
        with (
            patch('curator.maintenance.standard_identity', return_value=changed),
            patch('curator.maintenance_execution.subprocess.Popen') as launch,
        ):
            with self.assertRaisesRegex(UserError, 'stale'):
                self.service.maintenance_start_process(task, ['never'], None, None)
        launch.assert_not_called()

    def test_paused_typed_queue_projects_held_waiting_rule_work(self):
        self.engine()
        self.enable()
        self.arrive()
        self.service.dispatch_maintenance(self.lib['id'])
        self.assertEqual(len(self.queued()), 1)
        with self.store.transaction():
            self.store.put('settings', self.service.pause_key(None, 'optimize'), True)
        result = self.service.maintenance_configuration()['rules'][0]['operational']
        self.assertEqual(result['counts']['queued'], 1)
        self.assertEqual(result['counts']['waiting'], 1)
        self.assertTrue(result['held'])

    def test_explicit_operator_manual_requeue_preserves_old_claim_and_detaches_standing_permission(self):
        self.engine()
        enabled = self.enable()
        self.arrive()
        self.service.dispatch_maintenance(self.lib['id'])
        task = self.queued()[0]
        retained = self.root / 'retained-output.mkv'
        retained.write_bytes(b'retained-synthetic-result')
        with self.store.transaction():
            task.update(status='blocked', output=str(retained))
            self.store.put('tasks', task['id'], task)
        with acting('operator'):
            self.service.change_maintenance_state(enabled['id'], 1, 'disable')
        claim = copy.deepcopy(self.store.get('settings', task['maintenance']['claim']))
        with patch('curator.maintenance_execution.subprocess.Popen') as launch, self.assertRaises(UserError):
            self.service.maintenance_start_process(task, ['never-automatic'], None, None)
        launch.assert_not_called()
        with (
            acting('ai'),
            patch('curator.service.tools.freeze_handbrake_preset') as freeze,
            self.assertRaisesRegex(UserError, 'explicit operator'),
        ):
            self.service.action(task['id'], 'queue', task['version'])
        freeze.assert_not_called()
        import os

        source = Path(self.new_assets[0]['local_path'])
        before = source.stat()
        original = source.read_bytes()
        source.write_bytes(b'changed-synthetic-source')
        with (
            acting('operator'),
            patch('curator.service.tools.freeze_handbrake_preset') as freeze,
            self.assertRaises(UserError),
        ):
            self.service.action(task['id'], 'queue', task['version'])
        freeze.assert_not_called()
        self.assertIn('maintenance', self.service.get_task(task['id']))
        self.assertEqual(self.store.get('settings', claim['id']), claim)
        source.write_bytes(original)
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        with (
            acting('operator'),
            patch('curator.service.tools.freeze_handbrake_preset', return_value=copy.deepcopy(task['tool_settings'])),
            patch('curator.service.tools.command', return_value=['synthetic-manual-command']),
        ):
            manual = self.service.action(task['id'], 'queue', task['version'])
        self.assertNotIn('maintenance', manual)
        self.assertNotIn('maintenance_proposal', manual)
        self.assertEqual(manual['queued_by'], 'operator')
        self.assertEqual(manual['approval'], manual['version'])
        self.assertEqual(manual['maintenance_origins'][0]['provenance'], task['maintenance'])
        self.assertEqual(self.store.get('settings', claim['id']), claim)
        with patch('curator.maintenance_execution.subprocess.Popen') as launch:
            self.service.maintenance_start_process(manual, ['synthetic-manual-command'], None, None)
        self.assertEqual(launch.call_args.args[0], ['synthetic-manual-command'])
        self.assertEqual(retained.read_bytes(), b'retained-synthetic-result')
        self.assertEqual(self.store.get('settings', claim['id']), claim)
