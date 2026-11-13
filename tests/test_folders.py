import base64
import copy
import hashlib
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import test_curator
from curator.folders import combine
from curator.tools import fingerprint

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=')


class Folders(unittest.TestCase):
    setUp = test_curator.Workflows.setUp
    tearDown = test_curator.Workflows.tearDown

    def folder(self, path='/plex'):
        return next(row for row in self.service.folder_nodes() if row['path']==path)

    def settings(self, **values):
        return dict(fields={'studio':'Shared studio'},artwork={},mode='fill',recursive=False,**values)

    def add(self, aid, path, rating='20'):
        local=self.media/path;local.parent.mkdir(parents=True,exist_ok=True);local.write_bytes(b'video')
        asset=dict(self.asset,id=aid,rating_key=rating,plex_path='/plex/'+path,local_path=str(local.resolve()),fingerprint=fingerprint(local))
        with self.store.transaction():self.store.put('assets',aid,asset)
        if not any(r['ratingKey']==rating for r in self.plex.rows):
            item=copy.deepcopy(self.asset['item']);item.update(ratingKey=rating,Media=[{'Part':[{'file':'/plex/'+path}]}]);self.plex.rows.append(item)
        self.plex.item=lambda rating:copy.deepcopy(next(r for r in self.plex.rows if r['ratingKey']==rating))
        return asset

    def tagged_adapter(self):
        def edit(library,item,changes):
            self.plex.writes.append(changes)
            for field,value in changes.items():
                if field=='cast':self.plex.rows[0]['Role']=[dict(tag=r['name'],role=r['role'],thumb=r['thumb']) for r in value]
                elif isinstance(value,list):self.plex.rows[0][field.title()]=[{'tag':x} for x in value]
                else:self.plex.rows[0][field]=value
            return copy.deepcopy(self.plex.item('10'))
        self.plex.edit=edit
        self.art={}
        def artwork(rating,data,kind):
            self.art[kind]=data;self.plex.writes.append(kind)
            self.plex.rows[0][{'cover':'thumb','background':'art','logo':'clearLogo','square':'squareArt'}[kind]]='/library/art/'+kind
            return self.plex.item(rating)
        self.plex.artwork=artwork;self.plex.image=lambda rating,kind:self.art[kind]
        self.plex.cast_photo=lambda rating,data:'/library/uploaded/photo'
        self.plex.cast_image=lambda path:PNG

    def test_tree_counts_include_parent_levels_and_hide_deleted(self):
        self.add('b'*24,'Series/Part1.mkv');self.add('c'*24,'Series/Nested/Part2.mkv')
        gone=self.add('d'*24,'Gone/file.mkv');gone['present']=False
        with self.store.transaction():self.store.put('assets',gone['id'],gone)
        self.assertEqual(self.folder()['count'],3);self.assertEqual(self.folder('/plex/Series')['count'],2)
        self.assertEqual(self.folder('/plex/Series')['direct_count'],1)
        self.assertNotIn('/plex/Gone',[r['path'] for r in self.service.folder_nodes()])

    def test_recursive_scope_uses_path_components(self):
        self.add('b'*24,'A/one.mkv');self.add('c'*24,'A/Sub/two.mkv');self.add('d'*24,'AB/three.mkv')
        folder=self.folder('/plex/A')
        self.assertEqual(len(self.service.folder_members(folder,False)),1)
        self.assertEqual(len(self.service.folder_members(folder,True)),2)

    def test_fill_merge_replace(self):
        self.assertEqual(combine('Existing','New','fill','studio'),'Existing')
        self.assertEqual(combine(['Old'],['old','New'],'merge','label'),['Old','New'])
        self.assertEqual(combine('Existing','New','merge','studio'),'Existing')
        self.assertEqual(combine('Existing','','replace','studio'),'')
        merged=combine([{'name':'A','role':'','thumb':''}],[{'name':'a','role':'Actor','photo':'abc'},{'name':'B'}],'merge','cast')
        self.assertEqual(len(merged),2);self.assertEqual(merged[0]['role'],'Actor');self.assertEqual(merged[0]['photo'],'abc')

    def test_preview_has_live_before_and_no_plex_writes(self):
        data=self.settings();data['fields']={'summary':'New','studio':'Shared'}
        preview=self.service.folder_preview(self.folder()['id'],data)
        self.assertEqual(preview['rows'][0]['before']['summary'],'Before')
        self.assertEqual(preview['rows'][0]['changes'],{'studio':'Shared'})
        self.assertEqual(self.plex.writes,[])

    def test_preview_deduplicates_multiple_files_for_one_plex_title(self):
        self.add('b'*24,'version.mkv',rating='10')
        preview=self.service.folder_preview(self.folder()['id'],self.settings())
        self.assertEqual(len(preview['rows']),1);self.assertEqual(len(preview['members']),2)

    def test_preview_queue_run_and_no_duplicate_submission(self):
        self.tagged_adapter();preview=self.service.folder_preview(self.folder()['id'],self.settings())
        queued=self.service.queue_folder_preview(preview['id']);self.assertEqual(queued['queued'],1);self.assertEqual(self.plex.writes,[])
        self.service._execute(queued['tasks'][0]);self.assertEqual(self.service.get_task(queued['tasks'][0])['status'],'applied')
        self.assertEqual(self.plex.rows[0]['studio'],'Shared studio')
        with self.assertRaisesRegex(ValueError,'already queued'):self.service.queue_folder_preview(preview['id'])

    def test_membership_or_source_changed_requires_new_preview(self):
        preview=self.service.folder_preview(self.folder()['id'],self.settings());self.add('b'*24,'new.mkv')
        with self.assertRaisesRegex(ValueError,'membership changed'):self.service.queue_folder_preview(preview['id'])
        preview=self.service.folder_preview(self.folder()['id'],self.settings());self.file.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.service.queue_folder_preview(preview['id'])
        self.assertEqual(self.plex.writes,[])

    def test_external_metadata_change_blocks_worker(self):
        preview=self.service.folder_preview(self.folder()['id'],self.settings());queued=self.service.queue_folder_preview(preview['id'])
        self.plex.rows[0]['summary']='External edit';self.service._execute(queued['tasks'][0])
        task=self.service.get_task(queued['tasks'][0]);self.assertEqual(task['status'],'blocked');self.assertIn('metadata changed',task['error']);self.assertEqual(self.plex.writes,[])

    def test_missing_file_is_reported_and_not_queued(self):
        self.file.unlink();preview=self.service.folder_preview(self.folder()['id'],self.settings())
        self.assertIn('error',preview['rows'][0])
        with self.assertRaisesRegex(ValueError,'No applicable'):self.service.queue_folder_preview(preview['id'])

    def test_defaults_are_versioned_and_inherited_by_path(self):
        nested=self.add('b'*24,'Series/Sub/one.mkv');self.add('c'*24,'Other/two.mkv')
        folder=self.folder('/plex/Series');data=self.settings();data['recursive']=True
        saved=self.service.save_folder_defaults(folder['id'],data,None)
        with self.assertRaisesRegex(ValueError,'defaults changed'):self.service.save_folder_defaults(folder['id'],data,None)
        inherited=self.service.folder_read(self.folder('/plex/Series/Sub')['id'])['inherited'];self.assertEqual(len(inherited),1)
        self.assertEqual(self.service.folder_read(self.folder('/plex/Other')['id'])['inherited'],[])
        with self.store.transaction():self.service.recommend_folder_defaults(nested)
        tasks=[t for t in self.store.all('tasks') if t['kind']=='folder_metadata'];self.assertEqual(len(tasks),1);self.assertEqual(tasks[0]['status'],'recommendation')
        self.assertEqual(self.plex.writes,[])

    def test_defaults_dont_recommend_already_applied_shared_art(self):
        self.tagged_adapter();data=self.settings();data['mode']='replace';data['artwork']={'background':{'image':base64.b64encode(PNG).decode()}}
        self.service.save_folder_defaults(self.folder()['id'],data,None)
        preview=self.service.folder_preview(self.folder()['id'],data);queued=self.service.queue_folder_preview(preview['id']);self.service._execute(queued['tasks'][0])
        asset=self.store.get('assets',self.asset['id'])
        with self.store.transaction():self.service.recommend_folder_defaults(asset)
        self.assertEqual(len([t for t in self.store.all('tasks') if t['kind']=='folder_metadata' and t['status']=='recommendation']),0)

    def test_shared_art_uploaded_and_content_verified(self):
        self.tagged_adapter();data=self.settings();data['artwork']={'background':{'image':base64.b64encode(PNG).decode()}}
        preview=self.service.folder_preview(self.folder()['id'],data);queued=self.service.queue_folder_preview(preview['id']);self.service._execute(queued['tasks'][0])
        task=self.service.get_task(queued['tasks'][0]);self.assertEqual(task['status'],'applied');self.assertTrue(task['result']['background_verified'])
        self.assertEqual(self.art['background'],PNG)

    def test_art_changed_after_preview_blocks_before_metadata_write(self):
        self.tagged_adapter();self.plex.rows[0]['art']='/art';self.art['background']=PNG
        data=self.settings();data['mode']='replace';data['artwork']={'background':{'image':base64.b64encode(PNG+b'x').decode()}}
        preview=self.service.folder_preview(self.folder()['id'],data);queued=self.service.queue_folder_preview(preview['id']);self.art['background']=PNG+b'changed'
        self.service._execute(queued['tasks'][0]);self.assertEqual(self.service.get_task(queued['tasks'][0])['status'],'blocked');self.assertEqual(self.plex.writes,[])

    def test_cast_saved_profile_picture_works_without_public_host(self):
        self.tagged_adapter();pid='a'*32;photo=hashlib.sha256(PNG).hexdigest();(self.store.root/'cast').mkdir();(self.store.root/'cast'/photo).write_bytes(PNG)
        with self.store.transaction():self.store.put('settings','cast_profiles',{pid:dict(name='Actor',revision=1,photo=photo)})
        data=self.settings();data['fields']={'cast':[dict(name='Actor',profile_id=pid,revision=1)]}
        preview=self.service.folder_preview(self.folder()['id'],data);queued=self.service.queue_folder_preview(preview['id']);self.service._execute(queued['tasks'][0])
        self.assertEqual(self.service.get_task(queued['tasks'][0])['status'],'applied');self.assertEqual(self.plex.rows[0]['Role'][0]['thumb'],'/library/uploaded/photo')
        data['fields']['cast'][0]['revision']=2
        with self.assertRaisesRegex(ValueError,'profile changed'):self.service.folder_preview(self.folder()['id'],data)

    def test_blob_traversal_symlink_and_unknown_folder_rejected(self):
        with self.assertRaises(ValueError):self.service.folder_image('../../secret')
        with self.assertRaises(ValueError):self.service.folder_read('unknown')
        directory=self.store.root/'folder-images';directory.mkdir();(directory/('a'*64)).symlink_to(self.file)
        with self.assertRaises(ValueError):self.service.folder_image('a'*64)
        for settings in [dict(fields={'unknown':'x'}),dict(artwork={'unsupported':{}}),dict(mode='unexpected')]:
            with self.assertRaises(ValueError):self.service.folder_settings(settings)

    def test_background_publication_returns_before_operation_finishes_and_state_readable(self):
        task=dict(self.task,kind='join',status='awaiting_review',comparison_loaded=True)
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        started=threading.Event();release=threading.Event();done=threading.Event()
        def slow_publish(task):
            started.set();release.wait(2);self.service._save(task,status='applied');done.set()
        with patch.object(self.service,'publish_join',slow_publish):
            result=self.service.review(task['id'],1,'manual',background=True)
            try:
                self.assertTrue(started.wait(1));self.assertTrue(result['background']);self.assertEqual(self.service.state()['tasks'][0]['status'],'publishing')
                with self.assertRaises(ValueError):self.service.review(task['id'],1,'manual',background=True)
            finally:release.set();self.assertTrue(done.wait(2))

    def test_queue_preflight_does_not_hold_database_lock(self):
        started=threading.Event();release=threading.Event();done=threading.Event();errors=[]
        self.task['kind']='group'
        with self.store.transaction():self.store.put('tasks',self.task['id'],self.task)
        def slow(task):started.set();release.wait(2)
        def queue():
            try:self.service.action(self.task['id'],'queue',1)
            except Exception as error:errors.append(error)
            finally:done.set()
        with patch.object(self.service,'queue_file_task',slow),patch.object(self.service,'_file_conflicts'):
            worker=threading.Thread(target=queue);worker.start()
            try:
                self.assertTrue(started.wait(1));start=time.monotonic();self.assertEqual(self.service.state()['tasks'][0]['status'],'recommendation');self.assertLess(time.monotonic()-start,0.5)
            finally:release.set();worker.join(2)
        self.assertTrue(done.is_set());self.assertEqual(errors,[])


    def test_active_title_skipped_but_other_folder_titles_preview(self):
        self.add('b'*24,'other.mkv',rating='20')
        busy=dict(self.task,kind='join',status='running',plan={'assets':[self.asset['id']]})
        with self.store.transaction():self.store.put('tasks',busy['id'],busy)
        preview=self.service.folder_preview(self.folder()['id'],self.settings())
        self.assertIn('active work',preview['rows'][0]['error']);self.assertNotIn('error',preview['rows'][1])
        self.assertEqual(self.service.queue_folder_preview(preview['id'])['queued'],1)

    def test_presence_refresh_preserves_reserved_asset_during_rename(self):
        busy=dict(self.task,kind='rename',status='publishing',plan={'assets':[self.asset['id']]})
        with self.store.transaction():self.store.put('tasks',busy['id'],busy)
        self.file.unlink();self.plex.items=lambda library:iter([])
        self.service._sync_presence(self.lib)
        self.assertTrue(self.store.get('assets',self.asset['id'])['present'])

    def test_background_publication_failure_is_visible_in_task(self):
        task=dict(self.task,kind='join',status='awaiting_review',comparison_loaded=True)
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        finished=threading.Event()
        original=self.service._finish_review
        def finish(*args):
            try:return original(*args)
            finally:finished.set()
        with patch.object(self.service,'publish_join',side_effect=ValueError('Provider unavailable')),patch.object(self.service,'_finish_review',finish):
            self.service.review(task['id'],1,'manual',background=True);self.assertTrue(finished.wait(2))
        saved=self.service.get_task(task['id']);self.assertEqual(saved['status'],'blocked');self.assertIn('Provider unavailable',saved['error'])


    def test_background_publication_reserves_only_its_sources(self):
        task=dict(self.task,kind='join',status='publishing',plan={'assets':[self.asset['id']]})
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        same=dict(self.task,id='second')
        with self.assertRaisesRegex(ValueError,'reserved'):self.service.check_busy_sources(same)
        other=self.add('b'*24,'unrelated.mkv',rating='20')
        self.service.check_busy_sources(dict(same,asset=other['id']))


    def test_folder_load_ignores_scalar_storage_compatibility_settings(self):
        with self.store.transaction():
            self.store.put('settings','copy-install:device',True)
            self.store.put('settings','other-value',None)
        result=self.service.folder_read(self.folder()['id'])
        self.assertEqual(result['inherited'],[]);self.assertIsNone(result['defaults'])

    def test_folder_preview_ignores_nonrecord_settings_during_expiry_cleanup(self):
        with self.store.transaction():self.store.put('settings','copy-install:device',True)
        preview=self.service.folder_preview(self.folder()['id'],self.settings())
        self.assertEqual(preview['rows'][0]['changes'],{'studio':'Shared studio'})
        self.assertEqual(self.plex.writes,[])

    def test_scan_default_recommendations_ignore_scalar_settings(self):
        self.service.save_folder_defaults(self.folder()['id'],self.settings(),None)
        with self.store.transaction():
            self.store.put('settings','copy-install:device',True)
            self.service.recommend_folder_defaults(self.asset)
        self.assertEqual(len([t for t in self.service.state()['tasks'] if t['kind']=='folder_metadata']),1)


    def test_multiple_plex_roots_remain_visible_when_one_is_unmapped(self):
        library=dict(self.lib,locations=[{'path':'/plex'},{'path':'/second'}])
        with self.store.transaction():self.store.put('libraries',library['id'],library)
        roots=[r for r in self.service.folder_nodes() if r['parent'] is None]
        self.assertEqual({r['path'] for r in roots},{'/plex','/second'})
        missing=next(r for r in roots if r['path']=='/second')
        self.assertFalse(missing['mapped']);self.assertEqual(missing['count'],0)
        self.assertFalse(self.service.folder_read(missing['id'])['folder']['mapped'])

    def test_two_roots_translate_to_independent_mac_folders(self):
        second=self.root/'second-share';second.mkdir();(second/'second.mkv').write_bytes(b'second')
        library=dict(self.lib,locations=[{'path':'/plex'},{'path':'/second'}],mappings=self.lib['mappings']+[{'plex_root':'/second','local_root':str(second)}])
        item=dict(self.asset['item'],ratingKey='20',Media=[{'Part':[{'file':'/second/second.mkv'}]}])
        asset=dict(self.asset,id='b'*24,rating_key='20',plex_path='/second/second.mkv',local_path=str((second/'second.mkv').resolve()),fingerprint=fingerprint(second/'second.mkv'),item=item)
        self.plex.rows.append(item);self.plex.item=lambda rating:copy.deepcopy(next(r for r in self.plex.rows if r['ratingKey']==rating))
        with self.store.transaction():self.store.put('libraries',library['id'],library);self.store.put('assets',asset['id'],asset)
        roots=[r for r in self.service.folder_nodes() if not r['parent']]
        self.assertEqual(len(roots),2);self.assertTrue(all(r['mapped'] and r['count']==1 for r in roots))
        for folder in roots:
            preview=self.service.folder_preview(folder['id'],self.settings())
            self.assertEqual(len(preview['rows']),1);self.assertNotIn('error',preview['rows'][0])

    def test_independent_roots_with_same_basename_have_distinct_ids(self):
        library=dict(self.lib,locations=[{'path':'/disk1/Movies'},{'path':'/disk2/Movies'}])
        with self.store.transaction():self.store.put('libraries',library['id'],library)
        roots=[r for r in self.service.folder_nodes() if r['path'].endswith('/Movies')]
        self.assertEqual(len(roots),2);self.assertNotEqual(roots[0]['id'],roots[1]['id'])

    def test_location_refresh_preserves_profile_and_existing_mac_paths(self):
        self.plex.libraries=lambda:[dict(self.lib,locations=[{'path':'/plex'},{'path':'/new'}],mappings=[],profile='home')]
        refreshed=self.service.refresh_library_locations(self.lib['id'])
        self.assertEqual(len(refreshed['locations']),2);self.assertEqual(refreshed['mappings'],self.lib['mappings'])
        self.assertEqual(refreshed['profile'],self.lib['profile'])

    def test_failed_location_refresh_retains_cached_mappings(self):
        self.plex.libraries=lambda:[]
        with self.assertRaises(ValueError):self.service.refresh_library_locations(self.lib['id'])
        self.assertEqual(self.service.library(self.lib['id']),self.lib)

    def test_parent_mapping_can_cover_multiple_declared_roots(self):
        library=dict(self.lib,locations=[{'path':'/plex/A'},{'path':'/plex/B'}])
        with self.store.transaction():self.store.put('libraries',library['id'],library)
        roots=[r for r in self.service.folder_nodes() if r['path'] in {'/plex/A','/plex/B'}]
        self.assertEqual(len(roots),2);self.assertTrue(all(r['mapped'] for r in roots))


    def test_noop_preview_resolves_matching_folder_recommendation_without_queueing(self):
        self.service.save_folder_defaults(self.folder()['id'],self.settings(),None)
        with self.store.transaction():self.service.recommend_folder_defaults(self.asset)
        self.plex.rows[0]['studio']='Shared studio'
        home=dict(self.task,id='satisfied-home',kind='home',status='awaiting_review',result={'title':'Film','summary':'Before','themes':[]})
        with self.store.transaction():self.store.put('tasks',home['id'],home)
        preview=self.service.folder_preview(self.folder()['id'],self.settings())
        self.assertNotIn('error',preview['rows'][0]);self.assertEqual(self.service.get_task(home['id'])['status'],'resolved')
        self.assertEqual(preview['rows'][0]['changes'],{})
        task=next(t for t in self.service.state()['tasks'] if t['kind']=='folder_metadata')
        self.assertEqual(task['status'],'resolved');self.assertTrue(task['result']['no_changes_needed']);self.assertEqual(self.plex.writes,[])

    def test_worker_resolves_already_applied_values_without_writes_or_review(self):
        preview=self.service.folder_preview(self.folder()['id'],self.settings());queued=self.service.queue_folder_preview(preview['id'])
        self.plex.rows[0]['studio']='Shared studio';self.service._execute(queued['tasks'][0])
        task=self.service.get_task(queued['tasks'][0]);self.assertEqual(task['status'],'resolved');self.assertTrue(task['result']['no_changes_needed']);self.assertEqual(self.plex.writes,[])

    def test_same_tags_and_cast_picture_do_not_create_false_changes(self):
        self.tagged_adapter();self.plex.rows[0].update(Genre=[{'tag':'Travel'},{'tag':'Family'}],Role=[dict(tag='Actor',role='',thumb='/photo')])
        data=self.settings();data['mode']='replace';data['fields']={'genre':['family','travel'],'cast':[{'name':'Actor','image':base64.b64encode(PNG).decode()}]}
        preview=self.service.folder_preview(self.folder()['id'],data)
        self.assertEqual(preview['rows'][0]['changes'],{});self.assertEqual(self.plex.writes,[])

    def test_folder_apply_resolves_satisfied_home_review_but_keeps_video_work(self):
        self.tagged_adapter();home=dict(self.task,id='home-review',kind='home',status='awaiting_review',result={'title':'Film','summary':'Before','themes':[]})
        video=dict(self.task,id='video-review',kind='upscale',status='awaiting_review')
        with self.store.transaction():self.store.put('tasks',home['id'],home);self.store.put('tasks',video['id'],video)
        item=self.plex.item('10');item['thumb']='/cover'
        self.service.resolve_satisfied_folder_work(self.asset,item,self.folder()['id'],True)
        self.assertEqual(self.service.get_task(home['id'])['status'],'resolved')
        self.assertEqual(self.service.get_task(video['id'])['status'],'awaiting_review')
        self.assertEqual(self.service.get_task(self.task['id'])['status'],'resolved')

    def test_shared_cover_uses_existing_review_queue_and_verified_readback(self):
        self.tagged_adapter()
        data=self.settings();data.update(fields={},mode='replace',artwork={'cover':{'image':base64.b64encode(PNG).decode()}})
        preview=self.service.folder_preview(self.folder()['id'],data)
        self.assertEqual(self.plex.writes,[])
        queued=self.service.queue_folder_preview(preview['id'])
        self.service._execute(queued['tasks'][0])
        self.assertEqual(self.service.get_task(queued['tasks'][0])['status'],'applied')
        again=self.service.folder_preview(self.folder()['id'],data)
        self.assertEqual(again['rows'][0]['artwork'],{})
        with self.assertRaisesRegex(ValueError,'No applicable changes'):self.service.queue_folder_preview(again['id'])

    def saved_portrait(self):
        photo=hashlib.sha256(PNG).hexdigest();directory=self.store.root/'cast';directory.mkdir(exist_ok=True);(directory/photo).write_bytes(PNG)
        pid='a'*32
        with self.store.transaction():self.store.put('settings','cast_profiles',{pid:dict(name='Alice',revision=1,photo=photo)})
        return dict(profile_id=pid,revision=1)

    def test_portrait_only_changes_matching_identity_preserving_other_credits(self):
        self.tagged_adapter();self.plex.rows[0]['Role']=[dict(tag='Alice',role='Self',thumb=''),dict(tag='Bob',role='Guest',thumb='/bob')]
        other=self.add('b'*24,'Other.mkv');self.plex.rows[1]['Role']=[dict(tag='Bob',role='Self',thumb='/bob')]
        data=self.settings();data.update(fields={},portrait=self.saved_portrait())
        preview=self.service.folder_preview(self.folder()['id'],data)
        by_id={r['asset']:r for r in preview['rows']}
        changed=by_id[self.asset['id']]['changes']['cast']
        self.assertEqual(changed[0]['role'],'Self');self.assertIn('photo',changed[0])
        self.assertEqual(changed[1],dict(name='Bob',role='Guest',thumb='/bob'))
        self.assertEqual(by_id[other['id']]['changes'],{})
        self.assertEqual(self.plex.writes,[])
        queued=self.service.queue_folder_preview(preview['id']);self.assertEqual(queued['queued'],1)

    def test_stale_portrait_and_automatic_folder_defaults_are_rejected(self):
        data=self.settings();data.update(fields={},portrait=self.saved_portrait())
        with self.assertRaisesRegex(ValueError,'fresh preview'):
            self.service.save_folder_defaults(self.folder()['id'],data,None)
        data['portrait']['revision']=2
        with self.assertRaisesRegex(ValueError,'portrait changed'):
            self.service.folder_preview(self.folder()['id'],data)
