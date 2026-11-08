import base64
import copy
import io
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from curator import cast
from curator.plex import Plex, PlexError, NoImageRedirect
from curator.service import Service
import test_curator

PNG = b'\x89PNG\r\n\x1a\n' + b'cast-picture'


class CastWorkflow(unittest.TestCase):
    def setUp(self):
        test_curator.Workflows.setUp(self)
        self.uploads = []
        self.images = []
        def edit(library, item, changes):
            self.plex.writes.append(changes)
            self.plex.rows[0]['Role'] = [dict(tag=r['name'], role=r['role'], thumb=r['thumb']) for r in changes['cast']]
            return self.plex.item('10')
        self.plex.edit = edit
        def photo(key, data):
            self.uploads.append((key, data))
            return '/library/metadata/10/file?url=upload%3A%2F%2Fposters%2Fabcd'
        self.plex.cast_photo = photo
        def image(thumb):
            self.images.append(thumb)
            return PNG
        self.plex.cast_image = image
    tearDown = test_curator.Workflows.tearDown

    def save(self, rows, version=None):
        return self.service.apply_cast(self.task['id'], version or self.service.get_task(self.task['id'])['version'], rows)

    def test_uploaded_photo_and_reusable_profile_are_private_and_verified(self):
        result = self.save([dict(name='Example Performer', role='Self', image=base64.b64encode(PNG).decode(), remember=True)])
        self.assertEqual(self.uploads, [('10', PNG)])
        self.assertTrue(self.images)
        self.assertEqual(result['cast'][0]['name'], 'Example Performer')
        self.assertEqual(len(result['profiles']), 1)
        profile = result['profiles'][0]
        self.assertTrue(profile['has_photo'])
        self.assertNotIn('photo', profile)
        self.assertEqual(self.service.cast_profile_image(profile['id']), PNG)
        self.assertEqual(self.service.get_task(self.task['id'])['status'], 'applied')
        again = self.save([dict(name=profile['name'], profile_id=profile['id'], revision=profile['revision'])])
        self.assertEqual(again['cast'][0]['thumb'], result['cast'][0]['thumb'])
        self.assertEqual(len(self.uploads), 1)  # Same item's checked upload receipt is reusable.

    def test_names_only_order_and_clear_all(self):
        result = self.save([{'name':'Second','role':'Guest'}, {'name':'First'}])
        self.assertEqual([x['name'] for x in result['cast']], ['Second','First'])
        self.assertEqual(self.save([])['cast'], [])

    def test_stale_task_or_profile_does_not_write(self):
        with self.assertRaises(ValueError):self.save([{'name':'Name'}], version=99)
        with self.assertRaisesRegex(ValueError, 'profile changed'):
            self.save([dict(name='Name', profile_id='a'*32, revision=1)])
        self.assertEqual(self.uploads, [])
        self.assertEqual(self.plex.writes, [])

    def test_external_cast_change_blocks_before_upload(self):
        self.plex.rows[0]['Role'] = [{'tag':'Someone else'}]
        with self.assertRaisesRegex(ValueError, 'metadata changed'):
            self.save([dict(name='Name',image=base64.b64encode(PNG).decode())])
        self.assertEqual(self.uploads, [])
        self.assertEqual(self.plex.writes, [])

    def test_mismatch_keeps_task_blocked_and_does_not_save_profile(self):
        self.plex.edit = lambda *args: self.plex.item('10')
        with self.assertRaisesRegex(ValueError, 'readback differs'):
            self.save([dict(name='Name', remember=True)])
        self.assertEqual(self.service.get_task(self.task['id'])['status'], 'blocked')
        self.assertEqual(self.service.cast_profiles(), [])

    def test_image_retrieval_failure_is_not_success(self):
        self.plex.cast_image = lambda *args: (_ for _ in ()).throw(ValueError('Picture unavailable'))
        with self.assertRaisesRegex(ValueError, 'Picture unavailable'):
            self.save([dict(name='Name',image=base64.b64encode(PNG).decode(),remember=True)])
        self.assertEqual(self.service.cast_profiles(), [])
        self.assertEqual(self.service.get_task(self.task['id'])['status'], 'blocked')

    def test_unreviewed_photo_url_and_duplicate_names_rejected(self):
        for rows in ([dict(name='Name', thumb='https://example.org/image.jpg')], [{'name':'Name'}, {'name':' name '}], [dict(name='Name', image='bad')]):
            with self.assertRaises(ValueError):self.save(rows)
        self.assertEqual(self.plex.writes, [])

    def test_existing_picture_can_be_remembered_and_explicitly_cleared(self):
        self.plex.rows[0]['Role'] = [{'tag':'Name','thumb':'https://example.org/image.jpg'}]
        self.service.read_metadata(self.task['id'])
        result = self.save([dict(name='Name',thumb='https://example.org/image.jpg',remember=True)])
        self.assertTrue(result['profiles'][0]['has_photo'])
        result = self.save([dict(name='Name',thumb=result['cast'][0]['thumb'],clear_photo=True)])
        self.assertEqual(result['cast'][0]['thumb'], '')

    def test_unmodified_broken_remote_picture_does_not_block_other_cast_edits(self):
        self.plex.rows[0]['Role'] = [{'tag':'Name','thumb':'https://example.org/image.jpg'}]
        self.service.read_metadata(self.task['id'])
        self.plex.cast_image = lambda *args: (_ for _ in ()).throw(ValueError('Broken existing picture'))
        result = self.save([dict(name='Name', role='Guest',thumb='https://example.org/image.jpg'),dict(name='New person')])
        self.assertEqual(result['cast'][0]['role'], 'Guest')

    def test_profile_update_is_versioned_and_does_not_rewrite_other_titles(self):
        result = self.save([dict(name='Name', image=base64.b64encode(PNG).decode(), remember=True)])
        profile = result['profiles'][0]
        writes = len(self.plex.writes)
        self.save([dict(name='New Name', profile_id=profile['id'], revision=profile['revision'], remember=True)])
        self.assertEqual(len(self.plex.writes), writes + 1)
        updated = self.service.cast_profiles()[0]
        self.assertEqual(updated['revision'], 2)
        self.assertEqual(updated['name'], 'New Name')
        with self.assertRaisesRegex(ValueError, 'profile changed'):
            self.save([dict(name='Stale',profile_id=profile['id'],revision=1)])

    def test_reuse_on_another_title_uploads_its_own_copy(self):
        result = self.save([dict(name='Name', image=base64.b64encode(PNG).decode(), remember=True)])
        profile = result['profiles'][0]
        with self.store.transaction():
            asset = self.store.get('assets', self.asset['id'])
            asset['rating_key'] = '11'
            self.store.put('assets', asset['id'], asset)
        self.save([dict(name='Name',profile_id=profile['id'],revision=1)])
        self.assertEqual([row[0] for row in self.uploads], ['10','11'])

    def test_cast_photo_verification_failure_can_retry_without_stale_metadata(self):
        checks = []
        def image(thumb):
            checks.append(thumb)
            if len(checks) == 1:raise ValueError('Temporary photo failure')
            return PNG
        self.plex.cast_image = image
        rows = [dict(name='Name',image=base64.b64encode(PNG).decode(),remember=True)]
        with self.assertRaisesRegex(ValueError, 'Temporary photo failure'):self.save(rows)
        self.assertEqual(self.save(rows)['cast'][0]['name'], 'Name')
        self.assertEqual(len(self.uploads), 1)


class CastAdapter(unittest.TestCase):
    def test_cast_edit_encodes_names_removals_roles_images_and_order(self):
        plex=Plex('http://host','token');calls=[]
        plex.request=lambda *args,**kwargs:calls.append((args,kwargs)) or {}
        plex.item=lambda key:{}
        plex.edit({'key':'1'}, {'ratingKey':'10','type':'movie','Role':[{'tag':'Old, Name'},{'tag':'Existing','tagKey':'guid'}]},
                  {'cast':[dict(name='Existing',role='Self',thumb='/library/metadata/10/thumb/1'),dict(name='New',role='',thumb='')]})
        params=calls[0][0][2]
        self.assertEqual(params['actor[].tag.tag-'], 'Old%2C%20Name')
        self.assertEqual(params['actor[0].tag.tagKey'],'guid')
        self.assertEqual(params['actor[0].tagging.text'],'Self')
        self.assertEqual(params['actor[1].tag.tag'],'New')
        self.assertEqual(params['actor.locked'],1)
        self.assertNotIn('cast.value',params)

    def test_cast_validation_does_not_accept_upload_fields_in_ordinary_metadata(self):
        for rows in ([{'name':''}], [dict(name='N',image=base64.b64encode(PNG).decode())]):
            with self.assertRaises(ValueError):Plex.validate_changes({'cast':rows})

    def upload_adapter(self, selected_changes=False, wrong_bytes=False):
        plex=Plex('http://host','token');calls=[];state={'uploaded':False,'restored':False}
        def request(path,method='GET',params=None,**kwargs):
            calls.append((path,method,params,kwargs))
            if method=='POST':state['uploaded']=True;return {}
            if method=='PUT':state['restored']=True;return {}
            rows=[dict(ratingKey='original',selected=not(state['uploaded'] and selected_changes and not state['restored']))]
            if state['uploaded']:rows.append(dict(ratingKey='upload://posters/abcd',selected=selected_changes and not state['restored']))
            return {'Metadata':rows}
        plex.request=request
        plex.binary_image=lambda path,params: b'\xff\xd8\xffwrong' if wrong_bytes else PNG
        return plex,calls

    def test_cast_upload_never_selects_profile_as_cover_and_verifies_bytes(self):
        plex,calls=self.upload_adapter()
        self.assertEqual(plex.cast_photo('10', PNG), '/library/metadata/10/file?url=upload%3A%2F%2Fposters%2Fabcd')
        self.assertEqual(len([x for x in calls if x[1]=='PUT']),0)
        plex,calls=self.upload_adapter(selected_changes=True)
        plex.cast_photo('10',PNG)
        self.assertEqual([x[2] for x in calls if x[1]=='PUT'],[{'url':'original'}])
        plex,_=self.upload_adapter(wrong_bytes=True)
        with self.assertRaisesRegex(ValueError,'bytes differ'):plex.cast_photo('10',PNG)

    def test_cast_proxy_contacts_only_plex_and_does_not_leak_token_in_url(self):
        calls=[]
        def transport(request,**kwargs):calls.append(request);return io.BytesIO(PNG)
        plex=Plex('http://plex-host','secret',transport)
        self.assertEqual(plex.cast_image('https://photos.example/person.jpg'),PNG)
        self.assertEqual(urlsplit(calls[0].full_url).netloc,'plex-host')
        self.assertNotIn('secret', calls[0].full_url)
        self.assertEqual(parse_qs(urlsplit(calls[0].full_url).query)['url'],['https://photos.example/person.jpg'])
        for thumb in ['file:///etc/passwd','//evil/image','https://u:p@evil/image','/library/parts/1/file','http://evil/\nimage']:
            with self.assertRaises(ValueError):plex.cast_image(thumb)
        with self.assertRaisesRegex(PlexError, 'redirects'):
            NoImageRedirect().redirect_request(None,None,302,'',{},'https://evil')

    def test_cast_metadata_order_is_significant(self):
        rows=[dict(name='A',role='',thumb=''),dict(name='B',role='',thumb='')]
        self.assertTrue(Service._same_metadata({'cast':rows},{'cast':copy.deepcopy(rows)}))
        self.assertFalse(Service._same_metadata({'cast':rows},{'cast':list(reversed(rows))}))
