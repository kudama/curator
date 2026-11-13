import base64
import copy
import unittest

from curator import branding
from curator.artwork import resolve_style
from curator.store import Store
import test_curator

PNG=b'\x89PNG\r\n\x1a\nsynthetic'
ENCODED=base64.b64encode(PNG).decode()


class ArtworkPlans(unittest.TestCase):
    setUp=test_curator.Workflows.setUp
    tearDown=test_curator.Workflows.tearDown

    def plan(self, **kwargs):
        return self.service.artwork_plan([self.asset['id']], 'cover', 'gritty', images={self.asset['id']:ENCODED}, **kwargs)

    def adapter(self):
        self.images={}
        def upload(key,data,kind):
            self.plex.writes.append((key,kind));self.images[kind]=data
            self.plex.rows[0]['thumb']='/selected';return copy.deepcopy(self.plex.rows[0])
        self.plex.artwork=upload
        self.plex.image=lambda key,kind:self.images[kind]

    def test_import_is_durable_review_not_a_write_and_publication_is_verified(self):
        self.adapter();task=self.plan()['tasks'][0]
        self.assertEqual(task['status'],'awaiting_review');self.assertEqual(self.plex.writes,[])
        self.assertEqual(self.service.folder_image(task['plan']['candidate']),PNG)
        self.file.unlink()  # Artwork review doesn't require the NAS video mount.
        result=self.service.review(task['id'],1,'explicit fixture approval')
        self.assertEqual(result['status'],'applied');self.assertTrue(result['result']['verified'])
        self.assertEqual(len(self.plex.writes),1)
        with self.assertRaises(ValueError):self.service.review(task['id'],1,'duplicate')
        self.assertEqual(len(self.plex.writes),1)

    def test_stale_plex_artwork_blocks_before_upload_retains_candidate(self):
        self.adapter();task=self.plan()['tasks'][0]
        self.plex.rows[0]['thumb']='/changed';self.images['cover']=b'\x89PNG\r\n\x1a\nchanged'
        with self.assertRaisesRegex(ValueError,'changed after preview'):
            self.service.review(task['id'],1,'explicit fixture approval')
        self.assertEqual(self.plex.writes,[])
        self.assertEqual(self.service.get_task(task['id'])['status'],'blocked')
        self.assertEqual(self.service.folder_image(task['plan']['candidate']),PNG)

    def test_original_is_preserved_and_identical_image_is_noop(self):
        self.adapter();self.plex.rows[0]['thumb']='/old';self.images['cover']=PNG
        result=self.plan();self.assertEqual(result['tasks'],[]);self.assertEqual(result['skipped'],[self.asset['id']])
        self.images['cover']=b'\x89PNG\r\n\x1a\noriginal';task=self.plan()['tasks'][0]
        self.assertEqual(self.service.folder_image(task['plan']['original']),self.images['cover'])

    def test_bad_readback_is_blocked_with_partial_upload_receipt(self):
        self.adapter();task=self.plan()['tasks'][0]
        upload=self.plex.artwork
        def bad_upload(*args):
            result=upload(*args);self.images['cover']=b'wrong';return result
        self.plex.artwork=bad_upload
        with self.assertRaisesRegex(ValueError,'readback differs'):
            self.service.review(task['id'],1,'explicit approval')
        task=self.service.get_task(task['id'])
        self.assertEqual(task['status'],'blocked');self.assertTrue(task['result']['uploaded'])

    def test_style_snapshot_and_per_title_context_survive_rename_and_deletion(self):
        task=self.service.artwork_plan([self.asset['id']],'cover','gritty')['tasks'][0]
        saved=copy.deepcopy(task['plan'])
        self.service.save_config({'branding_presets':[branding.DEFAULT_PRESETS[1]]})
        self.assertEqual(self.service.get_task(task['id'])['plan'],saved)
        style=self.service.save_artwork_style(task['id'],'From saved plan')
        self.assertEqual(style['details'],saved['settings']['prompt'])
        self.assertEqual(style['model'],'mango-v3')
        self.assertIn(self.asset['title'],saved['settings']['prompt'])
        with self.store.transaction():self.service.reconcile_findings(self.asset,[])
        self.assertEqual(self.service.get_task(task['id'])['status'],'recommendation')

    def test_drafts_survive_state_reopen(self):
        self.adapter();task=self.plan()['tasks'][0];root=self.store.root
        self.store.close();self.store=Store(root);self.service.store=self.store
        self.assertEqual(self.service.get_task(task['id'])['plan'],task['plan'])
        self.assertEqual(self.service.folder_image(task['plan']['candidate']),PNG)

    def test_unselected_images_and_generic_queue_or_edit_are_rejected(self):
        with self.assertRaises(ValueError):self.service.artwork_plan([self.asset['id']],'cover','gritty',images={'unselected':ENCODED})
        task=self.service.artwork_plan([self.asset['id']],'cover','gritty')['tasks'][0]
        with self.assertRaises(ValueError):self.service.action(task['id'],'queue',1)
        with self.assertRaises(ValueError):self.service.edit_task(task['id'],{'title':'silent change'},1)
        self.assertEqual(self.plex.writes,[])

    def test_ratios_target_defaults_explicit_overrides_and_style_defaults(self):
        preset=dict(branding.DEFAULT_PRESETS[0],model='mango-v3s',resolution='3K',ratio='9:16',negative_prompt='No frame')
        for profile,kind,ratio in [('home','cover','16:9'),('commercial','cover','2:3'),('commercial','background','16:9'),('home','square','1:1')]:
            result=resolve_style(preset,{'title':'Title','summary':'Context'},profile,kind,{})
            self.assertEqual(result['settings']['ratio'],ratio)
            self.assertEqual(result['settings']['resolution'],'3K')
            self.assertEqual(result['settings']['negative_prompt'],'No frame')
        result=resolve_style(preset,{'title':'Another title'},'home','cover',{'ratio':'4:5','resolution':'1K'})
        self.assertEqual(result['settings']['ratio'],'4:5');self.assertIn('Another title',result['settings']['prompt'])
        with self.assertRaises(ValueError):resolve_style(preset,{},'home','folder',{})

    def test_per_title_batch_freezes_distinct_context_and_selected_targets(self):
        second=copy.deepcopy(self.asset);second.update(id='b'*24,rating_key='20',title='Second title');item=copy.deepcopy(self.asset['item']);item.update(ratingKey='20',title='Second title',summary='Different context')
        first=self.plex.item('10');self.plex.item=lambda key:copy.deepcopy(first if key=='10' else item)
        with self.store.transaction():self.store.put('assets',second['id'],second)
        result=self.service.artwork_plan([self.asset['id'],second['id']],'cover','gritty')
        prompts=[t['plan']['settings']['prompt'] for t in result['tasks']]
        self.assertNotEqual(prompts[0],prompts[1]);self.assertIn('Second title',prompts[1])
        self.assertEqual({t['asset'] for t in result['tasks']},{self.asset['id'],second['id']})

    def test_mage_consent_is_required_once_for_exact_saved_quote(self):
        from unittest.mock import patch
        task=self.service.artwork_plan([self.asset['id']],'cover','gritty')['tasks'][0]
        with patch('curator.mage.Mage') as cls:
            provider=cls.return_value;provider.credential_identity.return_value='fixture-key'
            provider.quote.return_value={'gems':7,'body':{'model_id':'mango-v3','prompt':'Synthetic'},'basis':'synthetic quote'}
            quote=self.service.mage_quote([{'id':task['id'],'version':1}])
            self.assertEqual(quote['total'],7);self.assertEqual(quote['count'],1)
            with self.assertRaises(ValueError):self.service.authorize_mage(quote['id'],False)
            self.service.authorize_mage(quote['id'],True)
            with self.assertRaises(ValueError):self.service.authorize_mage(quote['id'],True)
            provider.submit.assert_not_called()
        saved=self.service.get_task(task['id']);self.assertEqual(saved['status'],'queued')
        self.assertIn('idempotency_key',saved['provider'])

    def test_mage_completed_job_downloads_before_review_never_publishes(self):
        from unittest.mock import Mock
        self.adapter();task=self.service.artwork_plan([self.asset['id']],'cover','gritty')['tasks'][0]
        task.update(status='running',provider={'credential':'test','attempted':True,'idempotency_key':'same-key','body':{'prompt':'Synthetic'},'estimate':7})
        provider=Mock();provider.credential_identity.return_value='test'
        provider.submit.return_value={'request_id':'a'*36,'status':'in_progress','billing':{'gems_charged':7}}
        provider.status.return_value={'request_id':'a'*36,'status':'completed','billing':{'gems_charged':7},'result':{'url':'https://assets.mage.space/result.png'}}
        provider.download.return_value=PNG
        self.service.execute_mage(task,provider,lambda seconds:None)
        saved=self.service.get_task(task['id']);self.assertEqual(saved['status'],'awaiting_review');self.assertEqual(saved['kind'],'artwork')
        self.assertEqual(self.service.folder_image(saved['plan']['candidate']),PNG)
        self.assertEqual(saved['provider']['billing']['gems_charged'],7);self.assertEqual(self.plex.writes,[])

    def test_mage_recovery_polls_known_request_without_resubmit_and_keeps_charge_on_cancel(self):
        from unittest.mock import Mock
        task=self.service.artwork_plan([self.asset['id']],'cover','gritty')['tasks'][0]
        task.update(status='running',provider={'credential':'test','idempotency_key':'same','request_id':'b'*36,'body':{},'estimate':7})
        provider=Mock();provider.credential_identity.return_value='test'
        provider.status.return_value={'request_id':'b'*36,'status':'in_progress','billing':{'gems_charged':7}}
        provider.cancel.return_value={'request_id':'b'*36,'status':'cancelled','billing':{'gems_charged':7}}
        self.service.cancels.add(task['id']);self.service.execute_mage(task,provider,lambda seconds:None)
        saved=self.service.get_task(task['id']);self.assertEqual(saved['status'],'cancelled');self.assertEqual(saved['result']['billing']['gems_charged'],7)
        provider.submit.assert_not_called();provider.cancel.assert_called_once()

    def test_mage_uncertain_submit_reuses_same_body_and_key_after_explicit_resume(self):
        from unittest.mock import Mock
        task=self.service.artwork_plan([self.asset['id']],'cover','gritty')['tasks'][0]
        task.update(status='blocked',provider={'credential':'test','attempted':True,'idempotency_key':'durable-key','body':{'prompt':'Synthetic'},'estimate':7})
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        task=self.service.resume_mage(task['id'],1)
        provider=Mock();provider.credential_identity.return_value='test';provider.submit.side_effect=ValueError('Timeout; unknown outcome')
        with self.assertRaises(ValueError):self.service.execute_mage(task,provider,lambda seconds:None)
        provider.submit.assert_called_once_with({'prompt':'Synthetic'},'durable-key')
        provider.credential_identity.return_value='changed'
        with self.assertRaisesRegex(ValueError,'credential changed'):self.service.execute_mage(task,provider,lambda seconds:None)
        self.assertEqual(provider.submit.call_count,1)

    def test_local_portrait_identity_and_image_save_do_not_modify_plex(self):
        self.plex.rows[0]['Role']=[dict(tag='Alice',role='Self',thumb='')]
        saved=self.service.remember_portrait_identity(self.asset['id'],0)
        saved=self.service.save_portrait(saved['profile_id'],saved['revision'],ENCODED)
        self.assertEqual(self.service.cast_profile_image(saved['profile_id']),PNG)
        self.assertEqual(self.plex.writes,[])
        with self.assertRaises(ValueError):self.service.save_portrait(saved['profile_id'],1,ENCODED)
        with self.assertRaises(ValueError):self.service.remember_portrait_identity(self.asset['id'],0)

    def test_portrait_review_selects_exact_credit_and_preserves_other_people(self):
        self.plex.rows[0]['Role']=[dict(tag='Alice',role='Self',thumb=''),dict(tag='Bob',role='Guest',thumb='/bob')]
        saved=self.service.remember_portrait_identity(self.asset['id'],0)
        saved=self.service.save_portrait(saved['profile_id'],1,ENCODED)
        result=self.service.portrait_plan(saved['profile_id'],saved['revision'],[{'asset':self.asset['id'],'index':0}])
        task=result['tasks'][0];self.assertEqual(task['plan']['before'][1],dict(name='Bob',role='Guest',thumb='/bob'))
        self.assertEqual(self.plex.writes,[])
        with self.assertRaisesRegex(ValueError,'identity changed'):
            self.service.portrait_plan(saved['profile_id'],saved['revision'],[{'asset':self.asset['id'],'index':1}])
        with self.assertRaises(ValueError):self.service.portrait_plan(saved['profile_id'],1,[{'asset':self.asset['id'],'index':0}])

    def test_native_portrait_publication_is_blocked_without_any_external_write(self):
        from unittest.mock import Mock
        from curator.plex import Plex
        self.plex.rows[0]['Role']=[dict(tag='Alice',role='Self',thumb='')]
        saved=self.service.remember_portrait_identity(self.asset['id'],0);saved=self.service.save_portrait(saved['profile_id'],1,ENCODED)
        task=self.service.portrait_plan(saved['profile_id'],saved['revision'],[{'asset':self.asset['id'],'index':0}])['tasks'][0]
        client=Mock(spec=Plex);self.service.checked_client=lambda library:client
        with self.assertRaisesRegex(ValueError,'transport is unverified'):
            self.service.review(task['id'],1,'fixture approval')
        client.cast_photo.assert_not_called();client.edit.assert_not_called()
        self.assertEqual(self.service.get_task(task['id'])['status'],'blocked')

    def test_price_is_rechecked_before_first_paid_attempt(self):
        from unittest.mock import Mock
        task=self.service.artwork_plan([self.asset['id']],'cover','gritty')['tasks'][0]
        task.update(status='running',provider={'credential':'test','idempotency_key':'same','body':{'prompt':'Synthetic'},'estimate':7})
        provider=Mock();provider.credential_identity.return_value='test';provider.quote.return_value={'gems':8,'body':{'prompt':'Synthetic'}}
        with self.assertRaisesRegex(ValueError,'price or supported settings changed'):
            self.service.execute_mage(task,provider,lambda seconds:None)
        provider.submit.assert_not_called()

    def test_generation_request_identity_survives_restart_without_replay(self):
        task=self.service.artwork_plan([self.asset['id']],'cover','gritty')['tasks'][0]
        task.update(status='running',provider={'credential':'test','idempotency_key':'durable','request_id':'b'*36,'body':{},'estimate':7})
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        root=self.store.root;self.store.close();self.store=Store(root);self.service.store=self.store
        saved=self.service.get_task(task['id']);self.assertEqual(saved['status'],'blocked');self.assertEqual(saved['provider']['request_id'],'b'*36)
        self.service.resume_mage(task['id'],1);self.assertEqual(self.service.get_task(task['id'])['provider']['idempotency_key'],'durable')

    def test_references_remain_private_local_blobs_until_quoted_consent(self):
        result=self.service.artwork_plan([self.asset['id']],'cover','gritty',references=[ENCODED])
        task=result['tasks'][0];photo=task['plan']['reference_photos'][0]
        self.assertEqual(self.service.folder_image(photo),PNG)
        self.assertEqual(task['evidence']['outbound_files'],[photo]);self.assertNotIn('provider',task)
        self.assertEqual(self.plex.writes,[])
        with self.assertRaises(ValueError):self.service.artwork_plan([self.asset['id']],'cover','gritty',references=[''])

    def test_tampered_candidate_never_reaches_plex(self):
        self.adapter();task=self.plan()['tasks'][0]
        (self.store.root/'folder-images'/task['plan']['candidate']).write_bytes(b'tampered')
        with self.assertRaises(ValueError):self.service.review(task['id'],1,'explicit fixture approval')
        self.assertEqual(self.plex.writes,[])

    def test_candidate_requests_are_individually_accountable_and_unsubmitted(self):
        task=self.service.artwork_plan([self.asset['id']],'cover','gritty')['tasks'][0]
        result=self.service.artwork_candidates(task['id'],1,3)
        self.assertEqual(len({t['id'] for t in result['tasks']}),3)
        self.assertEqual(len({t['evidence']['candidate_group'] for t in result['tasks']}),1)
        self.assertTrue(all(t['status']=='recommendation' and not t.get('provider') for t in result['tasks']))
        self.assertEqual([t['evidence']['candidate_index'] for t in result['tasks']],[1,2,3])
        self.assertEqual(self.plex.writes,[])
        with self.assertRaises(ValueError):self.service.artwork_candidates(task['id'],1,2)

    def test_collection_poster_default_stays_portrait_in_home_profile(self):
        plan=resolve_style(branding.DEFAULT_PRESETS[0],{'type':'collection','title':'Collection'},'home','cover',{})
        self.assertEqual(plan['settings']['ratio'],'2:3')

    def test_reused_plex_rating_key_with_changed_source_identity_blocks_publish(self):
        self.adapter();task=self.plan()['tasks'][0]
        self.plex.rows[0]['Media']=[{'Part':[{'file':'/plex/replaced-title.mkv'}]}]
        with self.assertRaisesRegex(ValueError,'destination identity changed'):
            self.service.review(task['id'],1,'explicit fixture approval')
        self.assertEqual(self.plex.writes,[])
