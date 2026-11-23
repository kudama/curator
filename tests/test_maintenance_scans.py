import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

import test_curator
from test_maintenance_inventory import InventoryClient
from test_maintenance_policy import rule
from test_maintenance_rules import STANDARD
from curator.errors import UserError
from curator.history import acting
from curator.service import Service
from curator.tools import digest as file_hash


class ScanService(Service):
    def maintenance_tool_snapshot(self, values, captured=None):
        return dict(fixture='synthetic executable')

    def ensure_maintenance_scheduler(self):
        pass  # Tests tick exact disposable state explicitly, never a background schedule.

    def start_pending_maintenance(self, kind=None):
        return []


class Scans(unittest.TestCase):
    setUp = test_curator.Workflows.setUp
    tearDown = test_curator.Workflows.tearDown

    def engine(self):
        self.client = InventoryClient()
        self.client.rows = [self.plex.item('10')]
        request = self.client.request
        self.client.request = lambda path, **kwargs: (
            dict(machineIdentifier='server') if path == '/identity' else request(path, **kwargs)
        )
        self.service = ScanService(self.store, lambda *args: self.client)
        self.clock = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
        self.service.maintenance_clock = lambda: self.clock
        for item in [
            patch('curator.maintenance.POLICY_ACCEPTED', True),
            patch('curator.maintenance.standard_identity', return_value=STANDARD),
            patch(
                'curator.maintenance_scans.evaluated',
                side_effect=lambda service, asset: dict(
                    standard=STANDARD, completion={'status': 'complete'}, findings=[]
                ),
            ),
        ]:
            item.start()
            self.addCleanup(item.stop)
        self.values = rule(library=self.lib['id'], roots=['/plex'], excluded_paths=[])
        self.values['limits'].update(items_per_run=20, items_per_day=100)
        caps = dict(limits=self.values['limits'], timezone=self.values['timezone'])
        with acting('operator'):
            self.service.save_maintenance_caps(None, 0, caps)
            self.service.save_maintenance_caps(self.lib['id'], 0, caps)
            self.service.observe_maintenance_scan(self.lib['id'], [self.asset['id']])
            saved = self.service.save_maintenance_rule(None, 0, self.values)
            preview = self.service.preview_maintenance_enable(saved['id'], 1)
            self.enabled = self.service.enable_maintenance_rule(preview['preview'], preview['digest'], 'scan')
            self.service.pause_maintenance_scope(None, False)
        self.fake = self.root / 'fake-probe'
        self.fake.write_text(
            '#!'
            + sys.executable
            + '\nimport json,sys\nfrom pathlib import Path\nassert Path(sys.argv[-1]).read_bytes()==b"new-synthetic-video"\nprint(json.dumps({"streams":[{"codec_type":"video","codec_name":"h264","width":1920,"height":1080}],"format":{"duration":"1","size":"19","format_name":"mov"}}))\n'
        )
        self.fake.chmod(0o700)
        with self.store.transaction():
            self.store.put('settings', 'config', dict(ffprobe=str(self.fake)))

    def arrive(self):
        self.new = self.media / 'new.mp4'
        self.new.write_bytes(b'new-synthetic-video')
        self.client.rows.append(
            dict(
                ratingKey='99',
                guid='new-guid',
                title='Synthetic arrival',
                Media=[{'Part': [{'id': '99', 'file': '/plex/new.mp4'}]}],
            )
        )

    def scan(self):
        run = self.service.admit_maintenance_scan(self.enabled['id'])
        self.assertIsNotNone(run)
        result = self.service.execute_maintenance_scan(run['id'])
        with self.store.transaction():
            job = self.service.file_operation(run['job'])
            job['phase'] = 'complete'
            self.store.put('settings', job['id'], job)
        self.clock += timedelta(minutes=60)
        return result

    def test_no_baseline_or_old_file_probe_and_new_stable_source_uses_real_bounded_child(self):
        self.engine()
        original = file_hash(self.file)
        self.arrive()
        with patch(
            'curator.maintenance_scans.tools.probe', wraps=__import__('curator.tools', fromlist=['probe']).probe
        ) as probe:
            first = self.scan()
            self.assertEqual(first['phase'], 'complete')
            self.assertEqual(first['items'][0]['phase'], 'observing')
            probe.assert_not_called()
            second = self.scan()
            self.assertEqual(second['phase'], 'complete', second)
            self.assertEqual(second['items'][0]['phase'], 'complete', second)
            self.assertEqual(probe.call_count, 1)
            third = self.scan()
            self.assertEqual(third['items'], [])
            self.assertEqual(probe.call_count, 1)
        self.assertEqual(file_hash(self.file), original)
        self.assertEqual(self.new.read_bytes(), b'new-synthetic-video')
        arrivals = self.service.maintenance_arrivals(self.lib['id'])
        self.assertEqual(len(arrivals), 1)
        self.assertEqual(arrivals[0]['phase'], 'ready')
        self.assertEqual(self.plex.writes, [])

    def test_bad_complete_inventory_never_resolves_or_probes_any_media(self):
        self.engine()
        self.arrive()
        self.client.edit = lambda block, n: dict(block, totalSize=10001)
        with (
            patch('curator.maintenance_scans.map_path') as mapping,
            patch('curator.maintenance_scans.tools.probe') as probe,
        ):
            result = self.scan()
        self.assertEqual(result['phase'], 'failed')
        mapping.assert_not_called()
        probe.assert_not_called()
        self.assertIn('catalogue cap', result['error'])
        self.assertTrue(self.service.maintenance_rule(self.enabled['id'])['paused'])

    def test_outside_roots_exclusions_and_baseline_rematch_never_resolve_media(self):
        self.engine()
        self.client.rows += [
            dict(ratingKey='99', Media=[{'Part': [{'file': '/outside/no.mp4'}]}]),
            dict(self.plex.item('10'), ratingKey='100', guid=self.asset['item'].get('guid')),
        ]
        # A rematch retaining a source fingerprint is filtered after its one bounded stat,
        # while path/root and exact baseline identities are filtered before any stat.
        self.client.rows = self.client.rows[:2]
        with patch('curator.maintenance_scans.map_path') as mapping:
            result = self.scan()
        mapping.assert_not_called()
        self.assertEqual(result['items'], [])

    def test_cadence_coalesces_and_disable_cancels_only_unstarted_scan(self):
        self.engine()
        first = self.service.admit_maintenance_scan(self.enabled['id'])
        self.assertIsNone(self.service.admit_maintenance_scan(self.enabled['id']))
        with acting('operator'):
            self.service.change_maintenance_state(self.enabled['id'], 1, 'disable')
        self.assertEqual(self.service.file_operation(first['job'])['phase'], 'cancelled')
        self.assertEqual(self.service.maintenance_scan_run(first['id'])['phase'], 'revoked')
        with patch.object(self.service, 'client') as client:
            with self.assertRaises(UserError):
                self.service.execute_maintenance_scan(first['id'])
        client.assert_not_called()

    def test_revocation_during_inventory_prevents_first_media_access(self):
        self.engine()
        self.arrive()
        original = self.client.request

        def revoke(path, **kwargs):
            result = original(path, **kwargs)
            with acting('operator'):
                if self.service.maintenance_rule(self.enabled['id'])['enabled']:
                    self.service.change_maintenance_state(self.enabled['id'], 1, 'disable')
            return result

        self.client.request = revoke
        with patch('curator.maintenance_scans.map_path') as mapping:
            result = self.scan()
        self.assertEqual(result['phase'], 'failed')
        mapping.assert_not_called()

    def test_hard_probe_output_cap_retains_artifacts_and_restart_never_replays(self):
        self.engine()
        self.arrive()
        self.scan()
        self.fake.write_text('#!' + sys.executable + '\nimport os\nos.write(1,b"x"*16000000)\n')
        result = self.scan()
        self.assertEqual(result['phase'], 'partial')
        claims = [r for r in self.store.all('settings') if isinstance(r, dict) and r.get('phase') == 'uncertain']
        self.assertEqual(len(claims), 1)
        self.assertLessEqual(
            Path(claims[0]['artifacts'][0]).stat().st_size, self.values['options']['probe_output_bytes']
        )
        self.service.recover_maintenance_scans()
        self.assertEqual(self.store.get('settings', claims[0]['id'])['phase'], 'uncertain')
        self.assertTrue(self.service.maintenance_rule(self.enabled['id'])['paused'])

    def test_maintenance_only_file_worker_does_not_drain_manually_queued_job(self):
        self.engine()
        run = self.service.admit_maintenance_scan(self.enabled['id'])
        manual = self.service.queue_file_operation('repair', {'task': self.task['id']}, background=True, start=False)
        seen = []

        def execute(job):
            seen.append(job['id'])

        with patch.object(self.service, '_execute_file_operation', side_effect=execute):
            self.service.start_file_queue(maintenance_only=True)
            until = time.monotonic() + 5
            while self.service.file_workers and time.monotonic() < until:
                time.sleep(0.01)
        self.assertEqual(seen, [run['job']])
        self.assertEqual(self.service.file_operation(manual['id'])['phase'], 'waiting')
        self.assertFalse(self.service.file_queue_paused())

    def test_file_queue_pause_and_default_disabled_scheduler_do_nothing(self):
        self.engine()
        with self.store.transaction():
            self.store.put('settings', self.service.pause_key(None, 'file_operations'), True)
        with patch.object(self.service, 'client') as client:
            self.assertEqual(self.service.maintenance_tick(), [])
        client.assert_not_called()
        self.assertTrue(self.service.file_queue_paused())
        with (
            patch('curator.maintenance.POLICY_ACCEPTED', False),
            patch.object(self.service, 'admit_maintenance_scan') as admit,
        ):
            self.assertEqual(self.service.maintenance_tick(), [])
        admit.assert_not_called()

    def test_pending_scan_projection_uses_its_reserved_next_sequence_not_old_baseline(self):
        self.engine()
        baseline = self.store.get('settings', 'maintenance-arrivals:' + self.lib['id'])
        run = self.service.admit_maintenance_scan(self.enabled['id'])
        self.assertEqual(run['sequence'], baseline['sequence'] + 1)
        result = self.service.maintenance_configuration()['rules'][0]['operational']
        self.assertEqual(result['counts']['queued'], 1)
        self.assertTrue(all(row['latest_run_items'] == 19 for row in result['remaining']))
        self.assertTrue(all(row['run_sequence'] == run['sequence'] for row in result['remaining']))

    def test_malformed_later_inventory_row_prevents_earlier_new_source_observation(self):
        self.engine()
        self.arrive()
        self.client.rows.append(dict(ratingKey='100', Media=[dict(Part=['malformed'])]))
        with (
            patch('curator.maintenance_scans.map_path') as mapping,
            patch('curator.maintenance_scans.tools.probe') as probe,
        ):
            result = self.scan()
        self.assertEqual(result['phase'], 'failed')
        mapping.assert_not_called()
        probe.assert_not_called()
        self.assertIn('malformed', result['error'])
