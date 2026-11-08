"""File workflows use disposable media and a fake Plex, never a private library."""
import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from curator import multipart, tools
from curator.file_workflows import identity
from curator.plex import Plex, PlexError
from curator.service import Service
from curator.store import Store


class FixturePlex:
    def __init__(self, folder):
        self.folder=folder;self.rows={};self.trash=False;self.follow=True;self.change_metadata=False;self.groups={};self.scans=[]
        for i in range(1,4):
            name=f'Trip - Part {i}.mkv'
            self.rows[str(i)]=dict(ratingKey=str(i),guid='local://'+str(i),type='movie',title=f'Trip part {i}',summary='Description',studio='Studio',tagline='Tagline',
                viewCount=i,viewOffset=123,Genre=[{'tag':'Travel'}],Label=[{'tag':'Custom'}],Collection=[],Role=[{'tag':'Person','role':'Self'}],
                Media=[{'Part':[{'file':'/plex/'+name,'id':str(i)}]}])
            (folder/name).write_bytes(f'part {i}'.encode())
    def item(self,key):return copy.deepcopy(self.rows[str(key)])
    def automatic_trash(self):
        if self.trash:raise ValueError('Disable automatic trash')
        return False
    def scan_folder(self,library,folder):
        self.scans.append(folder)
        if not self.follow:return
        for row in self.rows.values():
            path=row['Media'][0]['Part'][0]['file']
            if row['ratingKey']=='1' and (self.folder/'Better.mkv').exists():
                row['Media'][0]['Part'][0]['file']='/plex/Better.mkv'
                if self.change_metadata:row['summary']='Unexpected change'
        if (self.folder/'Joined.mkv').exists() and '99' not in self.rows:
            self.rows['99']=dict(ratingKey='99',type='movie',title='Joined',Media=[{'Part':[{'file':'/plex/Joined.mkv','id':'99'}]}])
    def items(self,library):return iter(copy.deepcopy(list(self.rows.values())))
    def edit(self,library,item,changes):
        row=self.rows[str(item['ratingKey'])]
        for k,v in changes.items():
            if k in {'genre','label','collection'}:row[k.title()]=[{'tag':x} for x in v]
            elif k=='cast':row['Role']=[{'tag':x['name'],'role':x.get('role',''),'thumb':x.get('thumb','')} for x in v]
            else:row[k]=v
        return copy.deepcopy(row)
    def group_state(self,library,kind,title,owned=None):
        actual=self.groups.get((kind,title))
        if actual and actual!=owned:raise ValueError('Unmanaged grouping')
        return actual
    def managed_group(self,library,kind,title,keys,owned,receipt):
        self.group_state(library,kind,title,owned)
        value=dict(kind=kind,key=kind+'1',keys=keys)
        self.groups[kind,title]=value;receipt(value);return value


def media(width=1920,height=1080,duration=2,codec='h264'):
    return dict(width=width,height=height,duration_seconds=duration,size_bytes=100,codec=codec,pix_fmt='yuv420p',color_transfer=None,
                streams=[dict(codec_type='video',codec_name=codec,width=width,height=height,pix_fmt='yuv420p',time_base='1/1000',r_frame_rate='30/1',extradata_hash='same')],chapters=[])


class Plans(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.folder=self.root/'media';self.folder.mkdir()
        self.plex=FixturePlex(self.folder);self.store=Store(self.root/'state');self.service=Service(self.store,lambda *a:self.plex)
        self.library=dict(id='server:1',server='server',key='1',title='Movies',type='movie',profile='home',mappings=[dict(plex_root='/plex',local_root=str(self.folder))])
        self.assets=[]
        with self.store.transaction():
            self.store.put('libraries',self.library['id'],self.library)
            for key,item in self.plex.rows.items():
                path=item['Media'][0]['Part'][0]['file'];local=self.folder/Path(path).name
                asset=dict(id=key*24,library=self.library['id'],rating_key=key,plex_path=path,local_path=str(local),title=item['title'],item=item,present=True,fingerprint=tools.fingerprint(local),technical=media())
                self.assets.append(asset);self.store.put('assets',asset['id'],asset)
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def plan(self,kind='rename',**kwargs):
        data=dict(kind=kind,assets=[self.assets[0]['id']] if kind=='rename' else [a['id'] for a in self.assets[:2]],filename='Better.mkv' if kind=='rename' else 'Joined.mkv',title='Trip')
        data.update(kwargs)
        with patch('curator.file_workflows.tools.probe',return_value=media()):return self.service.file_plan(data)
    def run_task(self,task):
        self.service.action(task['id'],'queue',task['version']);self.service._execute(task['id']);return self.service.get_task(task['id'])
    def test_rename_moves_sidecars_backups_preserves_identity_and_task_ids(self):
        source=Path(self.assets[0]['local_path'])
        for tail in ('.en.srt','-old.mkv','.mkv-old','-trailer.mp4'):
            (source.parent/(source.stem+tail)).write_bytes(b'extra')
        prior=dict(id='prior',asset=self.assets[0]['id'],library=self.library['id'],kind='metadata',status='applied',version=1,archive=str(source.with_name(source.stem+'-old.mkv')))
        with self.store.transaction():self.store.put('tasks','prior',prior)
        task=self.plan();self.assertEqual(len(task['plan']['moves']),5)
        before=identity(self.plex.item('1'));result=self.run_task(task)
        self.assertEqual(result['status'],'applied');self.assertFalse(source.exists())
        self.assertTrue((self.folder/'Better.mkv').exists());self.assertTrue((self.folder/'Better.en.srt').exists())
        self.assertTrue((self.folder/'Better-old.mkv').exists());self.assertTrue((self.folder/'Better.mkv-old').exists())
        self.assertTrue((self.folder/'Better-trailer.mp4').exists())
        self.assertEqual(identity(self.plex.item('1')),before)
        self.assertEqual(self.store.get('assets',self.assets[0]['id'])['plex_path'],'/plex/Better.mkv')
        self.assertEqual(self.service.get_task('prior')['status'],'applied');self.assertEqual(self.service.get_task('prior')['version'],2)
    def test_rename_identity_failure_restores_files(self):
        task=self.plan();self.plex.follow=False
        with patch('curator.file_workflows.time.sleep'):
            result=self.run_task(task)
        self.assertEqual(result['status'],'blocked');self.assertTrue(result['rename_restored'])
        self.assertTrue(Path(self.assets[0]['local_path']).exists());self.assertFalse((self.folder/'Better.mkv').exists())
    def test_rename_metadata_change_restores_files(self):
        task=self.plan();self.plex.change_metadata=True
        result=self.run_task(task);self.assertEqual(result['status'],'blocked');self.assertTrue(result['rename_restored'])
    def test_rename_missing_mount_and_collision_and_traversal(self):
        for name in ('../bad.mkv','Other.mp4','.hidden.mkv'):
            with self.subTest(name=name),self.assertRaises(ValueError):self.plan(filename=name)
        (self.folder/'Better.mkv').write_bytes(b'collision')
        with self.assertRaisesRegex(ValueError,'already exists'):self.plan()
    def test_automatic_trash_blocks_before_mutation(self):
        self.plex.trash=True
        with self.assertRaises(ValueError):self.plan()
        self.assertTrue(Path(self.assets[0]['local_path']).exists())
    def test_recover_interrupted_rename_preserves_original_data(self):
        task=self.plan();move=task['plan']['moves'][0]
        old,new=Path(move['source']),Path(move['destination'])
        os.link(old,new);old.unlink()
        task.update(status='blocked',rename_started=True,rename_moved=[move],rename_before=self.plex.item('1'),rename_art_hashes={})
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        result=self.service.action(task['id'],'restore_rename',1)
        self.assertEqual(result['status'],'resolved');self.assertTrue(old.exists());self.assertFalse(new.exists())

    def test_group_update_does_not_duplicate_on_repeat(self):
        first=self.plan(kind='group');self.run_task(first)
        repeated=self.plan(kind='group');self.assertEqual(self.run_task(repeated)['status'],'applied')
        self.assertEqual(len(self.plex.groups),2)

    def test_scan_skips_reserved_file_and_continues_other_files(self):
        task=self.plan();self.service.action(task['id'],'queue',1)
        before=self.store.get('assets',self.assets[0]['id'])
        with patch('curator.service.threading.Thread') as thread:self.service.scan(self.library['id'])
        thread.return_value.start.assert_called_once()
        with patch('curator.service.tools.probe',return_value=media()) as probe:self.service._scan(self.library)
        self.assertEqual(probe.call_count,2)
        self.assertEqual(self.store.get('assets',self.assets[0]['id']),before)
        self.assertEqual(self.service.scan_status[self.library['id']]['skipped_reserved'],1)

    def test_join_blocks_external_subtitles_instead_of_dropping_them(self):
        Path(self.assets[0]['local_path']).with_suffix('.en.srt').write_text('Subtitle')
        with self.assertRaisesRegex(ValueError,'external subtitles'):self.plan(kind='join')

    def test_missing_source_and_symlink_sidecar_refuse_before_mutation(self):
        source=Path(self.assets[0]['local_path']);side=source.with_suffix('.en.srt');side.symlink_to(source)
        with self.assertRaisesRegex(ValueError,'regular files'):self.plan()
        side.unlink();source.unlink()
        with self.assertRaises(ValueError):self.plan()

    def test_source_or_sidecar_change_invalidates_preview(self):
        task=self.plan();Path(self.assets[0]['local_path']).write_bytes(b'changed')
        with self.assertRaises(ValueError):self.service.action(task['id'],'queue',1)
    def test_active_source_conflict_and_scan_proposal_preservation(self):
        task=self.plan();self.service.action(task['id'],'queue',1)
        with self.assertRaisesRegex(ValueError,'Another'):self.plan(kind='join')
        with self.store.transaction():self.service.reconcile_findings(self.assets[0],[])
        self.assertEqual(self.service.get_task(task['id'])['status'],'queued')
    def test_join_plan_requires_matching_streams_or_explicit_normalization(self):
        with patch('curator.file_workflows.tools.probe',side_effect=[media(),media(1280,720)]):
            with self.assertRaisesRegex(ValueError,'Normalize'):
                self.service.file_plan(dict(kind='join',assets=[a['id'] for a in self.assets[:2]],filename='Joined.mkv',title='Trip'))
        task=self.plan(kind='join',mode='normalize');self.assertEqual(task['plan']['canvas']['width'],1920)
        self.assertEqual([x['start'] for x in task['plan']['chapters']],[0,2])
    def test_group_creation_update_and_idempotence(self):
        task=self.plan(kind='group');self.assertEqual(self.run_task(task)['status'],'applied')
        self.assertEqual(len(self.plex.groups),2)
        task=self.plan(kind='group',assets=[a['id'] for a in reversed(self.assets)])
        self.assertEqual(self.run_task(task)['status'],'applied')
        self.assertEqual(self.plex.groups['playlist','Trip']['keys'],['3','2','1']);self.assertEqual(len(self.plex.groups),2)
    def test_group_refuses_unmanaged_title(self):
        self.plex.groups['playlist','Trip']={'key':'external','keys':['1']}
        with self.assertRaisesRegex(ValueError,'Unmanaged'):self.plan(kind='group')
    def test_no_edit_bypass_for_complex_plan(self):
        task=self.plan()
        with self.assertRaisesRegex(ValueError,'new file operation'):self.service.edit_task(task['id'],{'title':'Bypass'},1)
    def test_publish_join_preserves_all_parts_and_copies_metadata(self):
        task=self.plan(kind='join');output=self.root/'joined.mkv';output.write_bytes(b'joined')
        task.update(status='awaiting_review',source_hashes=[tools.digest(a['local_path']) for a in self.assets[:2]],output=str(output),output_hash=tools.digest(output),result=media(duration=4),validation=[],comparison_loaded=True)
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        result=self.service.review(task['id'],1,'manual')
        self.assertEqual(result['status'],'applied');self.assertEqual((self.folder/'Joined.mkv').read_bytes(),b'joined')
        self.assertTrue(all(Path(a['local_path']).exists() for a in self.assets))
        self.assertEqual(self.plex.item('99')['summary'],'Description');self.assertNotIn('viewCount',self.plex.item('99'))
    def test_join_publication_records_phase_and_filesystem_error(self):
        import errno
        task=self.plan(kind='join');output=self.root/'joined.mkv';output.write_bytes(b'joined')
        task.update(status='awaiting_review',source_hashes=[tools.digest(a['local_path']) for a in self.assets[:2]],output=str(output),output_hash=tools.digest(output),result=media(duration=4),validation=[],comparison_loaded=True)
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        with patch('curator.file_workflows.install_exclusive',side_effect=OSError(errno.EACCES,'Permission denied')):
            with self.assertRaisesRegex(ValueError,'Installing verified joined file'):
                self.service.review(task['id'],1,'manual')
        result=self.service.get_task(task['id'])
        self.assertEqual(result['status'],'blocked');self.assertEqual(result['publication_error']['errno'],errno.EACCES)
        log=self.service.publication_log(task['id'])['entries']
        self.assertTrue(any(e.get('phase')=='Verifying staged joined video' for e in log))
        self.assertEqual(log[-1]['action'],'publication failed');self.assertEqual(log[-1]['errno'],errno.EACCES)
        self.assertTrue(output.exists());self.assertTrue(all(Path(a['local_path']).exists() for a in self.assets))
        self.assertFalse((self.folder/'Joined.mkv').exists())
        self.service.action(task['id'],'resume_join',1)
        self.assertEqual(self.service.publication_log(task['id'])['entries'][-1]['action'],'publication failed')

    def test_join_metadata_ignores_playback_state_and_supports_old_plans(self):
        task=self.plan(kind='join');item=self.plex.item('1')
        item.update(viewCount=99,viewOffset=99999,lastViewedAt=12345,Field=[{'name':'summary','locked':True}])
        self.service.check_join_metadata(task['plan'],item)
        legacy=dict(task['plan']);legacy.pop('metadata_snapshot')
        self.service.check_join_metadata(legacy,item)
        item['summary']='New description'
        with self.assertRaisesRegex(ValueError,'summary'):self.service.check_join_metadata(task['plan'],item)

    def test_join_metadata_change_blocks_before_expensive_source_hashes(self):
        task=self.plan(kind='join');task.update(status='awaiting_review',comparison_loaded=True)
        self.plex.rows['1']['summary']='Changed description'
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        with patch.object(self.service,'publication_digest') as digest:
            with self.assertRaisesRegex(ValueError,'Refresh metadata preview'):self.service.review(task['id'],1,'manual')
        digest.assert_not_called()

    def test_metadata_refresh_retains_output_and_comparison_then_publishes(self):
        task=self.plan(kind='join');output=self.root/'joined.mkv';output.write_bytes(b'joined')
        task.update(status='blocked',source_hashes=[tools.digest(a['local_path']) for a in self.assets[:2]],output=str(output),output_hash=tools.digest(output),result=media(duration=4),validation=[],comparison_loaded=True,error='Metadata changed')
        self.plex.rows['1']['summary']='Updated description'
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        with patch.object(self.service,'_run_file_tool') as encode:
            result=self.service.action(task['id'],'refresh_join_metadata',1)
            self.assertEqual(result['status'],'awaiting_review');self.assertEqual(result['version'],2)
            self.assertTrue(result['comparison_loaded']);self.assertEqual(result['output_hash'],tools.digest(output))
            self.assertEqual(result['plan']['metadata_snapshot']['metadata']['summary'],'Updated description')
            self.assertEqual(self.service.review(task['id'],2,'manual')['status'],'applied')
        encode.assert_not_called();self.assertEqual(self.plex.rows['99']['summary'],'Updated description')

    def test_artwork_url_churn_is_accepted_only_when_image_bytes_match(self):
        task=self.plan(kind='join');item=self.plex.item('1');item['thumb']='/library/metadata/1/thumb/100'
        with patch.object(self.plex,'image',return_value=b'approved-image',create=True):
            task['plan']['metadata_snapshot']=self.service.join_metadata_snapshot(item,client=self.plex)
            item['thumb']='/library/metadata/1/thumb/200'
            self.service.check_join_metadata(task['plan'],item,self.plex)
        with patch.object(self.plex,'image',return_value=b'different-image',create=True):
            with self.assertRaisesRegex(ValueError,'artwork image content'):
                self.service.check_join_metadata(task['plan'],item,self.plex)

    def test_rename_ignores_internal_cast_ids_but_preserves_semantic_fields(self):
        before=self.plex.item('1');after=copy.deepcopy(before)
        after['Role'][0]['id']=999;after['Field']=[{'name':'summary','locked':True}]
        self.assertTrue(self.service.same_rename_identity(before,after))
        after['Role'][0]['role']='Changed role'
        self.assertFalse(self.service.same_rename_identity(before,after))

    @unittest.skipUnless(__import__('sys').platform=='darwin','Native macOS exclusive-rename check')
    def test_native_rename_does_not_require_share_hard_links(self):
        import errno
        task=self.plan()
        with patch('curator.file_workflows.os.link',side_effect=OSError(errno.ENOTSUP,'No hard links')):
            result=self.run_task(task)
        self.assertEqual(result['status'],'applied',result.get('error'))
        self.assertTrue((self.folder/'Better.mkv').exists())

    def test_rename_records_exact_filesystem_failure_and_retains_original(self):
        import errno
        task=self.plan()
        with patch('curator.file_workflows.install_exclusive',side_effect=PermissionError(errno.EACCES,'Denied')):
            result=self.run_task(task)
        self.assertEqual(result['status'],'blocked');self.assertEqual(result['rename_error']['errno'],errno.EACCES)
        self.assertTrue(result['rename_restored']);self.assertTrue(Path(self.assets[0]['local_path']).exists())
        self.assertEqual(self.service.publication_log(task['id'])['entries'][-1]['error_type'],'PermissionError')

    def test_join_falls_back_when_share_rejects_exclusive_rename(self):
        import errno
        task=self.plan(kind='join');output=self.root/'joined.mkv';output.write_bytes(b'joined')
        task.update(status='awaiting_review',source_hashes=[tools.digest(a['local_path']) for a in self.assets[:2]],output=str(output),output_hash=tools.digest(output),result=media(duration=4),validation=[],comparison_loaded=True)
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        with patch('curator.file_workflows.install_exclusive',side_effect=OSError(errno.ENOTSUP,'Unsupported operation')):
            result=self.service.review(task['id'],1,'manual')
        self.assertEqual(result['status'],'applied');self.assertEqual(output.read_bytes(),b'joined')
        self.assertEqual((self.folder/'Joined.mkv').read_bytes(),b'joined')
        self.assertTrue(all(Path(a['local_path']).exists() for a in self.assets))
        self.assertTrue(self.service.copy_install_required(self.folder/'another.mkv'))

    def test_rename_uses_verified_copy_when_exclusive_rename_is_unsupported(self):
        import errno
        task=self.plan()
        with patch('curator.file_workflows.install_exclusive',side_effect=OSError(errno.ENOTSUP,'Unsupported operation')):
            result=self.run_task(task)
        self.assertEqual(result['status'],'applied',result.get('error'))
        self.assertEqual((self.folder/'Better.mkv').read_bytes(),b'part 1')
        self.assertFalse(Path(self.assets[0]['local_path']).exists())

    def test_copy_based_rename_rolls_back_on_plex_mismatch(self):
        import errno
        task=self.plan();self.plex.follow=False
        with patch('curator.file_workflows.install_exclusive',side_effect=OSError(errno.ENOTSUP,'Unsupported operation')),patch('curator.file_workflows.time.sleep'):
            result=self.run_task(task)
        self.assertEqual(result['status'],'blocked');self.assertTrue(result['rename_restored'])
        self.assertEqual(Path(self.assets[0]['local_path']).read_bytes(),b'part 1')
        self.assertFalse((self.folder/'Better.mkv').exists())
        self.plan(filename='Another.mkv')  # Restored cache has the copy's current fingerprint.

    def test_verified_copy_refuses_existing_destination_without_deleting_it(self):
        task=self.plan();destination=self.folder/'collision.mkv';destination.write_bytes(b'user file')
        with self.assertRaises(FileExistsError):
            self.service.move_with_fallback(task,Path(self.assets[0]['local_path']),destination,'Copy',force_copy=True)
        self.assertEqual(destination.read_bytes(),b'user file');self.assertTrue(Path(self.assets[0]['local_path']).exists())

    def test_interrupted_copy_removes_only_its_partial_destination(self):
        task=self.plan();source=Path(self.assets[0]['local_path']);destination=self.folder/'partial.mkv'
        def broken(task,source,destination,phase,created=None):
            with destination.open('xb') as stream:
                stream.write(b'partial');stat=os.fstat(stream.fileno());created(dict(device=stat.st_dev,inode=stat.st_ino))
                raise OSError('Simulated write failure')
        with patch.object(self.service,'_copy_with_progress',side_effect=broken):
            with self.assertRaises(OSError):self.service.move_with_fallback(task,source,destination,'Copy',force_copy=True)
        self.assertFalse(destination.exists());self.assertEqual(source.read_bytes(),b'part 1')

    def test_receipt_failure_after_copy_move_never_deletes_only_remaining_copy(self):
        task=self.plan();source=Path(self.assets[0]['local_path']);destination=self.folder/'moved.mkv';save=self.service._save
        def fail_receipt(task,**values):
            if 'file_move_pending' in values and values['file_move_pending'] is None:raise RuntimeError('Receipt failed')
            return save(task,**values)
        with patch.object(self.service,'_save',side_effect=fail_receipt):
            with self.assertRaises(RuntimeError):self.service.move_with_fallback(task,source,destination,'Move',force_copy=True)
        self.assertFalse(source.exists());self.assertEqual(destination.read_bytes(),b'part 1')

    def test_previous_errno45_installs_directly_from_retained_output(self):
        import errno
        task=self.plan(kind='join');output=self.root/'joined.mkv';output.write_bytes(b'joined')
        task.update(status='awaiting_review',source_hashes=[tools.digest(a['local_path']) for a in self.assets[:2]],output=str(output),output_hash=tools.digest(output),result=media(duration=4),validation=[],comparison_loaded=True,
                    publication_error={'errno':errno.ENOTSUP,'phase':'Installing verified joined file'})
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        with patch('curator.file_workflows.install_exclusive') as native:
            self.assertEqual(self.service.review(task['id'],1,'manual')['status'],'applied')
        native.assert_not_called();self.assertTrue(output.exists())
        self.assertFalse(any(self.folder.glob('.curator-*')))

    def test_copy_fallback_does_not_broaden_file_mode(self):
        task=self.plan();source=Path(self.assets[0]['local_path']);source.chmod(0o600);destination=self.folder/'private.mkv'
        self.service.move_with_fallback(task,source,destination,'Copy',force_copy=True,remove_source=False)
        self.assertEqual(destination.stat().st_mode&0o777,0o600);self.assertTrue(source.exists())

    def test_join_waits_until_plex_reports_complete_copied_file(self):
        import errno
        task=self.plan(kind='join');output=self.root/'joined.mkv';output.write_bytes(b'joined')
        task.update(status='awaiting_review',source_hashes=[tools.digest(a['local_path']) for a in self.assets[:2]],output=str(output),output_hash=tools.digest(output),result=media(duration=4),validation=[],comparison_loaded=True,
                    publication_error={'errno':errno.ENOTSUP,'phase':'Installing verified joined file'})
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        native=self.plex.items;reads=[]
        def indexing(library):
            rows=list(native(library));reads.append(1)
            for row in rows:
                if row['ratingKey']=='99':row['Media'][0]['Part'][0]['size']=1 if len(reads)==1 else 100
            return iter(rows)
        with patch.object(self.plex,'items',side_effect=indexing),patch('curator.file_workflows.time.sleep'):
            self.assertEqual(self.service.review(task['id'],1,'manual')['status'],'applied')
        self.assertEqual(len(reads),2)

    def test_join_cannot_succeed_if_artwork_step_erases_cast(self):
        self.plex.rows['1']['thumb']='/library/metadata/1/thumb/test'
        with patch.object(self.plex,'image',return_value=b'approved-image',create=True):
            task=self.plan(kind='join');output=self.root/'joined.mkv';output.write_bytes(b'joined')
            task.update(status='awaiting_review',source_hashes=[tools.digest(a['local_path']) for a in self.assets[:2]],output=str(output),output_hash=tools.digest(output),result=media(duration=4),validation=[],comparison_loaded=True)
            with self.store.transaction():self.store.put('tasks',task['id'],task)
            def upload(*args,**kwargs):self.plex.rows['99']['Role']=[]
            with patch.object(self.plex,'artwork',side_effect=upload,create=True):
                with self.assertRaisesRegex(ValueError,'did not persist.*cast'):
                    self.service.review(task['id'],1,'manual')
        result=self.service.get_task(task['id'])
        self.assertEqual(result['status'],'blocked');self.assertTrue(result['published']);self.assertFalse(result['plex_verified'])
        self.assertEqual(result['metadata_copy_differing'],['cast']);self.assertTrue(output.exists())

    def test_join_final_check_detects_delayed_metadata_reset(self):
        task=self.plan(kind='join');output=self.root/'joined.mkv';output.write_bytes(b'joined')
        task.update(status='awaiting_review',source_hashes=[tools.digest(a['local_path']) for a in self.assets[:2]],output=str(output),output_hash=tools.digest(output),result=media(duration=4),validation=[],comparison_loaded=True)
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        original=self.plex.item;reads=[]
        def read(key):
            if str(key)=='99':
                reads.append(1)
                if len(reads)==2:self.plex.rows['99']['summary']=''
            return original(key)
        with patch.object(self.plex,'item',side_effect=read),patch('curator.file_workflows.time.sleep'):
            with self.assertRaisesRegex(ValueError,'did not persist.*summary'):
                self.service.review(task['id'],1,'manual')
        result=self.service.get_task(task['id'])
        self.assertEqual(result['metadata_copy_checks'],2);self.assertEqual(result['status'],'blocked')

    def test_publish_join_requires_comparison(self):
        task=self.plan(kind='join');task.update(status='awaiting_review')
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        with self.assertRaisesRegex(ValueError,'comparison'):self.service.review(task['id'],1,'manual')
    def test_verified_rename_scan_reuses_asset_id(self):
        task=self.plan();self.assertEqual(self.run_task(task)['status'],'applied')
        self.service.scan_status[self.library['id']]={'running':True,'count':0}
        with patch('curator.service.tools.probe',return_value=media()):self.service._scan(self.library)
        matching=[a for a in self.store.all('assets') if a['plex_path']=='/plex/Better.mkv']
        self.assertEqual(len(matching),1);self.assertEqual(matching[0]['id'],self.assets[0]['id'])


class MultipartHelpers(unittest.TestCase):
    def test_numeric_order_missing_duplicate_and_folder_scoping(self):
        assets=[dict(id=str(i),library='l',title='Trip',plex_path='/a/Trip - Part '+str(i)+'.mkv') for i in (10,2,1)]
        other=dict(assets[0],id='other',plex_path='/b/Trip - Part 3.mkv');assets.append(other)
        result=multipart.suggestions(assets,assets[0]);self.assertEqual(result['assets'],['1','2','10']);self.assertTrue(result['warnings'])
    def test_chapters_preserve_internal_boundaries(self):
        m=media();m['chapters']=[dict(start_time='1',end_time='2',tags={'title':'Internal'})]
        rows=multipart.chapters([m,media()],['One','Two']);self.assertEqual([r['start'] for r in rows],[0,1,2]);self.assertEqual(rows[0]['end'],1)
    def test_compatibility_checks_audio_and_extradata(self):
        a=media();b=copy.deepcopy(a);self.assertTrue(multipart.compatibility([a,b]));b['streams'][0]['extradata_hash']='different';self.assertFalse(multipart.compatibility([a,b]))
    def test_timecode_is_omitted_but_unknown_data_is_blocked(self):
        m=media();m['streams'].append({'index':2,'codec_type':'data','codec_tag_string':'tmcd'})
        self.assertEqual(multipart.stream_maps(m),['-map','0:0'])
        m['streams'][-1]['codec_tag_string']='gpmd'
        with self.assertRaisesRegex(ValueError,'ancillary'):multipart.playback_streams(m)

    def test_exclusive_install_does_not_overwrite_destination(self):
        from curator.file_workflows import install_exclusive
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'stage';destination=Path(folder)/'destination'
            source.write_bytes(b'joined');install_exclusive(source,destination)
            self.assertFalse(source.exists());self.assertEqual(destination.read_bytes(),b'joined')
            source.write_bytes(b'other')
            with self.assertRaises(OSError):install_exclusive(source,destination)
            self.assertEqual(source.read_bytes(),b'other');self.assertEqual(destination.read_bytes(),b'joined')

    def test_normalization_refuses_hdr_and_missing_tracks(self):
        a=media();b=media();b['pix_fmt']='yuv420p10le'
        with self.assertRaisesRegex(ValueError,'10-bit'):multipart.normalization([a,b])
        b=media();b['streams'].append({'codec_type':'audio'})
        with self.assertRaisesRegex(ValueError,'same track'):multipart.normalization([a,b])


class PlexGuards(unittest.TestCase):
    def test_preferences_and_targeted_scan_requests(self):
        plex=Plex('http://localhost:32400','test');calls=[]
        def request(path,*args,**kwargs):
            calls.append((path,args,kwargs));return {'Setting':[{'id':'autoEmptyTrash','value':'0'}]}
        plex.request=request;self.assertFalse(plex.automatic_trash());plex.scan_folder({'key':'1'},'/plex')
        self.assertEqual(calls[-1][0],'/library/sections/1/refresh');self.assertEqual(calls[-1][2]['params'],{'path':'/plex'})
        plex.request=lambda *a,**kw:{'Setting':[{'id':'autoEmptyTrash','value':'1'}]}
        with self.assertRaises(PlexError):plex.automatic_trash()
    def test_group_ownership_collision_and_remote_drift(self):
        plex=Plex('http://localhost:32400','test')
        plex.request=lambda path,**kw: {'Metadata':[{'title':'Trip','ratingKey':'8','smart':False}]} if path=='/playlists' else {'Metadata':[{'ratingKey':'2'}]}
        with self.assertRaisesRegex(PlexError,'unmanaged'):plex.group_state({'key':'1'},'playlist','Trip')
        with self.assertRaisesRegex(PlexError,'outside'):plex.group_state({'key':'1'},'playlist','Trip',{'key':'8','keys':['1']})
    def test_managed_playlist_reorder_uses_playlist_item_ids_and_verifies(self):
        plex=Plex('http://localhost:32400','test');members=['1','2'];calls=[]
        def request(path,method='GET',params=None,**kwargs):
            calls.append((path,method,params))
            if path=='/playlists':return {'Metadata':[{'title':'Trip','ratingKey':'8','smart':False}]}
            if path=='/playlists/8/items' and method=='GET':return {'Metadata':[{'ratingKey':k,'playlistItemID':'p'+k} for k in members]}
            if method=='DELETE':members.remove(path.rsplit('/',1)[-1][1:]);return {}
            if method=='PUT':members[:]=params['uri'].rsplit('/',1)[-1].split(',');return {}
            raise AssertionError(path)
        plex.request=request;receipts=[]
        result=plex.managed_group({'server':'s','key':'1'},'playlist','Trip',['2','1'],{'key':'8','keys':['1','2']},receipts.append)
        self.assertEqual(members,['2','1']);self.assertEqual(result['keys'],['2','1'])
        self.assertTrue(any(path=='/playlists/8/items/p1' for path,_,_ in calls));self.assertEqual(len(receipts),1)

    def test_managed_collection_creation_receipt_and_membership_verification(self):
        plex=Plex('http://localhost:32400','test');created=[]
        def request(path,method='GET',params=None,**kwargs):
            if path=='/library/sections/1/collections':return {'Metadata':created}
            if path=='/library/collections' and method=='POST':
                self.assertEqual(params['sectionId'],'1');self.assertEqual(params['type'],1)
                created.append({'ratingKey':'9','title':'Trip','smart':0});return {'Metadata':created}
            if path=='/library/metadata/9/children':return {'Metadata':[{'ratingKey':'2'},{'ratingKey':'1'}]}
            raise AssertionError(path)
        plex.request=request;receipts=[]
        result=plex.managed_group({'server':'s','key':'1'},'collection','Trip',['1','2'],None,receipts.append)
        self.assertEqual(result['key'],'9');self.assertTrue(receipts[0]['uncertain']);self.assertNotIn('uncertain',receipts[-1])



if __name__=='__main__':unittest.main()

@unittest.skipUnless(os.environ.get('CURATOR_FFMPEG_TESTS')=='1','Set CURATOR_FFMPEG_TESTS=1 for local FFmpeg integration checks')
class RealFFmpeg(unittest.TestCase):
    def setUp(self):
        self.fixture=Plans();self.fixture.setUp();self.service=self.fixture.service
        self.exe=tools.executable({},'ffmpeg')
    def tearDown(self):self.fixture.tearDown()
    def generate(self,mixed=False,timecode=False):
        for index,asset in enumerate(self.fixture.assets[:2]):
            size='180x320' if mixed and index else '320x180'
            if timecode:
                prior=Path(asset['local_path']);source=prior.with_suffix('.mov');prior.unlink()
                asset.update(local_path=str(source),plex_path='/plex/'+source.name)
                self.fixture.plex.rows[asset['rating_key']]['Media'][0]['Part'][0]['file']=asset['plex_path']
                asset['item']=self.fixture.plex.item(asset['rating_key'])
            result=subprocess.run([self.exe,'-nostdin','-y','-f','lavfi','-i',f'color=c={"red" if index else "blue"}:s={size}:r=30',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','1','-c:v','mpeg4','-q:v','2','-pix_fmt','yuv420p',
                '-c:a','pcm_s24le' if timecode else 'aac','-ac','2',*(['-timecode','01:00:00:00'] if timecode else []),asset['local_path']],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr[-2000:].decode(errors='replace'))
            asset.update(fingerprint=tools.fingerprint(asset['local_path']),technical=tools.probe(asset['local_path'],{}))
            with self.fixture.store.transaction():self.fixture.store.put('assets',asset['id'],asset)
    def join(self,mode):
        task=self.service.file_plan(dict(kind='join',assets=[a['id'] for a in self.fixture.assets[:2]],filename='Joined.mkv',title='Trip joined',mode=mode,
                                        chapter_titles=['First','Second']))
        task=self.fixture.run_task(task)
        self.assertEqual(task['status'],'awaiting_review',task.get('error'))
        self.assertEqual(len(task['result']['chapters']),2)
        result=self.service.join_comparison(task['id']);self.assertEqual(len(result['samples']),4)
        self.assertTrue(self.service.join_sample(task['id'],result['samples'][0]['files'][0]).startswith(b'\xff\xd8'))
        return self.service.get_task(task['id'])
    def test_stream_copy_join_chapters_boundaries_and_publication(self):
        self.generate();before=[tools.digest(a['local_path']) for a in self.fixture.assets[:2]]
        task=self.join('copy')
        def compressed(path):
            run=subprocess.run([self.exe,'-nostdin','-v','error','-i',str(path),'-map','0:v:0','-c','copy','-f','data','-'],capture_output=True,check=True)
            return run.stdout
        import hashlib
        self.assertEqual(hashlib.sha256(b''.join(compressed(a['local_path']) for a in self.fixture.assets[:2])).digest(),hashlib.sha256(compressed(task['output'])).digest())
        result=self.service.review(task['id'],1,'manual')
        self.assertEqual(result['status'],'applied',result.get('error'));self.assertEqual(before,[tools.digest(a['local_path']) for a in self.fixture.assets[:2]])
    def test_normalization_geometry_and_join_with_software_fixture_encoder(self):
        self.generate(mixed=True)
        native=multipart.normalize_command
        def software_fixture(*args):
            argv=native(*args)
            index=argv.index('-c:v')
            stop=argv.index('-vf')
            argv[index+1:stop]=['mpeg4','-q:v','2']
            return argv
        with patch('curator.file_workflows.multipart.normalize_command',side_effect=software_fixture):
            task=self.join('normalize')
        self.assertEqual((task['result']['width'],task['result']['height']),(320,180))

    def test_mov_timecode_and_pcm_join_to_mkv_without_timecode_mapping(self):
        self.generate(timecode=True)
        self.assertTrue(any(s.get('codec_tag_string')=='tmcd' for s in self.fixture.assets[0]['technical']['streams']))
        task=self.join('copy')
        self.assertEqual([s['codec_type'] for s in task['result']['streams']],['video','audio'])
        self.assertEqual(task['result']['streams'][1]['codec_name'],'pcm_s24le')
        self.assertTrue(all(any(s.get('codec_tag_string')=='tmcd' for s in tools.probe(a['local_path'],{})['streams']) for a in self.fixture.assets[:2]))
