"""Durable artwork plans using Curator's existing task store and publication gate."""
import base64
import copy
import hashlib
import uuid

from . import branding
from .plex import Plex
from .store import now

RATIOS = {'21:9', '16:9', '3:2', '5:4', '1:1', '4:5', '2:3', '9:16', '9:21'}


def resolve_style(preset, item, profile, kind, overrides):
    if kind not in Plex.ARTWORK:
        raise ValueError('Unsupported artwork destination')
    if not isinstance(overrides, dict) or set(overrides) - {'prompt', 'negative_prompt', 'model', 'ratio', 'resolution'}:
        raise ValueError('Invalid artwork settings')
    if any(not isinstance(v, str) or len(v) > 12000 for v in overrides.values()):
        raise ValueError('Invalid artwork setting value')
    # Destination defaults take precedence over style defaults; explicit overrides win.
    ratio = '2:3' if kind=='cover' and item.get('type')=='collection' else '1:1' if kind in {'square','logo'} else '16:9' if kind == 'background' or profile == 'home' else '2:3'
    result = dict(model=preset.get('model') or 'mango-v3', ratio=ratio,
                  resolution=preset.get('resolution') or '2K', negative_prompt=preset.get('negative_prompt',''))
    result.update(overrides)
    if result['ratio'] not in RATIOS or result['resolution'] not in {'1K','2K','3K','4K'}:
        raise ValueError('Choose a supported ratio and resolution')
    title, summary = item.get('title',''), item.get('summary','')
    result.setdefault('prompt', f"Create {kind} artwork for {title}. Context: {summary}\n{preset['details']}\nBackground: {preset['background']}. Typography: {preset['typography']}\nTarget ratio: {result['ratio']}; resolution: {result['resolution']}. Preserve reference proportions.")
    if not result['prompt'].strip():
        raise ValueError('A prompt is required')
    return dict(style=copy.deepcopy(preset), settings=result, context=dict(title=title, summary=summary), kind=kind)


class ArtworkWorkflows:
    def artwork_plan(self, asset_ids, kind, preset_id, overrides=None, images=None, originals=None, references=None):
        if not isinstance(asset_ids, list) or not asset_ids or len(asset_ids) > 100 or len(set(asset_ids)) != len(asset_ids):
            raise ValueError('Select between one and 100 distinct titles')
        references=references or []
        if not isinstance(references,list) or len(references)>10:raise ValueError('Choose at most ten local reference images')
        reference_photos=[self._folder_photo(encoded=image) for image in references]
        if any(not photo for photo in reference_photos):raise ValueError('Reference images cannot be empty')
        images = images or {}
        originals = originals or {}
        if not isinstance(originals,dict) or set(originals)-set(images):
            raise ValueError('Originals must belong to selected imported images')
        if not isinstance(images, dict) or set(images) - set(asset_ids):
            raise ValueError('Artwork may only be assigned to selected titles')
        presets = self.config().get('branding_presets', branding.DEFAULT_PRESETS)
        preset = next((p for p in presets if p['id'] == preset_id), None)
        if not preset:
            raise ValueError('Style changed; reload and select an available style')
        tasks, skipped, seen = [], [], set()
        # Resolve every title before committing any task, preserving batch atomicity.
        for aid in asset_ids:
            asset = self.asset({'asset':aid}, check=False)
            identity = (asset['library'], asset['rating_key'])
            if identity in seen:
                raise ValueError('Select each Plex title only once')
            seen.add(identity)
            client = self.checked_client(self.library(asset['library']))
            item = client.item(asset['rating_key'])
            if str(item.get('ratingKey')) != asset['rating_key']:
                raise ValueError('Plex title identity changed; rescan before planning')
            plan = resolve_style(preset, item, self.library(asset['library'])['profile'], kind, overrides or {})
            plan.update(assets=[aid], rating_key=asset['rating_key'], reference_photos=reference_photos, target=dict(guid=item.get('guid'),paths=sorted(part.get('file','') for media in item.get('Media',[]) for part in media.get('Part',[]))))
            task_kind, status = 'mage_generation', 'recommendation'
            if aid in images:
                candidate = self._folder_photo(encoded=images[aid])
                if not candidate:
                    raise ValueError('Choose an image for each imported title')
                original = self._folder_photo(encoded=base64.b64encode(client.image(asset['rating_key'],kind)).decode()) if Plex.artwork_path(item,kind) else None
                if candidate == original:
                    skipped.append(aid);continue
                plan.update(candidate=candidate, original=original, source_image=self._folder_photo(encoded=originals[aid]) if aid in originals else candidate)
                task_kind, status = 'artwork', 'awaiting_review'
            tasks.append(dict(id=uuid.uuid4().hex, asset=aid, library=asset['library'], title=item.get('title',asset['title']),
                              kind=task_kind, status=status, version=1, reason='Review artwork for this Plex title',
                              plan=plan, evidence={'destination':asset['rating_key'], 'outbound_files':reference_photos, 'paid_submission_enabled':False},
                              created=now(), updated=now()))
        with self.store.transaction():
            for task in tasks:
                self.store.put('tasks',task['id'],task)
                self.store.event(task['id'],dict(action='saved immutable artwork plan'))
        return dict(tasks=tasks, skipped=skipped)

    def save_artwork_style(self, key, name):
        task = self.get_task(key)
        if task['kind'] not in {'artwork','mage_generation'}:
            raise ValueError('Choose an artwork plan')
        if not isinstance(name,str) or not name.strip() or len(name)>500:
            raise ValueError('Name the new style')
        settings = task['plan']['settings']
        style = dict(task['plan']['style'], id='style-'+uuid.uuid4().hex[:16], name=name.strip(),
                     details=settings['prompt'], model=settings['model'], ratio=settings['ratio'],
                     resolution=settings['resolution'], negative_prompt=settings['negative_prompt'])
        self.save_config({'branding_presets':self.config().get('branding_presets',branding.DEFAULT_PRESETS)+[style]})
        return style

    def publish_artwork(self, task, asset):
        plan = task['plan'];kind = plan['kind']
        if plan['rating_key'] != asset['rating_key']:
            raise ValueError('Artwork destination changed; create a fresh review')
        image = self.folder_image(plan['candidate'])
        client = self.checked_client(self.library(asset['library']))
        item = client.item(asset['rating_key'])
        target=plan.get('target',{})
        paths=sorted(part.get('file','') for media in item.get('Media',[]) for part in media.get('Part',[]))
        if str(item.get('ratingKey'))!=plan['rating_key'] or target.get('guid')!=item.get('guid') or target.get('paths',paths)!=paths:
            raise ValueError('Plex destination identity changed after artwork review')
        current = hashlib.sha256(client.image(asset['rating_key'],kind)).hexdigest() if Plex.artwork_path(item,kind) else None
        if current == plan['candidate']:
            self._save(task,status='applied',result={'verified':True,'no_changes_needed':True});return
        if current != plan['original']:
            raise ValueError('Plex artwork changed after preview; retain this draft and create a fresh review')
        result = client.artwork(asset['rating_key'], image, kind)
        self._save(task,result={'uploaded':True},progress={'phase':'Verifying selected Plex artwork'})
        if not Plex.artwork_path(result,kind) or hashlib.sha256(client.image(asset['rating_key'],kind)).hexdigest() != plan['candidate']:
            raise ValueError('Plex image readback differs; candidate and original are retained for recovery')
        self._cache_metadata(asset,result)
        self._save(task,status='applied',result={'verified':True},error=None)

    def save_portrait(self, profile_id, revision, encoded):
        from . import cast
        image = cast.photo_bytes(encoded)
        photo = self._folder_photo(encoded=encoded)
        with self.store.transaction():
            profiles = self.store.get('settings','cast_profiles',{})
            profile = profiles.get(profile_id)
            if not profile or profile['revision'] != revision:
                raise ValueError('Saved person changed; reload before replacing the portrait')
            # Keep the same identity; do not touch credits or publish anything.
            directory = self.store.root/'cast';directory.mkdir(mode=0o700,exist_ok=True)
            target = directory/photo
            if target.is_symlink():raise ValueError('Invalid portrait storage')
            if not target.exists():
                import os
                fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as out:out.write(image);out.flush();os.fsync(out.fileno())
            profile=dict(profile,photo=photo,revision=revision+1)
            profiles[profile_id]=profile;self.store.put('settings','cast_profiles',profiles)
        return dict(profile_id=profile_id,revision=revision+1,photo=photo)

    def portrait_plan(self, profile_id, revision, targets):
        from . import cast
        profiles=self.store.get('settings','cast_profiles',{})
        profile=profiles.get(profile_id)
        if not profile or profile['revision']!=revision or not profile.get('photo'):
            raise ValueError('Saved portrait changed; reload and preview again')
        if not isinstance(targets,list) or not 1<=len(targets)<=100:
            raise ValueError('Choose explicit portrait targets')
        encoded=base64.b64encode(self.cast_profile_image(profile_id)).decode()
        photo=self._folder_photo(encoded=encoded);tasks=[];seen=set()
        for target in targets:
            if not isinstance(target,dict) or set(target)!={'asset','index'} or type(target['index']) is not int:
                raise ValueError('Select an exact credited person in each target')
            asset=self.asset({'asset':target['asset']},check=False)
            identity=(asset['library'],asset['rating_key'])
            if identity in seen:raise ValueError('Select each target title once')
            seen.add(identity);client=self.checked_client(self.library(asset['library']))
            item=client.item(asset['rating_key']);rows=cast.fields(item);index=target['index']
            if not 0<=index<len(rows) or rows[index]['name'].casefold()!=profile['name'].casefold():
                raise ValueError('Target credit identity changed; preview again')
            original=self._folder_photo(encoded=base64.b64encode(client.cast_image(rows[index]['thumb'])).decode()) if rows[index]['thumb'] else None
            if original==photo:continue
            tasks.append(dict(id=uuid.uuid4().hex,asset=asset['id'],library=asset['library'],title=asset['title'],kind='portrait',
                status='awaiting_review',version=1,reason='Review portrait for the explicitly selected credit',created=now(),updated=now(),
                plan=dict(assets=[asset['id']],rating_key=asset['rating_key'],index=index,before=rows,original=original,candidate=photo,
                          profile_id=profile_id,profile_revision=revision,name=profile['name'])))
        with self.store.transaction():
            for task in tasks:self.store.put('tasks',task['id'],task)
        return {'tasks':tasks}

    def publish_portrait(self, task, asset):
        client=self.checked_client(self.library(asset['library']))
        if isinstance(client,Plex):
            raise ValueError('Native Plex portrait transport is unverified. Download the retained portrait and apply it manually; no Plex credit was changed.')
        from . import cast
        plan=task['plan'];item=client.item(asset['rating_key']);rows=cast.fields(item)
        if asset['rating_key']!=plan['rating_key'] or rows!=plan['before']:
            raise ValueError('Cast changed after review; create a fresh portrait preview')
        image=self.folder_image(plan['candidate'])
        thumb=client.cast_photo(asset['rating_key'],image)
        self._save(task,result={'uploaded':True})
        rows=copy.deepcopy(rows);rows[plan['index']]['thumb']=thumb
        self._write_metadata(client,asset,{'cast':rows},{'cast':plan['before']})
        observed=cast.fields(client.item(asset['rating_key']))
        if observed!=rows or hashlib.sha256(client.cast_image(observed[plan['index']]['thumb'])).hexdigest()!=plan['candidate']:
            raise ValueError('Portrait image readback differs; original and candidate retained')
        self._save(task,status='applied',result={'verified':True},error=None)

    def mage_quote(self, targets):
        from .mage import Mage
        provider=Mage(self.store.root);rows=[]
        if not isinstance(targets,list) or not 1<=len(targets)<=20 or len({t['id'] for t in targets})!=len(targets):
            raise ValueError('Choose between one and twenty distinct generation plans')
        for target in targets:
            task=self.get_task(target['id'])
            if task['kind']!='mage_generation' or task['version']!=target['version'] or task['status'] not in {'recommendation','cancelled'} or task.get('provider'):
                raise ValueError('Generation plan changed or has already been submitted')
            quote=provider.quote(task['plan']['settings'],len(task['plan'].get('reference_photos',[])))
            rows.append(dict(id=task['id'],version=task['version'],quote=quote,title=task['title']))
        receipt=dict(id=uuid.uuid4().hex,rows=rows,total=sum(r['quote']['gems'] for r in rows),count=len(rows),created=__import__('time').time(),credential=provider.credential_identity())
        with self.store.transaction():self.store.put('settings','mage-quote:'+receipt['id'],receipt)
        return {k:v for k,v in receipt.items() if k!='credential'}

    def authorize_mage(self, quote_id, consent):
        from .mage import Mage
        import time
        if consent is not True:raise ValueError('Explicit cost and outbound prompt approval required')
        provider=Mage(self.store.root)
        with self.store.transaction():
            receipt=self.store.get('settings','mage-quote:'+quote_id)
            if not receipt or receipt.get('used') or time.time()-receipt['created']>120 or receipt['credential']!=provider.credential_identity():
                raise ValueError('Quote expired, used or credential changed; request a fresh quote')
            for row in receipt['rows']:
                task=self.get_task(row['id'])
                if task['version']!=row['version'] or task['status'] not in {'recommendation','cancelled'} or task.get('provider'):
                    raise ValueError('Plan changed after quotation')
            for row in receipt['rows']:
                task=self.get_task(row['id'])
                task.update(status='queued',approval=task['version'],provider=dict(idempotency_key=uuid.uuid4().hex,body=row['quote']['body'],estimate=row['quote']['gems'],credential=receipt['credential']))
                self.store.put('tasks',task['id'],task)
                self.store.event(task['id'],dict(action='approved Mage prompt and estimated Gems',gems=row['quote']['gems']))
            receipt['used']=True;self.store.put('settings','mage-quote:'+quote_id,receipt)
        return {'queued':receipt['count'],'estimated_gems':receipt['total']}

    def execute_mage(self, task, provider=None, wait=None):
        from .mage import Mage
        import time
        provider=provider or Mage(self.store.root);wait=wait or time.sleep
        receipt=task.get('provider')
        if not receipt or receipt['credential']!=provider.credential_identity():
            raise ValueError('Mage credential changed or consent is missing; no submission made')
        asset=self.asset(task,check=False)
        if asset['library']!=task['library'] or asset['rating_key']!=task['plan']['rating_key']:
            raise ValueError('Generation destination changed; no new request submitted')
        if not receipt.get('request_id') and not receipt.get('attempted'):
            fresh=provider.quote(task['plan']['settings'],len(task['plan'].get('reference_photos',[])))
            if fresh['gems']>receipt['estimate'] or fresh['body']!=receipt['body']:
                raise ValueError('Mage price or supported settings changed; obtain fresh approval')
            # Persist the uncertain-outcome boundary before the first paid request.
            receipt['attempted']=True;self._save(task,provider=receipt)
        body=copy.deepcopy(receipt['body'])
        references=[]
        for photo in task['plan'].get('reference_photos',[]):
            image=self.folder_image(photo);mime='image/png' if image.startswith(b'\x89PNG') else 'image/jpeg'
            references.append('data:'+mime+';base64,'+base64.b64encode(image).decode())
        if references:body['image']=references[0]
        if len(references)>1:body['additional_images']=references[1:]
        request=provider.status(receipt['request_id']) if receipt.get('request_id') else provider.submit(body,receipt['idempotency_key'])
        for attempt in range(30):
            import re
            request_id=request.get('request_id')
            if not isinstance(request_id,str) or not re.fullmatch(r'[a-f0-9-]{36}',request_id):raise ValueError('Mage returned an invalid request identity; retain this idempotency key for recovery')
            if receipt.get('request_id') and receipt['request_id']!=request_id:raise ValueError('Mage request identity differs')
            receipt.update(request_id=request_id,status=request.get('status'),billing=request.get('billing',{}))
            self._save(task,provider=receipt,progress={'phase':'Mage '+str(request.get('status'))})
            if request.get('status')=='completed':
                image=provider.download((request.get('result') or {}).get('url',''))
                photo=self._folder_photo(encoded=base64.b64encode(image).decode())
                asset=self.asset(task,check=False);client=self.checked_client(self.library(asset['library']));item=client.item(asset['rating_key']);kind=task['plan']['kind']
                original=self._folder_photo(encoded=base64.b64encode(client.image(asset['rating_key'],kind)).decode()) if Plex.artwork_path(item,kind) else None
                task['plan'].update(candidate=photo,source_image=photo,original=original)
                # Same durable task enters artwork review. Generation never publishes.
                self._save(task,kind='artwork',status='awaiting_review',result={'generated':True,'billing':receipt['billing']},error=None);return
            if request.get('status') in {'failed','cancelled'}:
                self._save(task,status='cancelled' if request['status']=='cancelled' else 'failed',error='Mage '+request['status']+'; inspect billed/refunded Gems',result={'billing':receipt['billing']});return
            if request.get('status') not in {'queued','in_progress'}:raise ValueError('Unknown Mage state; check request before retrying')
            if task['id'] in self.cancels or self.get_task(task['id']).get('mage_cancel_requested'):
                request=provider.cancel(request_id);self.cancels.discard(task['id']);continue
            wait(min(2*1.5**attempt,15));request=provider.status(request_id)
        raise ValueError('Mage is still running; request retained. Explicit resume polls without resubmitting.')

    def resume_mage(self, key, version):
        with self.store.transaction():
            task=self.get_task(key)
            if task['kind']!='mage_generation' or task['version']!=version or task['status']!='blocked' or not task.get('provider'):
                raise ValueError('No interrupted Mage request to resume')
            # If submission lost its response, the same immutable body/key is replayed.
            task.update(status='queued',approval=version,error=None);self.store.put('tasks',key,task)
        return task

    def remember_portrait_identity(self, asset_id, index):
        from . import cast
        if type(index) is not int:raise ValueError('Select a credited person')
        asset=self.asset({'asset':asset_id},check=False)
        client=self.checked_client(self.library(asset['library']));item=client.item(asset['rating_key']);rows=cast.fields(item)
        if not 0<=index<len(rows):raise ValueError('Credit no longer exists')
        row=rows[index]
        if not row['name'].strip():raise ValueError('Credit needs a name in Metadata Manager first')
        photo=None
        if row['thumb']:
            image=client.cast_image(row['thumb']);photo=self._folder_photo(encoded=base64.b64encode(image).decode())
        with self.store.transaction():
            profiles=self.store.get('settings','cast_profiles',{})
            if any(p['name'].casefold()==row['name'].casefold() for p in profiles.values()):
                raise ValueError('A saved person already has this name; select the existing profile or disambiguate the credit first')
            pid=uuid.uuid4().hex
            profiles[pid]=dict(name=row['name'],photo=None,revision=1,identity=dict(library=asset['library'],rating_key=asset['rating_key'],credit_index=index))
            self.store.put('settings','cast_profiles',profiles)
        if photo:return self.save_portrait(pid,1,base64.b64encode(self.folder_image(photo)).decode())
        return dict(profile_id=pid,revision=1)

    def artwork_candidates(self, key, version, count):
        if type(count) is not int or not 1<=count<=4:
            raise ValueError('Choose one through four candidates')
        with self.store.transaction():
            source=self.get_task(key)
            if source['kind']!='mage_generation' or source['status']!='recommendation' or source['version']!=version or source.get('provider'):
                raise ValueError('Create candidates from an unsubmitted generation plan')
            group=uuid.uuid4().hex;tasks=[]
            for index in range(count):
                task=copy.deepcopy(source)
                task.update(id=source['id'] if index==0 else uuid.uuid4().hex,version=version+1 if index==0 else 1,created=now(),updated=now())
                task['evidence'].update(candidate_group=group,candidate_index=index+1,candidate_count=count)
                self.store.put('tasks',task['id'],task);tasks.append(task)
        return {'tasks':tasks,'count':count}
