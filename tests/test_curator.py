import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from curator.paths import map_path
from curator.quality import assess
from curator.store import Store
from curator.service import Service
from curator.plex import Plex, PlexError
from curator.tools import command, fingerprint, validate
from curator.web import Handler


class Paths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.movie = self.root / 'A film ü.mkv'
        self.movie.write_bytes(b'film')
        self.mappings = [dict(plex_root='/media/Movies', local_root=str(self.root))]

    def tearDown(self):
        self.tmp.cleanup()

    def test_unicode_spaces(self):
        self.assertEqual(map_path('/media/Movies/A film ü.mkv', self.mappings), self.movie.resolve())

    def test_component_prefix(self):
        with self.assertRaises(ValueError):
            map_path('/media/MoviesElse/A film ü.mkv', self.mappings)

    def test_longest_root(self):
        extra = dict(plex_root='/media/Movies/sub', local_root=str(self.root))
        self.assertEqual(map_path('/media/Movies/sub/A film ü.mkv', self.mappings + [extra]), self.movie.resolve())

    def test_duplicate_root(self):
        with self.assertRaises(ValueError):
            map_path('/media/Movies/A film ü.mkv', self.mappings * 2)

    def test_traversal(self):
        for source in ['/media/Movies/../x', 'media/Movies/x', '//media/Movies/x']:
            with self.subTest(source=source), self.assertRaises(ValueError):
                map_path(source, self.mappings)

    def test_root_traversal(self):
        for field in ['plex_root', 'local_root']:
            bad = dict(self.mappings[0]);bad[field] += '/../escape'
            with self.assertRaises(ValueError):
                map_path('/media/Movies/A film ü.mkv', [bad])

    def test_missing_mount(self):
        with self.assertRaises(ValueError):
            map_path('/media/Movies/a.mkv', [dict(plex_root='/media/Movies', local_root=str(self.root / 'absent'))])

    def test_symlink_escape(self):
        (self.root / 'link').symlink_to(self.root.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            map_path('/media/Movies/link/outside', self.mappings, False)


class Quality(unittest.TestCase):
    def media(self, **values):
        return dict(width=1920, height=1080, duration_seconds=100, size_bytes=100_000_000,
                    codec='h264', **values)

    def test_720_recommends_upscale(self):
        self.assertEqual(assess(dict(width=1280, height=720))[0]['kind'], 'upscale')

    def test_cinematic_and_portrait(self):
        for width, height in [(1920, 800), (1080, 1920), (3840, 1600)]:
            self.assertTrue(assess(dict(width=width, height=height))[0]['evidence']['optional'])

    def test_optional_upscale_keeps_separate_handbrake_recommendation(self):
        findings=assess(dict(width=3840,height=2160,duration_seconds=60,bitrate=80_000_000))
        self.assertEqual([x['kind'] for x in findings], ['upscale','optimize'])
        self.assertTrue(findings[0]['evidence']['optional'])

    def test_unknown_or_invalid(self):
        for width in [0, None, True, float('nan'), -1, '1920']:
            self.assertEqual(assess(dict(width=width, height=1080))[0]['kind'], 'inspect')

    def test_high_bitrate_is_recommendation_not_saving_claim(self):
        result = assess(self.media(bitrate=30_000_000))
        optimization=next(x for x in result if x['kind']=='optimize')
        self.assertIsNone(optimization['evidence']['estimated_savings'])

    def test_codec_alone_not_reason(self):
        for codec in ['h264', 'mpeg2video', 'hevc']:
            self.assertEqual([x['kind'] for x in assess(dict(width=1920, height=1080, codec=codec))], ['upscale'])

    def test_zero_duration_no_optimization(self):
        self.assertEqual([x['kind'] for x in assess(dict(width=1920, height=1080, duration_seconds=0, size_bytes=9999999999, bitrate=999999999))], ['upscale'])

    def test_preserve_remux(self):
        self.assertEqual([x['kind'] for x in assess(self.media(bitrate=100_000_000, preserve_quality=True))], ['upscale'])

    def test_custom_threshold(self):
        self.assertEqual([x['kind'] for x in assess(self.media(bitrate=30_000_000), {'max_mbps_1080': 40})], ['upscale'])

    def test_upscale_and_encoding_are_one_plan(self):
        findings=assess(dict(width=1280,height=720,duration_seconds=60,bitrate=40_000_000))
        self.assertEqual([x['kind'] for x in findings],['upscale'])


class FakePlex:
    def __init__(self, *args):
        self.rows = [dict(ratingKey='10', type='movie', title='Film', summary='Before',
                          Media=[{'Part': [{'file': '/plex/film.mkv'}]}])]
        self.writes = []

    def item(self, key):
        return self.rows[0].copy()

    def edit(self, library, item, changes):
        self.writes.append(changes)
        self.rows[0].update(changes)
        return self.rows[0]

    def refresh(self, key):
        self.writes.append('refresh')


class Workflows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.media = self.root / 'share';self.media.mkdir()
        self.file = self.media / 'film.mkv';self.file.write_bytes(b'original-video')
        self.store = Store(self.root / 'state')
        self.plex = FakePlex()
        self.service = Service(self.store, lambda *args: self.plex)
        self.lib = dict(id='server:1', server='server', key='1', title='Movies', type='movie',
                        profile='commercial', mappings=[dict(plex_root='/plex', local_root=str(self.media))], themes=[])
        self.asset = dict(id='a'*24, library='server:1', title='Film', rating_key='10', plex_path='/plex/film.mkv',
                          local_path=str(self.file.resolve()), fingerprint=fingerprint(self.file), item=self.plex.item('10'), present=True)
        with self.store.transaction():
            self.store.put('libraries', self.lib['id'], self.lib)
            self.store.put('assets', self.asset['id'], self.asset)
            self.task = self.service.task(self.asset, dict(kind='metadata', reason='Fix description'))

    def tearDown(self):
        self.store.close();self.tmp.cleanup()

    def edit(self):
        return self.service.edit_task(self.task['id'], {'changes': {'summary': 'After'}}, 1)

    def test_rescan_deduplicates(self):
        with self.store.transaction():
            self.service.task(self.asset, dict(kind='metadata', reason='Fix description again'))
        self.assertEqual(len(self.store.all('tasks')), 1)

    def test_scan_hides_deleted_file_even_when_plex_retains_its_record(self):
        self.file.unlink();self.plex.items=lambda library:iter([self.plex.item('10')])
        self.service.scan_status[self.lib['id']]={}
        with patch('curator.service.tools.probe') as probe:self.service._scan(self.lib)
        probe.assert_not_called()
        self.assertFalse(self.store.get('assets',self.asset['id'])['present'])
        self.assertTrue(self.store.get('assets',self.asset['id'])['missing_file'])
        self.assertEqual(self.service.get_task(self.task['id'])['status'],'recommendation')

    def test_presence_sync_prunes_deleted_file_without_probing_or_deleting_history(self):
        self.file.unlink();self.plex.items=lambda library:iter([self.plex.item('10')])
        with patch('curator.service.tools.probe') as probe:self.service._sync_presence(self.lib)
        probe.assert_not_called();self.assertFalse(self.store.get('assets',self.asset['id'])['present'])
        self.assertIsNotNone(self.service.get_task(self.task['id']));self.assertEqual(self.plex.writes,[])

    def test_presence_sync_hides_catalog_removed_item(self):
        self.plex.items=lambda library:iter([]);self.service._sync_presence(self.lib)
        self.assertFalse(self.store.get('assets',self.asset['id'])['present'])
        self.assertTrue(self.file.exists())

    def test_presence_sync_preserves_entries_when_device_or_mount_is_unavailable(self):
        self.file.unlink();self.plex.items=lambda library:iter([self.plex.item('10')])
        with self.store.transaction():self.store.put('assets',self.asset['id'],{**self.asset,'fingerprint':{**self.asset['fingerprint'],'device':-1}})
        self.service._sync_presence(self.lib)
        asset=self.store.get('assets',self.asset['id'])
        self.assertTrue(asset['present']);self.assertTrue(asset['availability_error'])

    def test_presence_sync_does_not_prune_after_partial_plex_failure(self):
        def partial(library):
            yield self.plex.item('10')
            raise ValueError('Network failed')
        self.plex.items=partial;self.service._sync_presence(self.lib)
        self.assertTrue(self.store.get('assets',self.asset['id'])['present'])
        self.assertIn('failed',self.service.presence_status[self.lib['id']]['error'])

    def test_presence_sync_returns_restored_files_for_rescan(self):
        self.plex.items=lambda library:iter([self.plex.item('10')])
        with self.store.transaction():self.store.put('assets',self.asset['id'],{**self.asset,'present':False,'missing_file':True})
        self.service._sync_presence(self.lib)
        asset=self.store.get('assets',self.asset['id'])
        self.assertTrue(asset['present']);self.assertFalse(asset['missing_file'])
        self.assertIn('scan',asset['availability_error'])

    def test_scan_resolves_old_probe_failure_and_reopens_if_it_recurs(self):
        self.plex.items = lambda library: iter([self.plex.item('10')])
        self.service.scan_status[self.lib['id']] = {}
        with patch('curator.service.tools.probe', side_effect=ValueError('Video probe failed')):
            self.service._scan(self.lib)
        task = next(t for t in self.store.all('tasks') if t['kind'] == 'inspect')
        self.assertEqual(task['reason'], 'Video probe failed')
        technical = dict(width=1920, height=1080, codec='h264', duration_seconds=100,
                         size_bytes=100, bitrate=8, streams=[])
        with patch('curator.service.tools.probe', return_value=technical):
            self.service._scan(self.lib)
        self.assertEqual(self.service.get_task(task['id'])['status'], 'resolved')
        with patch('curator.service.tools.probe', side_effect=ValueError('Video probe failed')):
            self.service._scan(self.lib)
        reopened = self.service.get_task(task['id'])
        self.assertEqual(reopened['status'], 'recommendation')
        self.assertEqual(reopened['version'], task['version'] + 1)
        self.assertEqual(len([t for t in self.store.all('tasks') if t['kind'] == 'inspect']), 1)
        self.assertEqual(self.plex.writes, [])

    def test_optional_upscale_does_not_reopen_completed_work(self):
        from curator.service import identifier
        task=dict(self.task,id=identifier(self.asset['id'],'upscale'),kind='upscale',status='applied',published=True)
        with self.store.transaction():
            self.store.put('tasks',task['id'],task)
            self.service.reconcile_findings(self.asset,[dict(kind='upscale',reason='Optional',evidence={'optional':True})])
        self.assertEqual(self.service.get_task(task['id'])['status'],'applied')
        self.assertTrue(self.service.get_task(task['id'])['published'])

    def test_new_scan_finding_reopens_applied_task_without_old_approval_or_output(self):
        previous=dict(self.task,status='applied',approval=1,output='old-output',published=True,
                      plan={'changes':{'summary':'Old proposal'}},result={'verified':True})
        with self.store.transaction():
            self.store.put('tasks',previous['id'],previous)
            self.service.reconcile_findings(self.asset,[{'kind':'metadata','reason':'Description missing again'}])
        reopened=self.service.get_task(previous['id'])
        self.assertEqual(reopened['status'],'recommendation')
        self.assertEqual(reopened['version'],2)
        self.assertEqual(reopened['plan'],{})
        self.assertNotIn('approval',reopened)
        self.assertNotIn('published',reopened)
        self.assertNotIn('output',reopened)

    def test_cannot_queue_without_preview(self):
        with self.assertRaises(ValueError):
            self.service.action(self.task['id'], 'queue', 1)

    def optimization_task(self):
        with self.store.transaction():
            return self.service.task(self.asset, dict(kind='optimize', reason='Review bitrate'))

    def test_optimization_requires_task_preset_even_if_default_is_configured(self):
        self.service.save_config({'handbrake_preset': 'App default'})
        task=self.optimization_task()
        with self.assertRaisesRegex(ValueError,'this task'):
            self.service.action(task['id'],'queue',task['version'])
        self.assertEqual(self.service.get_task(task['id'])['status'],'recommendation')

    def test_task_preset_is_snapshotted_and_edit_invalidates_approval(self):
        task=self.optimization_task()
        saved=self.service.edit_task(task['id'],{'handbrake_preset':'Hardware/Chosen preset'},1)
        settings={'handbrake':'/chosen/HandBrakeCLI','handbrake_preset':'Captured',
                  'handbrake_preset_file':'private/snapshot.json','handbrake_preset_hash':'hash'}
        with patch('curator.service.tools.freeze_handbrake_preset',return_value=settings) as freeze, \
             patch('curator.service.tools.command',return_value=['command']):
            queued=self.service.action(task['id'],'queue',saved['version'])
        self.assertEqual(freeze.call_args.args[1],'Hardware/Chosen preset')
        self.assertEqual(queued['tool_settings']['handbrake_preset_file'],'private/snapshot.json')
        changed=self.service.edit_task(task['id'],{'handbrake_preset':'General/Other preset'},saved['version'])
        self.assertNotIn('approval',changed)
        self.assertEqual(changed['status'],'recommendation')

    def test_queue_saves_selected_preset_and_approves_its_new_version(self):
        task = self.optimization_task()
        with patch('curator.service.tools.freeze_handbrake_preset', return_value={'handbrake_preset_file':'snapshot'}) as freeze, \
             patch('curator.service.tools.command', return_value=['command']):
            queued = self.service.action(task['id'], 'queue', 1, 'General/Chosen')
        self.assertEqual(queued['plan']['handbrake_preset'], 'General/Chosen')
        self.assertEqual(queued['version'], 2)
        self.assertEqual(queued['approval'], 2)
        self.assertEqual(queued['status'], 'queued')
        self.assertEqual(freeze.call_args.args[1], 'General/Chosen')
        with self.assertRaisesRegex(ValueError, 'Stale'):
            self.service.action(task['id'], 'queue', 1, 'General/Other')

    def test_queue_preset_failure_leaves_plan_and_version_unchanged(self):
        task = self.optimization_task()
        with patch('curator.service.tools.freeze_handbrake_preset', side_effect=ValueError('Preset unavailable')):
            with self.assertRaisesRegex(ValueError, 'Preset unavailable'):
                self.service.action(task['id'], 'queue', 1, 'Missing')
        saved = self.service.get_task(task['id'])
        self.assertEqual(saved['version'], 1)
        self.assertEqual(saved['status'], 'recommendation')
        self.assertNotIn('handbrake_preset', saved['plan'])
        self.assertNotIn('approval', saved)

    def test_non_video_task_cannot_set_a_handbrake_preset(self):
        with self.assertRaises(ValueError):
            self.service.edit_task(self.task['id'],{'handbrake_preset':'Some preset'},1)

    def test_edit_invalidates_approval(self):
        task = self.edit();self.service.action(task['id'], 'queue', 2)
        result = self.service.edit_task(task['id'], {'changes': {'summary': 'Different'}}, 2)
        self.assertEqual(result['status'], 'recommendation')
        self.assertNotIn('approval', result)

    def test_stale_version(self):
        self.edit()
        with self.assertRaises(ValueError):
            self.service.action(self.task['id'], 'queue', 1)

    def test_source_change_blocks(self):
        task = self.edit();self.service.action(task['id'], 'queue', 2)
        self.file.write_bytes(b'changed')
        self.service._execute(task['id'])
        self.assertEqual(self.service.get_task(task['id'])['status'], 'blocked')
        self.assertEqual(self.plex.writes, [])

    def test_rescan_cannot_refresh_a_stale_approval(self):
        task = self.edit();self.service.action(task['id'], 'queue', 2)
        self.file.write_bytes(b'changed')
        self.asset['fingerprint'] = fingerprint(self.file)
        with self.store.transaction():self.store.put('assets', self.asset['id'], self.asset)
        self.service._execute(task['id'])
        self.assertEqual(self.plex.writes, [])
        self.assertIn('since queue approval', self.service.get_task(task['id'])['error'])

    def test_external_metadata_change_blocks(self):
        task = self.edit();self.service.action(task['id'], 'queue', 2)
        self.plex.rows[0]['summary'] = 'Other edit'
        self.service._execute(task['id'])
        self.assertEqual(self.plex.writes, [])

    def test_metadata_preview_apply_readback(self):
        task = self.edit();self.service.action(task['id'], 'queue', 2);self.service._execute(task['id'])
        self.assertEqual(self.plex.writes, [{'summary': 'After'}])
        self.assertEqual(self.service.get_task(task['id'])['status'], 'applied')

    def test_metadata_tag_capitalization_uses_plex_spelling(self):
        def edit(library, item, changes):
            self.plex.writes.append(changes)
            self.plex.rows[0]['Genre'] = [{'tag': value.capitalize()} for value in changes['genre']]
            return self.plex.item('10')
        self.plex.edit = edit
        result = self.service.apply_metadata(self.task['id'], 1, {'genre': ['travel', 'outdoors']})
        self.assertEqual(result['status'], 'applied')
        self.assertEqual(result['metadata']['genre'], ['Outdoors', 'Travel'])
        self.assertEqual(self.service.get_task(self.task['id'])['status'], 'applied')

    def test_tag_identity_is_case_insensitive_but_text_and_cast_are_exact(self):
        for field in ['genre', 'collection', 'label']:
            self.assertTrue(Service._same_metadata({field:['Travel','Outdoors']},{field:['outdoors','travel']}))
            self.assertFalse(Service._same_metadata({field:['Travel']},{field:['travel','outdoors']}))
            self.assertFalse(Service._same_metadata({field:['Different']},{field:['travel']}))
        self.assertFalse(Service._same_metadata({'summary':'Text'},{'summary':'text'}))
        self.assertFalse(Service._same_metadata({'title':'Title'},{'title':'title'}))
        self.assertFalse(Service._same_metadata({'cast':[{'name':'Name'}]},{'cast':[{'name':'name'}]}))

    def test_actual_metadata_mismatch_reports_field_and_caches_observed_for_retry(self):
        def edit(library, item, changes):
            self.plex.rows[0].update(title='After',summary='Not the requested summary')
            return self.plex.item('10')
        self.plex.edit = edit
        with self.assertRaisesRegex(ValueError, r'readback differs \(Description\)'):
            self.service.apply_metadata(self.task['id'], 1, {'title':'After','summary':'Requested'})
        cached = self.store.get('assets', self.asset['id'])
        self.assertEqual(cached['item']['title'], 'After')
        self.assertEqual(self.service.get_task(self.task['id'])['status'], 'blocked')
        self.assertEqual(cached['item']['summary'], 'Not the requested summary')

    def test_cancel_queued_does_not_execute(self):
        task = self.edit();self.service.action(task['id'], 'queue', 2);self.service.action(task['id'], 'cancel', 2)
        self.service._execute(task['id']);self.assertEqual(self.plex.writes, [])

    def test_restart_does_not_replay_external_work(self):
        with self.store.transaction():
            self.task['status']='publishing';self.store.put('tasks',self.task['id'],self.task)
        self.store.close();self.store=Store(self.root/'state')
        task=self.store.get('tasks',self.task['id'])
        self.assertEqual(task['status'],'blocked')
        self.assertIn('Interrupted',task['error'])

    def test_token_never_returned(self):
        self.service.save_config({'plex_url':'http://localhost:32400','plex_token':'private-value'})
        text=json.dumps(self.service.state())
        self.assertNotIn('private-value',text)

    def test_new_library_settings_validate_duplicate_mappings(self):
        with self.assertRaises(ValueError):
            self.service.save_library(self.lib['id'],{'profile':'commercial','mappings':self.lib['mappings']*2})

    def test_review_cannot_skip_processing(self):
        with self.assertRaises(ValueError):self.service.review(self.task['id'],1,'manual')

    def test_publish_original_renamed_old_and_verified_without_archive_config(self):
        from curator.tools import digest
        output=self.root/'result.mkv';output.write_bytes(b'processed-video')
        task=dict(self.task,kind='upscale',status='awaiting_review',output=str(output),validation=[],
                  source_hash=digest(self.file),output_hash=digest(output),comparison_loaded=True)
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        self.service.review(task['id'],1,'manual')
        self.assertEqual(self.file.read_bytes(),b'processed-video')
        self.assertEqual(self.file.with_name(self.file.stem+'-old'+self.file.suffix).read_bytes(),b'original-video')
        self.assertTrue(self.service.get_task(task['id'])['plex_verified'])

    def test_mov_publication_preserves_extension_and_old_original(self):
        from curator.tools import digest
        source = self.file.with_suffix('.MOV');self.file.rename(source)
        asset = {**self.asset, 'local_path':str(source.resolve()),'plex_path':'/plex/film.MOV','fingerprint':fingerprint(source)}
        self.plex.rows[0]['Media'] = [{'Part':[{'file':'/plex/film.MOV'}]}]
        output = self.root/'result.mov';output.write_bytes(b'processed-mov')
        task = dict(self.task,kind='upscale',status='awaiting_review',output=str(output),validation=[],
                    source_hash=digest(source),output_hash=digest(output),comparison_loaded=True)
        with self.store.transaction():
            self.store.put('assets',asset['id'],asset);self.store.put('tasks',task['id'],task)
        self.service.review(task['id'],1,'manual')
        self.assertEqual(source.read_bytes(),b'processed-mov')
        self.assertEqual(source.with_name(source.stem+'-old'+source.suffix).read_bytes(),b'original-video')
        self.assertEqual(self.service.get_task(task['id'])['status'],'applied')

    def quicktime_task(self):
        from curator.tools import digest
        source=self.file.with_suffix('.mov');self.file.rename(source);source.write_bytes(b'processed-hevc')
        output=self.root/'retained.mov';output.write_bytes(b'processed-hevc')
        backup=source.with_name(source.name+'-old');backup.write_bytes(b'original-h264')
        asset={**self.asset,'local_path':str(source.resolve()),'fingerprint':fingerprint(source)}
        task=dict(self.task,status='applied',kind='upscale',published=True,output=str(output),output_hash=digest(output))
        with self.store.transaction():
            self.store.put('assets',asset['id'],asset);self.store.put('tasks',task['id'],task)
        return task,source,backup

    def test_quicktime_repair_retains_processed_copy_and_old_source(self):
        task,source,backup=self.quicktime_task()
        before=dict(width=1920,height=1080,duration_seconds=100,codec='hevc',streams=[{'codec_type':'video','codec_name':'hevc','codec_tag_string':'hev1'}])
        after={**before,'streams':[{'codec_type':'video','codec_name':'hevc','codec_tag_string':'hvc1'}]}
        def remux(argv,**kwargs):
            self.assertEqual(argv[argv.index('-c')+1],'copy')
            Path(argv[-1]).write_bytes(b'fixed-hvc1');return SimpleNamespace(returncode=0)
        with patch('curator.service.tools.probe',side_effect=[before,after]), \
             patch('curator.service.subprocess.run',side_effect=remux):
            result=self.service.action(task['id'],'repair_quicktime',task['version'])
        self.assertEqual(result['status'],'applied')
        self.assertEqual(source.read_bytes(),b'fixed-hvc1')
        self.assertEqual(backup.read_bytes(),b'original-h264')
        self.assertEqual(Path(result['quicktime_repair_previous']['output']).read_bytes(),b'processed-hevc')
        self.assertEqual(result['result']['streams'][0]['codec_tag_string'],'hvc1')

    def test_quicktime_repair_refuses_changed_file_before_remux(self):
        task,source,backup=self.quicktime_task();source.write_bytes(b'external edit')
        with patch('curator.service.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError,'changed'):
                self.service.action(task['id'],'repair_quicktime',task['version'])
        run.assert_not_called()
        self.assertEqual(source.read_bytes(),b'external edit')
        self.assertEqual(backup.read_bytes(),b'original-h264')

    def test_publish_never_overwrites_existing_old_backup(self):
        from curator.tools import digest
        for name in (self.file.stem+'-old'+self.file.suffix, self.file.name+'-old'):
            with self.subTest(backup=name):
                backup=self.file.with_name(name);backup.write_bytes(b'previous original')
                output=self.root/'result.mkv';output.write_bytes(b'processed-video')
                task=dict(self.task,kind='optimize',status='awaiting_review',output=str(output),validation=[],
                          source_hash=digest(self.file),output_hash=digest(output),comparison_loaded=True)
                with self.store.transaction():self.store.put('tasks',task['id'],task)
                with self.assertRaisesRegex(ValueError,'already exists'):self.service.review(task['id'],1,'manual')
                self.assertEqual(backup.read_bytes(),b'previous original')
                self.assertEqual(self.file.read_bytes(),b'original-video')
                self.assertEqual(self.plex.writes,[])
                backup.unlink()

    def test_failed_swap_restores_original_name(self):
        from curator.tools import digest
        output=self.root/'result.mkv';output.write_bytes(b'processed-video')
        task=dict(self.task,kind='optimize',status='awaiting_review',output=str(output),validation=[],
                  source_hash=digest(self.file),output_hash=digest(output),comparison_loaded=True)
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        replace=os.replace
        def fail_stage(source,destination):
            if Path(source).name.startswith('.curator-'):raise OSError('Simulated swap failure')
            return replace(source,destination)
        with patch('curator.service.os.replace',side_effect=fail_stage),self.assertRaises(ValueError):
            self.service.review(task['id'],1,'manual')
        self.assertEqual(self.file.read_bytes(),b'original-video')
        self.assertFalse(self.file.with_name(self.file.stem+'-old'+self.file.suffix).exists())
        self.assertFalse(self.service.get_task(task['id']).get('published'))

    def test_blocked_publish_can_return_retained_output_to_review_without_encoding(self):
        output=self.root/'retained.mkv';output.write_bytes(b'processed')
        task=dict(self.task,kind='optimize',status='blocked',output=str(output),validation=[],
                  source_hash='original-hash',output_hash='processed-hash',comparison_loaded=True,
                  error='Configure an existing archive directory before replacement')
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        result=self.service.action(task['id'],'resume_review',1)
        self.assertEqual(result['status'],'awaiting_review')
        self.assertTrue(result['comparison_loaded'])
        self.assertIsNone(result['error'])
        self.assertEqual(self.file.read_bytes(),b'original-video')
        self.assertEqual(self.plex.writes,[])
        result.update(status='blocked',published=True)
        with self.store.transaction():self.store.put('tasks',task['id'],result)
        with self.assertRaises(ValueError):self.service.action(task['id'],'resume_review',1)

    def test_publish_copy_reports_measured_bytes_and_preserves_source(self):
        target = self.root / 'copy.mkv'
        task = dict(self.task, status='publishing')
        self.service._copy_with_progress(task, self.file, target, 'Archiving original')
        saved = self.service.get_task(task['id'])
        self.assertEqual(saved['progress'], {'phase': 'Archiving original',
            'completed_bytes': self.file.stat().st_size, 'total_bytes': self.file.stat().st_size})
        self.assertEqual(target.read_bytes(), self.file.read_bytes())
        with self.assertRaises(FileExistsError):
            self.service._copy_with_progress(task, self.file, target, 'Staging processed video')

    def test_changed_output_never_replaces_original(self):
        from curator.tools import digest
        output=self.root/'result.mkv';output.write_bytes(b'output')
        task=dict(self.task,kind='upscale',status='awaiting_review',output=str(output),validation=[],
                  source_hash=digest(self.file),output_hash=digest(output),comparison_loaded=True)
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        output.write_bytes(b'changed output')
        with self.assertRaises(ValueError):self.service.review(task['id'],1,'manual')
        self.assertEqual(self.file.read_bytes(),b'original-video')

    def test_reencoding_clears_old_comparison_readiness_and_frames(self):
        task = self.optimization_task()
        task['comparison_loaded'] = True
        folder = self.store.root / 'comparisons' / task['id'] / 'output'
        folder.mkdir(parents=True)
        frame = folder / '0.jpg';frame.write_bytes(b'old-frame')
        with patch('curator.service.tools.digest', side_effect=ValueError('Stop before encoding')):
            with self.assertRaisesRegex(ValueError, 'Stop before encoding'):
                self.service._process(task, self.asset)
        self.assertFalse(self.service.get_task(task['id'])['comparison_loaded'])
        self.assertFalse(frame.exists())

    def test_missing_comparison_does_not_change_review_to_blocked(self):
        task = self.optimization_task()
        with self.store.transaction():
            task.update(status='awaiting_review')
            self.store.put('tasks', task['id'], task)
        with self.assertRaisesRegex(ValueError, 'comparison'):
            self.service.review(task['id'], task['version'], 'manual')
        self.assertEqual(self.service.get_task(task['id'])['status'], 'awaiting_review')

    def test_missing_manual_comparison_blocks_publish(self):
        with self.assertRaisesRegex(ValueError,'comparison'):
            self.service._publish(dict(self.task),self.asset)

    def test_second_instance_cannot_reconcile_active_queue(self):
        with self.assertRaisesRegex(ValueError,'already'):
            Store(self.root/'state')


class Ordering(unittest.TestCase):
    def asset(self,show,season,episode,key):
        return dict(title=f'Episode {episode}',rating_key=key,
                    item=dict(grandparentTitle=show,parentIndex=season,index=episode))

    def test_interleaves_and_surfaces_missing_pair(self):
        from curator.organization import interleave
        assets=[self.asset('Main',1,2,'3'),self.asset('Companion',1,1,'2'),self.asset('Main',1,1,'1')]
        ordered,warnings=interleave(assets,'Main','Companion')
        self.assertEqual([x['rating_key'] for x in ordered],['1','2','3'])
        self.assertEqual(len(warnings),1)

    def test_explicit_season_offset(self):
        from curator.organization import interleave
        assets=[self.asset('Main',2,1,'1'),self.asset('Companion',1,1,'2')]
        ordered,warnings=interleave(assets,'Main','Companion',-1)
        self.assertEqual([x['rating_key'] for x in ordered],['1','2'])
        self.assertEqual(warnings,[])

    def test_ambiguous_episode_blocks(self):
        from curator.organization import interleave
        assets=[self.asset('Main',1,1,'1'),self.asset('Main',1,1,'9'),self.asset('Companion',1,1,'2')]
        with self.assertRaises(ValueError):interleave(assets,'Main','Companion')


class Validation(unittest.TestCase):
    def video(self):
        return dict(width=1920,height=1080,duration_seconds=100,streams=[{'codec_type':'audio','tags':{'language':'eng'}}])

    def test_missing_audio_or_changed_duration_blocks(self):
        original=self.video();output=dict(original,streams=[],duration_seconds=90)
        errors=validate(original,output)
        self.assertTrue(any('Duration' in x for x in errors));self.assertTrue(any('Audio' in x for x in errors))

    def test_anamorphic_portrait_uses_display_ratio_and_still_blocks_low_resolution(self):
        source = dict(self.video(), width=1296, height=2304, streams=[])
        output = dict(self.video(), width=1296, height=1080,
                      streams=[{'codec_type':'video','sample_aspect_ratio':'15:32','display_aspect_ratio':'9:16'}])
        issues = validate(source, output)
        self.assertNotIn('Aspect ratio changed', issues)
        self.assertIn('Output is below 1080-class target', issues)
        fixed = dict(output, width=1080, height=1920,
                     streams=[{'codec_type':'video','sample_aspect_ratio':'1:1','display_aspect_ratio':'9:16'}])
        self.assertEqual(validate(source, fixed), [])

    def test_rotation_metadata_preserves_displayed_orientation(self):
        source = dict(self.video(), streams=[{'codec_type':'video','side_data_list':[{'rotation':-90}]}])
        output = dict(self.video(), width=1080, height=1920,streams=[])
        self.assertEqual(validate(source, output), [])

    def test_hevc_apple_container_requires_quicktime_tag(self):
        source=dict(self.video(),streams=[])
        output=dict(source,container='mov,mp4,m4a,3gp,3g2,mj2',streams=[{'codec_type':'video','codec_name':'hevc','codec_tag_string':'hev1'}])
        self.assertTrue(any('hvc1' in error for error in validate(source,output)))
        output['streams'][0]['codec_tag_string']='hvc1'
        self.assertEqual(validate(source,output),[])
        output['container']='matroska,webm';output['streams'][0]['codec_tag_string']='[0][0][0][0]'
        self.assertEqual(validate(source,output),[])

    def test_same_video_valid(self):self.assertEqual(validate(self.video(),self.video()),[])

    def test_unsupported_processing_kind(self):
        with self.assertRaises(ValueError):command('delete','source','output',{})

    def test_logged_topaz_dynamic_two_times_filter_is_accepted_unchanged(self):
        vf = ('tvai_up=model=prob-4:scale=2:w=0:h=0:preblur=0:noise=0:details=0:halo=0:'
              'blur=0:compression=0:estimate=8:blend=0.2:device=-2:vram=0.86:instances=1')
        with patch('curator.tools.executable', return_value='/installed/topaz/ffmpeg'):
            argv = command('upscale', '/source.mp4', '/output.mp4', {'topaz_filter':vf})
        self.assertEqual(argv[argv.index('-vf') + 1], vf)
        self.assertIn('/output.mp4', argv)
        for invalid in (vf+';movie=/private/file', vf+'[out]', vf+'\nextra', vf+':file=/private/file'):
            with self.assertRaises(ValueError):
                command('upscale', '/source.mp4', '/output.mp4', {'topaz_filter':invalid})

    def test_handbrake_mov_output_uses_native_mov_container(self):
        with tempfile.TemporaryDirectory() as folder:
            preset=Path(folder)/'preset.json';preset.write_text('{}')
            from curator.tools import digest
            settings={'handbrake_preset':'Chosen','handbrake_preset_file':str(preset),'handbrake_preset_hash':digest(preset)}
            with patch('curator.tools.executable',return_value='/installed/HandBrakeCLI'):
                argv=command('optimize','source.MOV','output.mov',settings)
            self.assertEqual(argv[argv.index('--format')+1],'av_mov')

    def test_topaz_worker_environment_uses_installed_bundle_and_preserves_overrides(self):
        from curator.tools import processing_environment
        with tempfile.TemporaryDirectory() as folder:
            bundle=Path(folder)/'Topaz.app'/'Contents'
            models=bundle/'Resources'/'models';models.mkdir(parents=True)
            exe=bundle/'MacOS'/'ffmpeg';exe.parent.mkdir();exe.touch();exe.chmod(0o700)
            with patch.dict(os.environ,{},clear=True):
                env=processing_environment('upscale',{'topaz':str(exe)})
                self.assertEqual(env['TVAI_MODEL_DIR'],str(models))
                self.assertEqual(env['TVAI_MODEL_DATA_DIR'],str(models))
            with patch.dict(os.environ,{'TVAI_MODEL_DIR':str(models),'TVAI_MODEL_DATA_DIR':'custom-cache'},clear=True):
                self.assertEqual(processing_environment('upscale',{'topaz':str(exe)})['TVAI_MODEL_DATA_DIR'],'custom-cache')
        self.assertIsNone(processing_environment('optimize',{}))

    def test_processing_error_explains_model_cache_failure_without_paths(self):
        from curator.tools import processing_failure
        with tempfile.TemporaryDirectory() as folder:
            log=Path(folder)/'tool.log'
            log.write_text('MLModel Error: 0 The model is not found at URL: file:///private/model')
            error=processing_failure(log)
            self.assertIn('Core ML model cache',error)
            self.assertNotIn('/private',error)
            log.write_text('Model not found: prob-4')
            self.assertIn('model was not found',processing_failure(log))
            log.write_text('unknown encoder error')
            self.assertIn('private tool log',processing_failure(log))

    def test_apple_containers_get_hvc1_and_mkv_does_not(self):
        settings={'topaz_filter':'tvai_up=model=prob-4:scale=2:w=0:h=0'}
        with patch('curator.tools.executable',return_value='/installed/ffmpeg'):
            for suffix in ['.mov','.mp4','.m4v']:
                argv=command('upscale','source','output'+suffix,settings)
                self.assertEqual(argv[argv.index('-tag:v')+1],'hvc1')
                self.assertIn('+faststart',argv)
            self.assertNotIn('-tag:v',command('upscale','source','output.mkv',settings))

    def test_topaz_shell_like_filter_rejected(self):
        with self.assertRaises(ValueError):command('upscale','source','output',{'topaz_filter':'tvai_up=x;movie=/secret'})

    def test_preset_parser_handles_nested_customs_and_descriptions(self):
        from curator.tools import parse_handbrake_presets
        rows=parse_handbrake_presets('[12:00:00] startup\nGeneral/\n    Preset A\n        Description line.\nCustom/\n    Nested/\n        Preset A\n            Different settings.\nHandBrake has exited.\n')
        self.assertEqual([x['path'] for x in rows],['General/Preset A','Custom/Nested/Preset A'])
        self.assertEqual(rows[0]['description'],'Description line.')

    def test_changed_preset_snapshot_cannot_execute(self):
        from curator.tools import digest
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'preset.json';path.write_text('{}')
            settings={'handbrake_preset':'Approved','handbrake_preset_file':str(path),'handbrake_preset_hash':digest(path)}
            path.write_text('{"changed": true}')
            with self.assertRaisesRegex(ValueError,'snapshot'):
                command('optimize','source','output.mkv',settings)


class PlexAdapter(unittest.TestCase):
    def test_url_credentials_rejected(self):
        for url in ['ftp://host','http://user:secret@host','http://host/path','http://host?token=secret']:
            with self.assertRaises(PlexError):Plex(url,'token')

    def test_http_error_does_not_leak_credentials(self):
        from urllib.error import HTTPError
        def transport(*args,**kwargs):raise HTTPError('http://secret-url',401,'secret-token',{},None)
        with self.assertRaisesRegex(PlexError,'HTTP 401') as error:Plex('http://host','token',transport).libraries()
        self.assertNotIn('secret',str(error.exception))

    def test_items_pagination_and_episode_type(self):
        calls=[]
        class TestPlex(Plex):
            def request(self,path,method='GET',params=None,**kwargs):
                calls.append(params)
                return {'Metadata':[{'ratingKey':str(params['X-Plex-Container-Start'])}], 'totalSize':2}
        rows=list(TestPlex('http://host','token').items({'key':'1','type':'show'}))
        self.assertEqual(len(rows),2);self.assertEqual(calls[0]['type'],4)


class HTTPBoundary(unittest.TestCase):
    def handler(self,path='/',method='GET',headers=None,body=None):
        session='test-session'
        request=f'{method} {path} HTTP/1.1\r\nHost: localhost:8790\r\n'
        for k,v in (headers or {}).items():request+=k+': '+v+'\r\n'
        if body is not None:request+='Content-Length: '+str(len(body))+'\r\n'
        request+='Connection: close\r\n\r\n'+(body or '')
        class Connection:
            def __init__(self):self.output=bytearray()
            def makefile(self,*args):return io.BytesIO(request.encode())
            def sendall(self,data):self.output.extend(data)
        connection=Connection()
        server=SimpleNamespace(server_port=8790,session=session,service=SimpleNamespace(state=lambda:{'ok':True}))
        Handler(connection,('127.0.0.1',1),server)
        return bytes(connection.output)

    def test_html_sets_private_cookie(self):
        output=self.handler()
        self.assertIn(b'200 OK',output);self.assertIn(b'HttpOnly; SameSite=Strict',output)

    def test_api_requires_cookie(self):self.assertIn(b'403 Forbidden',self.handler('/api/state'))

    def test_api_same_session(self):
        self.assertIn(b'200 OK',self.handler('/api/state',headers={'Cookie':'curator_session=test-session'}))

    def test_cross_origin_post_rejected(self):
        headers={'Cookie':'curator_session=test-session','X-Curator-Request':'1','Origin':'https://evil.example'}
        self.assertIn(b'403 Forbidden',self.handler('/api/config','POST',headers,'{}'))

    def test_form_post_rejected(self):
        self.assertIn(b'403 Forbidden',self.handler('/api/config','POST',{'Cookie':'curator_session=test-session'},'{}'))


if __name__=='__main__':unittest.main()
