import copy
import unittest
from unittest.mock import patch

from curator.errors import UserError
from curator.standard_evaluation import evaluate, summarize
from curator.standards import DEFAULTS, type_digest
import test_curator as fixtures


def standard(kind='movie'):
    values = copy.deepcopy(DEFAULTS[kind])
    return dict(kind=kind, revision=0, type_revision=0, type_digest=type_digest(values), values=values)


def asset(**changes):
    result = dict(
        id='a',
        library='l',
        scanned='2026-11-22T12:00:00Z',
        present=True,
        item=dict(summary='A family outing', year=2026, Genre=[{'tag': 'Family'}]),
        technical=dict(width=1920, height=800, duration_seconds=60, bitrate=8_000_000),
    )
    result.update(changes)
    return result


class Evaluation(unittest.TestCase):
    def test_optional_work_does_not_make_movie_or_tv_incomplete_and_inputs_unchanged(self):
        for kind in ('movie', 'show'):
            source, effective = asset(), standard(kind)
            before = copy.deepcopy((source, effective))
            completion, findings = evaluate(source, effective)
            self.assertEqual(completion['status'], 'complete')
            self.assertEqual(completion['dimensions']['artwork']['state'], 'disabled')
            self.assertEqual([row['kind'] for row in findings], ['upscale'])
            self.assertTrue(findings[0]['evidence']['optional'])
            self.assertEqual((source, effective), before)

    def test_other_videos_require_current_date_cast_and_art_not_catalog_fields(self):
        source, effective = asset(), standard('other_videos')
        completion, findings = evaluate(source, effective)
        self.assertEqual(completion['dimensions']['metadata']['missing'], ['originally_available_at'])
        self.assertEqual(completion['dimensions']['cast']['missing'], ['known_people'])
        self.assertEqual(completion['dimensions']['artwork']['missing'], ['poster'])
        self.assertEqual([row['kind'] for row in findings].count('metadata'), 1)
        source['item'].update(originallyAvailableAt='2026-11-22', Role=[{'tag': 'Taylor'}], thumb='/thumb')
        self.assertEqual(evaluate(source, effective)[0]['status'], 'complete')

    def test_disabled_dimensions_need_no_transformation_or_probe(self):
        effective = standard()
        for row in effective['values'].values():
            row['enabled'] = False
        completion, findings = evaluate(asset(item={}, technical={}, blocked='probe failed'), effective)
        self.assertEqual(completion['status'], 'complete')
        self.assertEqual(findings, [])
        self.assertTrue(all(row['state'] == 'disabled' for row in completion['dimensions'].values()))

    def test_override_thresholds_preserve_and_missing_bitrate_are_distinct(self):
        effective = standard()
        source = asset(technical=dict(width=1920, height=1080, duration_seconds=60, bitrate=30_000_000))
        self.assertEqual(evaluate(source, effective)[0]['dimensions']['encoding']['state'], 'needs_attention')
        effective['values']['encoding']['max_mbps_1080'] = 40
        self.assertEqual(evaluate(source, effective, {'max_mbps_1080': 10})[0]['status'], 'complete')
        effective['values']['encoding']['max_mbps_1080'] = None
        self.assertEqual(evaluate(source, effective, {'max_mbps_1080': 40})[0]['status'], 'complete')
        source['technical'].pop('bitrate')
        self.assertEqual(evaluate(source, effective)[0]['dimensions']['encoding']['state'], 'unknown')
        effective['values']['encoding']['preserve_originals'] = True
        self.assertEqual(evaluate(source, effective)[0]['dimensions']['encoding']['state'], 'met')

    def test_required_upscale_and_encoding_both_count_but_use_one_plan(self):
        source = asset(technical=dict(width=1280, height=720, duration_seconds=60, bitrate=40_000_000))
        completion, findings = evaluate(source, standard())
        self.assertEqual(completion['dimensions']['upscaling']['state'], 'needs_attention')
        self.assertEqual(completion['dimensions']['encoding']['state'], 'needs_attention')
        self.assertEqual([row['kind'] for row in findings], ['upscale'])

    def test_targets_respect_aspect_rotation_and_ceiling(self):
        effective = standard()
        effective['values']['encoding']['enabled'] = False
        effective['values']['upscaling']['target'] = '2160'
        for width, height, status in (
            (1920, 1080, 'needs_attention'),
            (3840, 1600, 'complete'),
            (2160, 3840, 'complete'),
            (4096, 2160, 'complete'),
            (5120, 1000, 'unknown'),
        ):
            with self.subTest(width=width, height=height):
                completion, findings = evaluate(asset(technical=dict(width=width, height=height)), effective)
                self.assertEqual(
                    completion['dimensions']['upscaling']['state'], 'met' if status == 'complete' else status
                )
                if width > 4096:
                    self.assertNotIn('upscale', [row['kind'] for row in findings])

    def test_probe_failure_never_reuses_old_technical_as_healthy(self):
        completion, findings = evaluate(asset(blocked='probe failed'), standard())
        self.assertEqual(completion['status'], 'unknown')
        self.assertEqual(completion['dimensions']['upscaling']['state'], 'unknown')
        self.assertEqual(findings[-1]['kind'], 'inspect')
        for changes in ({'present': False}, {'scanned': None}, {'needs_scan': True}):
            self.assertEqual(evaluate(asset(**changes), standard())[0]['status'], 'unknown')

    def test_all_metadata_fields_and_image_array_are_observed_not_guessed(self):
        effective = standard()
        effective['values']['metadata']['required'] = [
            'summary',
            'year',
            'originally_available_at',
            'genres',
            'studio',
            'content_rating',
            'collections',
        ]
        effective['values']['artwork'].update(enabled=True, required=['poster', 'background', 'logo'])
        source = asset(item=dict(summary=' ', year=True, originallyAvailableAt='2026-02-30'))
        completion, _ = evaluate(source, effective)
        self.assertEqual(len(completion['dimensions']['metadata']['missing']), 7)
        source['item'] = dict(
            summary='Summary',
            year='2026',
            originallyAvailableAt='2026-02-28',
            Genre=[{'tag': 'Family'}],
            studio='Home',
            contentRating='G',
            Collection=[{'tag': 'Trips'}],
            Image=[{'type': kind, 'url': '/selected'} for kind in ('coverPoster', 'background', 'clearLogo')],
        )
        self.assertEqual(evaluate(source, effective)[0]['status'], 'complete')

    def test_aggregation_empty_and_unknown_never_look_complete(self):
        self.assertEqual(summarize([])['status'], 'unknown')
        rows = [evaluate(asset(), standard())[0], evaluate(asset(blocked='failed'), standard())[0]]
        summary = summarize(rows)
        self.assertEqual((summary['complete'], summary['unknown'], summary['total']), (1, 1, 2))
        self.assertEqual(summary['dimensions']['cast']['disabled'], 2)


class ScanIntegration(unittest.TestCase):
    setUp = fixtures.Workflows.setUp
    tearDown = fixtures.Workflows.tearDown

    def test_global_threshold_changed_during_probe_is_used_before_finding_commit(self):
        self.plex.items = lambda library: iter([self.plex.item('10')])
        self.service.scan_status[self.lib['id']] = {'count': 0}

        def probe(*args):
            config = self.service.config()
            config['max_mbps_1080'] = 40
            with self.store.transaction():
                self.store.put('settings', 'config', config)
            return dict(width=1920, height=1080, duration_seconds=60, bitrate=30_000_000)

        with patch('curator.service.tools.probe', side_effect=probe):
            self.service._scan(self.lib)
        self.assertNotIn('error', self.service.scan_status[self.lib['id']])
        self.assertFalse(
            [t for t in self.store.all('tasks') if t['kind'] == 'optimize' and t['status'] == 'recommendation']
        )
        current = self.store.all('assets')[0]
        self.assertEqual(current['completion']['dimensions']['encoding']['state'], 'met')

    def test_stricter_standard_keeps_completed_receipt_and_creates_one_unapproved_followup(self):
        source = asset()
        source.update(id=self.asset['id'], library=self.lib['id'], title=self.asset['title'])
        effective = self.service.library_standard(self.lib)
        first = next(row for row in evaluate(source, effective)[1] if row['kind'] == 'upscale')
        with self.store.transaction():
            completed = self.service.task(source, first)
            completed.update(
                status='applied',
                approval=1,
                plan={'approved': 'original'},
                output='/retained/output.mp4',
                output_hash='retained-hash',
                archive={'original': '/retained/original.mp4'},
                published=True,
                result={'verified': True},
            )
            self.store.put('tasks', completed['id'], completed)
        before = copy.deepcopy(completed)
        values = self.service.type_standard('movie')['values']
        values['upscaling']['target'] = '2160'
        self.service.save_type_standard('movie', 0, values)
        required = next(
            row for row in evaluate(source, self.service.library_standard(self.lib))[1] if row['kind'] == 'upscale'
        )
        ids = {completed['id']: None}
        with self.store.transaction():
            self.service.reconcile_findings(source, [required], ids)
            self.service.reconcile_findings(source, [required], ids)
            current = self.service.task(source, required)
        self.assertEqual(self.service.get_task(completed['id']), before)
        self.assertNotEqual(current['id'], completed['id'])
        self.assertEqual(current['supersedes'], completed['id'])
        self.assertEqual((current['status'], current['version'], current['plan']), ('recommendation', 1, {}))
        self.assertNotIn('approval', current)
        self.assertNotIn('output', current)
        self.assertEqual(
            len([t for t in self.store.all('tasks') if t['asset'] == source['id'] and t['kind'] == 'upscale']), 2
        )
        self.assertIn(current['id'], ids)

    def test_scan_consumes_latest_override_even_when_it_changes_during_probe(self):
        self.plex.items = lambda library: iter([self.plex.item('10')])
        self.service.scan_status[self.lib['id']] = {'count': 0}

        def probe(*args):
            self.service.save_library_overrides(
                self.lib['id'],
                0,
                {
                    'metadata': {'enabled': False},
                    'cast': {'enabled': False},
                    'artwork': {'enabled': False},
                    'upscaling': {'enabled': False},
                    'encoding': {'enabled': False},
                },
            )
            return dict(width=640, height=480, duration_seconds=60, bitrate=90_000_000)

        with patch('curator.service.tools.probe', side_effect=probe):
            self.service._scan(self.lib)
        self.assertNotIn('error', self.service.scan_status[self.lib['id']])
        self.assertTrue(all(row['status'] == 'resolved' for row in self.store.all('tasks')))
        self.assertFalse(self.plex.writes)
        self.assertEqual(self.service.state()['completion'][self.lib['id']]['status'], 'complete')

    def test_global_threshold_change_requires_fresh_review_without_changing_task(self):
        finding = evaluate(asset(), self.service.library_standard(self.lib), self.service.config())[1][0]
        with self.store.transaction():
            task = self.service.task(self.asset, finding)
            cfg = self.service.config()
            cfg['max_mbps_1080'] = 40
            self.store.put('settings', 'config', cfg)
        before = copy.deepcopy(self.service.get_task(task['id']))
        with self.assertRaisesRegex(UserError, 'standards changed'):
            self.service._check_task_standard(task)
        self.assertEqual(before, self.service.get_task(task['id']))

    def test_standards_change_invalidates_only_unsubmitted_review_version(self):
        source = self.asset
        first = evaluate(asset(), self.service.library_standard(self.lib))[1][0]
        with self.store.transaction():
            task = self.service.task(source, first)
            task.update(plan={'title': 'My draft'}, approval=task['version'])
            self.store.put('tasks', task['id'], task)
        values = self.service.type_standard('movie')['values']
        values['upscaling']['target'] = '2160'
        self.service.save_type_standard('movie', 0, values)
        with self.assertRaisesRegex(UserError, 'standards changed'):
            self.service._check_task_standard(task)
        second = evaluate(asset(), self.service.library_standard(self.lib))[1][0]
        with self.store.transaction():
            refreshed = self.service.task(source, second)
        self.assertEqual(refreshed['version'], task['version'] + 1)
        self.assertEqual(refreshed['plan'], {'title': 'My draft'})
        self.assertNotIn('approval', refreshed)
        refreshed.update(status='queued', approval=refreshed['version'])
        with self.store.transaction():
            self.store.put('tasks', refreshed['id'], refreshed)
            self.service.reconcile_findings(source, [first])
        self.assertEqual(self.service.get_task(refreshed['id']), refreshed)

    def test_state_reports_latest_standards_without_network_or_work(self):
        with self.store.transaction():
            self.store.put(
                'assets',
                self.asset['id'],
                dict(self.asset, scanned='2026-11-22', item=asset()['item'], technical=asset()['technical']),
            )
        before = copy.deepcopy(self.store.all('tasks'))
        with patch.object(self.service, 'checked_client', side_effect=AssertionError('network')):
            state = self.service.state()
        self.assertEqual(state['completion'][self.lib['id']]['status'], 'complete')
        self.assertEqual(self.store.all('tasks'), before)
        values = self.service.type_standard('movie')['values']
        values['metadata']['required'].append('studio')
        self.service.save_type_standard('movie', 0, values)
        self.assertEqual(self.service.state()['completion'][self.lib['id']]['status'], 'needs_attention')
