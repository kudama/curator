"""Folder-scoped, reviewed metadata plans. Private defaults never publish themselves."""
import base64
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path, PurePosixPath

from . import branding, cast, tools
from .paths import map_path
from .plex import Plex
from .store import now


def key(*values):
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:24]


def combine(before, proposed, mode, field):
    if mode == 'fill':
        return before or proposed
    if mode == 'merge':
        if field in {'genre', 'collection', 'label'}:
            result = list(before)
            for value in proposed:
                if value.casefold() not in {x.casefold() for x in result}:result.append(value)
            return result
        if field == 'cast':
            result = [dict(row) for row in before]
            for row in proposed:
                existing = next((r for r in result if r['name'].casefold() == row['name'].casefold()), None)
                if existing is None:result.append(row)
                else:
                    if not existing.get('role'):existing['role'] = row.get('role', '')
                    if not existing.get('thumb') and not existing.get('photo') and row.get('photo'):existing['photo'] = row['photo']
            return result
        return before or proposed
    return proposed


class FolderWorkflows:
    def folder_nodes(self):
        nodes = {}
        libraries = {row['id']:row for row in self.store.all('libraries')}
        roots = {}
        for library in libraries.values():
            declared = [PurePosixPath(row['path']) for row in library.get('locations',[]) if isinstance(row,dict) and isinstance(row.get('path'),str) and row['path'].startswith('/') and '..' not in PurePosixPath(row['path']).parts]
            roots[library['id']] = declared or [PurePosixPath(m['plex_root']) for m in library['mappings']]
            for root in roots[library['id']]:
                fid = key(library['id'],str(root))
                mapped = any(root.is_relative_to(m['plex_root']) for m in library['mappings'])
                nodes.setdefault(fid,dict(id=fid,library=library['id'],path=str(root),name=root.name or str(root),parent=None,count=0,direct_count=0,mapped=mapped))
        for asset in self.store.all('assets'):
            if asset.get('present') is False:continue
            library = libraries.get(asset['library'])
            if not library:continue
            path = PurePosixPath(asset['plex_path']).parent
            matches = [root for root in roots[library['id']] if path.is_relative_to(root)]
            root = max(matches,key=lambda p:len(p.parts)) if matches else path
            for folder in [path, *path.parents]:
                if not folder.is_relative_to(root):break
                fid = key(library['id'],str(folder))
                mapped = any(folder.is_relative_to(m['plex_root']) for m in library['mappings'])
                row = nodes.setdefault(fid,dict(id=fid,library=library['id'],path=str(folder),name=folder.name or str(folder),
                    parent=key(library['id'],str(folder.parent)) if folder != root else None,count=0,direct_count=0,mapped=mapped))
                row['count'] += 1
                if folder == path:row['direct_count'] += 1
        return sorted(nodes.values(),key=lambda row:(row['library'],row['path']))

    def folder_node(self, fid):
        row = next((r for r in self.folder_nodes() if r['id'] == fid), None)
        if not row:raise ValueError('Folder is no longer in the scanned library')
        return row

    def folder_members(self, folder, recursive):
        parent = PurePosixPath(folder['path'])
        return [a for a in self.store.all('assets') if a['library'] == folder['library'] and a.get('present') is not False
                and (PurePosixPath(a['plex_path']).parent == parent or recursive and PurePosixPath(a['plex_path']).parent.is_relative_to(parent))]

    def folder_read(self, fid):
        folder = self.folder_node(fid)
        defaults = self.store.get('settings', 'folder:' + fid)
        inherited = []
        for row in self.store.all('settings'):
            if isinstance(row,dict) and row.get('record') == 'folder_defaults' and row['library'] == folder['library'] and row['recursive'] and row['folder'] != folder['path'] and PurePosixPath(folder['path']).is_relative_to(row['folder']):
                inherited.append(row)
        library = self.library(folder['library'])
        local = map_path(folder['path'] + '/.curator-folder',library['mappings'],False).parent if folder['mapped'] else None
        brand = branding.read(local) if local and local.is_dir() else None
        return dict(folder=folder, defaults=defaults, branding=brand, branding_revision=branding.revision(brand) if brand else None, inherited=sorted(inherited, key=lambda r:len(PurePosixPath(r['folder']).parts), reverse=True))

    def folder_image(self, photo):
        if not isinstance(photo, str) or not re.fullmatch('[a-f0-9]{64}', photo):raise ValueError('Invalid folder image')
        target = self.store.root / 'folder-images' / photo
        if target.is_symlink():raise ValueError('Invalid folder image')
        data = tools.image_bytes(target)
        if hashlib.sha256(data).hexdigest() != photo:raise ValueError('Folder image changed; choose it again')
        return data

    def _folder_photo(self, encoded=None, photo=None):
        if encoded:
            data = cast.photo_bytes(encoded)
            photo = hashlib.sha256(data).hexdigest()
            directory = self.store.root / 'folder-images';directory.mkdir(mode=0o700, exist_ok=True)
            target = directory / photo
            if target.is_symlink():raise ValueError('Invalid folder image')
            if not target.exists():
                with target.open('xb') as out:os.chmod(target, 0o600);out.write(data)
        if photo:self.folder_image(photo)
        return photo

    def folder_settings(self, data):
        if not isinstance(data, dict) or set(data) - {'fields','artwork','mode','recursive','branding','portrait'}:raise ValueError('Invalid folder settings')
        mode = data.get('mode', 'fill')
        if not isinstance(mode,str) or mode not in {'fill','merge','replace'} or type(data.get('recursive', False)) is not bool:raise ValueError('Choose a folder scope and metadata mode')
        if not isinstance(data.get('fields',{}),dict):raise ValueError('Invalid folder metadata fields')
        fields = dict(data.get('fields', {}));artwork = data.get('artwork', {})
        if fields:
            standard = {k:v for k,v in fields.items() if k != 'cast'}
            if standard:Plex.validate_changes(standard)
        if 'cast' in fields:
            profiles = self.store.get('settings', 'cast_profiles', {})
            rows = []
            if not isinstance(fields['cast'], list) or len(fields['cast'])>100:raise ValueError('Choose at most 100 cast members')
            for source in fields['cast']:
                if not isinstance(source,dict):raise ValueError('Invalid folder cast member')
                row = dict(source);photo = row.pop('photo', None)
                cast.validate_rows([row])
                if row.get('thumb'):raise ValueError('Use a saved cast profile or upload a folder profile picture')
                profile = profiles.get(row.get('profile_id'))
                if row.get('profile_id') and (not profile or profile['revision'] != row.get('revision')):raise ValueError('Saved cast profile changed; reopen the folder editor')
                if row.get('clear_photo'):photo = None
                elif row.get('image'):photo = self._folder_photo(encoded=row['image'])
                elif photo:self.folder_image(photo)
                elif profile and profile.get('photo'):
                    photo = self._folder_photo(encoded=base64.b64encode(self.cast_profile_image(row['profile_id'])).decode())
                rows.append(dict(name=row['name'].strip(), role=row.get('role',''), **({'photo':photo} if photo else {})))
            cast.validate_rows([{k:v for k,v in row.items() if k != 'photo'} for row in rows])
            fields['cast'] = rows
        if not isinstance(artwork, dict) or set(artwork) - {'cover','background','logo','square'}:raise ValueError('Choose shared cover, background, logo or square artwork')
        images = {}
        for kind, value in artwork.items():
            if not isinstance(value, dict) or set(value) - {'image','photo'}:raise ValueError('Invalid shared artwork')
            photo = self._folder_photo(value.get('image'), value.get('photo'))
            if photo:images[kind] = {'photo':photo}
        brand = data.get('branding')
        if brand is not None:
            branding.validate(brand)
            if brand.get('logo'):raise ValueError('Manage creator logo files in the file editor')
            if brand.get('preset_id') not in {p['id'] for p in self.config().get('branding_presets', branding.DEFAULT_PRESETS)}:raise ValueError('Choose an available branding preset')
        settings = dict(fields=fields, artwork=images, mode=mode, recursive=data.get('recursive',False), branding=brand)
        portrait = data.get('portrait')
        if portrait is not None:
            if 'cast' in fields or not isinstance(portrait, dict) or set(portrait) != {'profile_id','revision'}:
                raise ValueError('Choose one saved portrait separately from shared cast replacement')
            profile = self.store.get('settings', 'cast_profiles', {}).get(portrait['profile_id'])
            if not profile or profile['revision'] != portrait['revision'] or not profile.get('photo'):
                raise ValueError('Saved portrait changed or has no picture; reopen the folder editor')
            photo = self._folder_photo(encoded=base64.b64encode(self.cast_profile_image(portrait['profile_id'])).decode())
            settings['portrait'] = dict(name=profile['name'], photo=photo, profile_id=portrait['profile_id'], revision=portrait['revision'])
        return settings

    def save_folder_defaults(self, fid, data, revision, branding_revision=None):
        folder = self.folder_node(fid);settings = self.folder_settings(data)
        if settings.get('portrait'):raise ValueError('Portrait application requires a fresh preview; it cannot become an automatic folder default')
        library = self.library(folder['library'])
        local = map_path(folder['path'] + '/.curator-folder', library['mappings'], False).parent
        if not local.is_dir():raise ValueError('Mapped folder is unavailable')
        with self.lock:
            old = self.store.get('settings', 'folder:' + fid)
            if (old or {}).get('revision') != revision:raise ValueError('Folder defaults changed; reopen before saving')
            if settings['branding'] is not None:
                previous = branding.read(local)
                if (branding.revision(previous) if previous else None) != branding_revision:raise ValueError('Folder branding changed; reopen before saving')
                branding.write(local, {**settings['branding'], 'logo':(previous or {}).get('logo','')}, branding_revision)
            value = dict(record='folder_defaults', library=folder['library'], folder=folder['path'], revision=uuid.uuid4().hex, updated=now(), **settings)
            with self.store.transaction():self.store.put('settings','folder:' + fid,value)
        return self.folder_read(fid)

    def _folder_changes(self, item, settings, client=None):
        before = self.metadata_fields(item);changes = {}
        fields = dict(settings['fields'])
        portrait = settings.get('portrait')
        if portrait:
            # Explicitly match the named saved identity; preserve every other credit.
            rows = []
            matched = False
            for original in before['cast']:
                row = dict(original)
                if row['name'].strip().casefold() == portrait['name'].strip().casefold():
                    row.pop('thumb', None);row['photo'] = portrait['photo'];matched = True
                rows.append(row)
            if matched:fields['cast'] = rows
        for field, proposed in fields.items():
            result = proposed if portrait and field == 'cast' else combine(before[field], proposed, settings['mode'], field)
            if field=='cast' and client:
                normalized=[]
                for row in result:
                    row=dict(row)
                    existing=next((r for r in before['cast'] if r['name']==row['name'] and r.get('role','')==row.get('role','')),None)
                    if row.get('photo') and existing and existing.get('thumb') and hashlib.sha256(client.cast_image(existing['thumb'])).hexdigest()==row['photo']:
                        row.pop('photo');row['thumb']=existing['thumb']
                    if not row.get('photo'):row.setdefault('thumb','')
                    normalized.append(row)
                result=normalized
            if not self._same_metadata(before,{field:result}):changes[field] = result
        artwork = {kind:value for kind,value in settings['artwork'].items() if settings['mode'] == 'replace' or not Plex.artwork_path(item,kind)}
        return before, changes, artwork

    def folder_preview(self, fid, data):
        folder = self.folder_node(fid);settings = self.folder_settings(data)
        members = self.folder_members(folder, settings['recursive'])
        if not members:raise ValueError('No scanned files in this folder scope')
        client = self.checked_client(self.library(folder['library']));rows = [];seen = set()
        for member in members:
            identity = member['rating_key']
            if identity in seen:continue
            seen.add(identity)
            try:
                asset = self.asset({'asset':member['id']})
                if asset.get('blocked') or asset.get('availability_error'):raise ValueError('Scan this file to resolve its availability before applying folder defaults')
                item = client.item(identity)
                if str(item.get('ratingKey')) != identity or asset['plex_path'] not in {part.get('file') for media in item.get('Media',[]) for part in media.get('Part',[])}:raise ValueError('Plex source path changed; rescan and preview again')
                before, changes, artwork = self._folder_changes(item, settings, client)
                hashes = {kind:hashlib.sha256(client.image(identity,kind)).hexdigest() if Plex.artwork_path(item,kind) else None for kind in artwork}
                artwork = {kind:value for kind,value in artwork.items() if hashes[kind] != value['photo']}
                hashes = {kind:hashes[kind] for kind in artwork}
                self.resolve_satisfied_folder_work(asset,item,fid,not changes and not artwork)
                for pending in self.store.all('tasks'):
                    if pending['library']==folder['library'] and pending['status'] in {'queued','running','publishing','awaiting_review'} and (asset['id'] in pending['plan'].get('assets',[pending['asset']]) or self.store.get('assets',pending['asset'],{}).get('rating_key')==identity):raise ValueError('This title has active work; finish or cancel it first')
                self._cache_metadata(asset,item)
                rows.append(dict(asset=asset['id'], title=item.get('title',asset['title']), filename=Path(asset['plex_path']).name,
                    source=asset['fingerprint'], before=before, changes=changes, artwork=artwork, art_before=hashes,
                    rating_key=identity, plex_path=asset['plex_path']))
            except (ValueError, OSError) as error:
                rows.append(dict(asset=member['id'], filename=Path(member['plex_path']).name, error=str(error)[:300]))
        preview = dict(id=uuid.uuid4().hex, folder=fid, library=folder['library'], created=time.time(), settings=settings,
                       members=sorted(a['id'] for a in members), rows=rows)
        with self.store.transaction():
            for row in self.store.all('settings'):
                if isinstance(row,dict) and row.get('record') == 'folder_preview' and time.time()-row['created']>3600:
                    self.store.db.execute('DELETE FROM settings WHERE id=?',('folder-preview:' + row['id'],))
            self.store.put('settings','folder-preview:' + preview['id'],dict(record='folder_preview',**preview))
        return preview

    def queue_folder_preview(self, preview_id):
        with self.lock:
            preview = self.store.get('settings','folder-preview:' + preview_id)
            if not preview or time.time()-preview['created']>3600:raise ValueError('Folder preview expired; preview again')
            if preview.get('queued'):raise ValueError('This preview is already queued')
            folder = self.folder_node(preview['folder'])
            if sorted(a['id'] for a in self.folder_members(folder,preview['settings']['recursive'])) != preview['members']:raise ValueError('Folder membership changed; preview again')
            rows = [row for row in preview['rows'] if not row.get('error') and (row['changes'] or row['artwork'])]
            if not rows:raise ValueError('No applicable changes in this preview')
            pending = self.store.all('tasks')
            for row in rows:
                asset = self.asset({'asset':row['asset']})
                if asset['fingerprint'] != row['source'] or asset['plex_path'] != row['plex_path'] or asset['rating_key'] != row['rating_key']:raise ValueError('Source changed; preview again')
                for task in pending:
                    ids = task['plan'].get('assets',[task['asset']])
                    if task['status'] in {'queued','running','publishing','awaiting_review'} and (asset['id'] in ids or self.store.get('assets',task['asset'],{}).get('rating_key') == asset['rating_key'] and task['library'] == asset['library']):raise ValueError('A selected title has active work; finish or cancel it before queueing folder changes')
            with self.store.transaction():
                tasks = []
                for row in rows:
                    tid = key(preview_id,row['rating_key'])
                    task = dict(id=tid,asset=row['asset'],library=preview['library'],title=row['title'],kind='folder_metadata',
                        reason='Apply reviewed folder metadata',evidence={'folder':folder['path']},plan=dict(folder=folder['id'],settings_signature=key(preview['settings']),changes=row['changes'],artwork=row['artwork'],art_before=row['art_before']),
                        metadata_before=row['before'],source=row['source'],status='queued',approval=1,version=1,created=now(),updated=now())
                    self.store.put('tasks',tid,task);self.store.event(tid,dict(action='approved folder preview',preview=preview_id));tasks.append(tid)
                    for old in pending:
                        if old['kind']=='folder_metadata' and old['asset']==row['asset'] and old['status'] in {'recommendation','blocked','failed','cancelled'}:
                            old.update(status='resolved',updated=now());self.store.put('tasks',old['id'],old)
                preview['queued'] = True;self.store.put('settings','folder-preview:' + preview_id,preview)
            return {'queued':len(tasks),'tasks':tasks}

    def resolve_satisfied_folder_work(self, asset, item, fid, folder_satisfied=False):
        observed=self.metadata_fields(item)
        with self.store.transaction():
            siblings={a['id'] for a in self.store.all('assets') if a['library']==asset['library'] and a['rating_key']==asset['rating_key']}
            for task in self.store.all('tasks'):
                if task['asset'] not in siblings or task.get('deleted') or task['status'] not in {'recommendation','awaiting_review','blocked'}:continue
                satisfied=False
                if task['kind']=='folder_metadata':satisfied=folder_satisfied and task['plan'].get('folder')==fid
                elif task['kind'] in {'metadata','home'}:
                    changes=task['plan'].get('changes')
                    if not changes and task['kind']=='home' and task.get('result'):
                        result=task['result']
                        if all(field in result for field in ('title','summary','themes')):
                            changes=dict(title=result['title'],summary=result['summary'],collection=sorted(set(observed['collection']+result['themes'])))
                    if changes:satisfied=self._same_metadata(observed,changes)
                    elif task['kind']=='metadata':satisfied=bool(item.get('summary') and Plex.artwork_path(item,'cover'))
                if satisfied:
                    task.update(status='resolved',version=task['version']+1,updated=now(),error=None,result={**(task.get('result') or {}),'no_changes_needed':True})
                    task.pop('approval',None);self.store.put('tasks',task['id'],task)
                    self.store.event(task['id'],dict(action='resolved already satisfied metadata',folder=fid))

    def execute_folder_metadata(self, task, asset):
        client = self.checked_client(self.library(asset['library']));item = client.item(asset['rating_key']);plan = task['plan']
        _, remaining, artwork=self._folder_changes(item,dict(fields=plan['changes'],artwork=plan['artwork'],mode='replace'),client)
        artwork={kind:value for kind,value in artwork.items() if not Plex.artwork_path(item,kind) or hashlib.sha256(client.image(asset['rating_key'],kind)).hexdigest()!=value['photo']}
        if not remaining and not artwork:
            self._cache_metadata(asset,item)
            self.resolve_satisfied_folder_work(asset,item,plan['folder'],True)
            self._save(task,status='resolved',result={'verified':True,'no_changes_needed':True})
            return
        if not self._same_metadata(self.metadata_fields(item),task['metadata_before']):raise ValueError('Plex metadata changed; make a fresh folder preview')
        for kind, expected in plan['art_before'].items():
            observed = hashlib.sha256(client.image(asset['rating_key'],kind)).hexdigest() if Plex.artwork_path(item,kind) else None
            if observed != expected:raise ValueError('Plex artwork changed; make a fresh folder preview')
        # Validate every private blob before the first external write.
        for value in plan['artwork'].values():self.folder_image(value['photo'])
        for row in plan['changes'].get('cast',[]):
            if row.get('photo'):self.folder_image(row['photo'])
        changes = {k:v for k,v in plan['changes'].items() if k != 'cast'}
        if 'cast' in plan['changes']:
            rows = []
            for row in plan['changes']['cast']:
                thumb = row.get('thumb','')
                if row.get('photo'):thumb = client.cast_photo(asset['rating_key'],self.folder_image(row['photo']))
                rows.append(dict(name=row['name'],role=row.get('role',''),thumb=thumb))
            changes['cast'] = rows
        if changes:
            self._write_metadata(client,asset,changes,task['metadata_before'])
            self._save(task,result={'metadata_verified':True})
        for kind, value in plan['artwork'].items():
            if task['id'] in self.cancels:raise ValueError('Folder apply cancelled; inspect completed fields before a fresh preview')
            result = client.artwork(asset['rating_key'],self.folder_image(value['photo']),kind)
            if not Plex.artwork_path(result,kind):raise ValueError('Plex did not select shared artwork')
            if hashlib.sha256(client.image(asset['rating_key'],kind)).hexdigest() != value['photo']:raise ValueError('Plex artwork readback differs; inspect before retrying')
            self._cache_metadata(asset,result)
            self._save(task,result={**task.get('result',{}),kind+'_verified':True})
        final = client.item(asset['rating_key'])
        if changes and not self._same_metadata(self.metadata_fields(final),changes):raise ValueError('Plex metadata changed during artwork upload; inspect before retrying')
        self._cache_metadata(asset,final)
        self.resolve_satisfied_folder_work(asset,final,plan['folder'],True)
        with self.store.transaction():
            self.store.put('settings','folder-applied:' + key(task['plan']['folder'],asset['rating_key']),dict(signature=plan['settings_signature'],metadata=self.metadata_fields(final),art={kind:Plex.artwork_path(final,kind) for kind in plan['artwork']}))
        self._save(task,status='applied',result={**task.get('result',{}),'verified':True})

    def recommend_folder_defaults(self, asset):
        choices = [r for r in self.store.all('settings') if isinstance(r,dict) and r.get('record') == 'folder_defaults' and r['library'] == asset['library']
            and (str(PurePosixPath(asset['plex_path']).parent) == r['folder'] or r['recursive'] and PurePosixPath(asset['plex_path']).parent.is_relative_to(r['folder']))]
        if not choices:return
        defaults = max(choices,key=lambda r:len(PurePosixPath(r['folder']).parts))
        _, changes, artwork = self._folder_changes(asset['item'],defaults)
        receipt = self.store.get('settings','folder-applied:' + key(key(asset['library'],defaults['folder']),asset['rating_key']))
        settings = {field:defaults[field] for field in ('fields','artwork','mode','recursive','branding')}
        if receipt and receipt['signature'] == key(settings) and self._same_metadata(self.metadata_fields(asset['item']),receipt['metadata']) and all(Plex.artwork_path(asset['item'],kind)==path for kind,path in receipt['art'].items()):
            changes, artwork = {}, {}
        tid = key('folder-defaults',asset['id'],defaults['revision'])
        for old in self.store.all('tasks'):
            if old['kind']=='folder_metadata' and old['asset']==asset['id'] and old['status']=='recommendation' and (old['id']!=tid or not changes and not artwork):
                old.update(status='resolved',updated=now());self.store.put('tasks',old['id'],old)
        if not changes and not artwork:return
        if self.store.get('tasks',tid):return
        self.store.put('tasks',tid,dict(id=tid,asset=asset['id'],library=asset['library'],title=asset['title'],kind='folder_metadata',
            status='recommendation',version=1,created=now(),updated=now(),reason='Review saved folder defaults for this file',
            evidence={'folder':defaults['folder']},plan={'folder':key(asset['library'],defaults['folder'])}))
