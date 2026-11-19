import errno
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from curator import tools
from curator.service import Service
from curator.store import Store


class UnattendedRuns(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.addCleanup(self.store.close)
        self.service = Service(self.store)
        self.media = Path(self.temp.name).resolve() / 'media'
        self.media.mkdir()
        self.source = self.media / 'source.mp4'
        self.source.write_bytes(b'0123456789')
        with self.store.transaction():
            for key in ('one', 'two'):
                self.store.put(
                    'libraries',
                    key,
                    dict(id=key, title=key, mappings=[dict(plex_root='/media', local_root=str(self.media))]),
                )
            for i in range(2):
                asset = dict(
                    id=str(i),
                    library='one' if i == 0 else 'two',
                    rating_key=str(i),
                    local_path=str(self.source),
                    plex_path='/media/source.mp4',
                    fingerprint=tools.fingerprint(self.source),
                    technical={'duration_seconds': 60},
                    item={},
                )
                self.store.put('assets', str(i), asset)
                self.store.put(
                    'tasks',
                    str(i),
                    dict(
                        id=str(i),
                        asset=str(i),
                        library=asset['library'],
                        kind='optimize',
                        status='queued',
                        version=1,
                        approval=1,
                        source=asset['fingerprint'],
                        tool_settings={'frozen': 'keep'},
                        plan={'handbrake_preset': 'Saved'},
                    ),
                )

    def test_defaults_are_scoped_and_never_rewrite_queued_approvals(self):
        before = self.service.get_task('0')
        self.service.save_processing_defaults('one', 'optimize', {'handbrake_preset': 'New'})
        self.assertEqual(self.service.processing_defaults()['one']['optimize']['handbrake_preset'], 'New')
        self.assertNotIn('two', self.service.processing_defaults())
        self.assertEqual(self.service.get_task('0'), before)
        with self.assertRaises(ValueError):
            self.service.save_processing_defaults('one', 'upscale', {'plex_token': 'no'})

    def test_readiness_is_read_only_groups_shared_volume_and_uses_measured_history(self):
        with self.store.transaction():
            self.store.put(
                'tasks',
                'history',
                dict(
                    id='history',
                    asset='0',
                    library='one',
                    kind='optimize',
                    status='applied',
                    version=1,
                    processing_seconds=120,
                    source={'size': 10},
                    result={'size_bytes': 20},
                ),
            )
        self.service.set_queue_limits({'optimize': 2})
        before = self.store.all('tasks')
        with (
            patch('curator.run_readiness.tools.command', return_value=['synthetic']),
            patch('curator.run_readiness.shutil.disk_usage', return_value=type('Usage', (), {'free': 1000})()),
            patch('subprocess.Popen', side_effect=AssertionError('Preflight must not execute tools')),
        ):
            readiness = self.service.run_readiness()
        self.assertEqual(readiness['waiting'], 2)
        self.assertEqual(readiness['issues'], [])
        self.assertEqual(len(readiness['volumes']), 1)
        self.assertEqual(readiness['volumes'][0]['estimated_extra_bytes'], 80)
        self.assertEqual(readiness['processing_eta_seconds'], 120)
        self.assertEqual(self.store.all('tasks'), before)

    def test_unknown_estimates_are_not_guessed_and_missing_source_is_reported(self):
        with patch('curator.run_readiness.tools.command', return_value=['synthetic']):
            result = self.service.run_readiness()
        self.assertIsNone(result['processing_eta_seconds'])
        self.assertEqual(result['volumes'][0]['unknown_jobs'], 2)
        self.source.unlink()
        result = self.service.run_readiness()
        self.assertEqual(len(result['issues']), 2)

    def test_remembered_upscale_settings_apply_only_to_new_approvals_without_credentials(self):
        self.service.save_config({'topaz_filter': 'workspace-filter', 'plex_token': 'private-token'})
        self.service.save_processing_defaults('one', 'upscale', {'topaz_filter': 'library-filter', 'topaz_quality': 65})
        before = self.service.get_task('0')
        candidate = {**before, 'status': 'recommendation', 'kind': 'upscale'}
        with patch('curator.service.tools.command', return_value=['synthetic']):
            prepared = self.service._prepare_queue(candidate, None)
        self.assertEqual(prepared['tool_settings']['topaz_filter'], 'library-filter')
        self.assertNotIn('plex_token', prepared['tool_settings'])
        self.assertEqual(self.service.get_task('0'), before)

    def test_explicit_failed_retry_rechecks_source_and_never_requeues_retained_outputs(self):
        with self.store.transaction():
            for key in ('0', '1'):
                task = self.service.get_task(key)
                task.update(status='blocked', kind='metadata', plan={'changes': {'title': 'Reviewed'}})
                if key == '1':
                    task['output'] = 'retained.mp4'
                self.store.put('tasks', key, task)
        result = self.service.retry_failed_results([{'id': '0', 'version': 1}, {'id': '1', 'version': 1}])
        self.assertEqual(result['queued'], 1)
        self.assertFalse(result['started'])
        self.assertEqual(self.service.get_task('1')['status'], 'blocked')

    def test_transient_read_retry_is_bounded_and_waits_before_next_attempt(self):
        with (
            patch.object(self.service, 'asset', side_effect=OSError(errno.EAGAIN, 'temporary')),
            patch('subprocess.Popen', side_effect=AssertionError('No processing may start')),
        ):
            self.assertEqual(self.service._execute('0'), 'retry_scheduled')
            task = self.service.get_task('0')
            self.assertEqual(task['preflight_retry_count'], 1)
            self.assertEqual(self.service._execute('0'), 'retry_wait')
            with patch('curator.service.time.time', return_value=task['retry_at'] + 1):
                self.assertEqual(self.service._execute('0'), 'retry_scheduled')
            task = self.service.get_task('0')
            with patch('curator.service.time.time', return_value=task['retry_at'] + 1):
                self.service._execute('0')
        task = self.service.get_task('0')
        self.assertEqual(task['status'], 'blocked')
        self.assertEqual(task['preflight_retry_count'], 2)

    def test_an_error_after_processing_starts_is_never_automatically_replayed(self):
        asset = self.store.get('assets', '0')
        with (
            patch.object(self.service, 'asset', return_value=asset),
            patch.object(self.service, '_process', side_effect=OSError(errno.EAGAIN, 'uncertain')),
        ):
            self.service._execute('0')
        task = self.service.get_task('0')
        self.assertEqual(task['status'], 'blocked')
        self.assertFalse(task.get('retry_at'))

    def test_fixed_run_membership_ignores_new_jobs_and_latches_terminal_counts(self):
        identity = self.service.create_run_receipt(None, None)
        first = self.service.get_task('0')
        self.service._save(first, status='awaiting_review')
        with self.store.transaction():
            self.store.put(
                'tasks',
                'later',
                dict(id='later', asset='0', library='one', kind='optimize', status='queued', version=1, approval=1),
            )
        second = self.service.get_task('1')
        self.service._save(second, status='blocked')
        summary = next(r for r in self.service.run_summaries() if r['id'] == identity)
        self.assertEqual(summary['phase'], 'needs_attention')
        self.assertEqual(summary['counts']['total'], 2)
        self.assertEqual(summary['counts']['remaining'], 0)
        self.service._save(first, status='applied', published=True)
        self.assertEqual(next(r for r in self.service.run_summaries() if r['id'] == identity)['counts']['ready'], 1)
        extra = self.service.create_run_receipt(None, None)
        self.assertNotEqual(identity, extra)

    def test_restart_holds_run_without_replaying_and_queue_attempt_changes_on_requeue(self):
        identity = self.service.create_run_receipt(None, None)
        old = self.service.get_task('0')['queue_attempt']
        fresh = Service(self.store)
        self.assertFalse(fresh.queue_running())
        self.assertEqual(next(r for r in fresh.run_summaries() if r['id'] == identity)['phase'], 'interrupted')
        task = fresh.get_task('0')
        with self.store.transaction():
            task['status'] = 'blocked'
            self.store.put('tasks', '0', task)
            task['status'] = 'queued'
            self.store.put('tasks', '0', task)
        self.assertNotEqual(old, fresh.get_task('0')['queue_attempt'])
