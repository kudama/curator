"""Reviewed file naming, multipart processing and managed Plex group workflows."""
import hashlib
import ctypes
import errno
import sys
import os
import subprocess
import time
import uuid
from pathlib import Path, PurePosixPath
from . import multipart, tools
from .paths import map_path
from .plex import Plex
from .store import now
from .quality import assess

FILE_KINDS = {'rename', 'join', 'group'}
ACTIVE = {'queued', 'running', 'publishing'}
UNSUPPORTED_MOVE = {errno.ENOTSUP,errno.EOPNOTSUPP,errno.ENOSYS}


def item_paths(item):
    return [p['file'] for m in item.get('Media',[]) for p in m.get('Part',[]) if p.get('file')]


def identity(item):
    # Capture curated fields and per-user playback state; scanner timestamps are excluded.
    fields = ('ratingKey','guid','title','summary','studio','tagline','year','originallyAvailableAt',
              'viewCount','viewOffset','lastViewedAt','userRating','Genre','Label','Collection','Role','Field')
    return {k:item.get(k) for k in fields}


def exclusive_move(source, destination):
    """Same-volume no-overwrite rename, including SMB mounts on macOS."""
    install_exclusive(source,destination)


def install_exclusive(source, destination):
    """Atomic same-volume install without clobbering an existing destination."""
    if sys.platform=='darwin':
        # Darwin sys/stdio.h: RENAME_EXCL=0x4. Avoid requiring hard-link support on SMB mounts.
        rename=ctypes.CDLL(None,use_errno=True).renamex_np
        rename.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint];rename.restype=ctypes.c_int
        if rename(os.fsencode(source),os.fsencode(destination),0x4):
            number=ctypes.get_errno()
            raise OSError(number,os.strerror(number))
    else:
        os.link(source,destination,follow_symlinks=False)
        source.unlink()


class FileWorkflows:
    def copy_install_required(self, destination, task=None):
        device=Path(destination).parent.stat().st_dev
        previous=(task or {}).get('publication_error') or {}
        return bool(self.store.get('settings','copy-install:'+str(device),False) or
                    (previous.get('errno') in UNSUPPORTED_MOVE and previous.get('phase')=='Installing verified joined file'))

    def move_with_fallback(self, task, source, destination, phase, receipt=None, force_copy=False, remove_source=True, preserve_time=True):
        source,destination=Path(source),Path(destination)
        if not force_copy and remove_source:
            try:
                install_exclusive(source,destination)
            except OSError as error:
                if error.errno not in UNSUPPORTED_MOVE:raise
                with self.store.transaction():self.store.put('settings','copy-install:'+str(destination.parent.stat().st_dev),True)
            else:
                if receipt:receipt(tools.fingerprint(destination))
                return
        self.publication_phase(task,phase+' using verified copy (share has no exclusive rename)')
        before=tools.fingerprint(source);owner=None;source_removed=False
        def created(value):
            nonlocal owner
            owner=value
            self._save(task,file_move_pending=dict(source=str(source),destination=str(destination),owner=value,source_fingerprint=before))
        try:
            checksum=self._copy_with_progress(task,source,destination,phase+' · copying',created=created)
            if self.publication_digest(task,destination,phase+' · verifying copy')!=checksum:
                raise ValueError('Destination copy failed verification; source retained')
            if tools.fingerprint(source)!=before:
                raise ValueError('Source changed during copy; source retained')
            if preserve_time:
                stat=source.stat();os.utime(destination,ns=(stat.st_atime_ns,stat.st_mtime_ns))
            current=destination.stat()
            if current.st_dev!=owner['device'] or current.st_ino!=owner['inode']:
                raise ValueError('Destination changed during copy; source retained')
            if receipt:receipt(tools.fingerprint(destination))
            if remove_source:
                source.unlink();source_removed=True
            self._save(task,file_move_pending=None)
        except Exception:
            # Remove only the new file opened exclusively by this call. Never touch a collision.
            if owner and not source_removed:
                try:
                    stat=destination.stat()
                    if stat.st_dev==owner['device'] and stat.st_ino==owner['inode']:
                        destination.unlink();self._save(task,file_move_pending=None)
                except OSError:pass
            raise

    def publication_phase(self, task, phase):
        self._save(task,progress={'phase':phase})
        with self.store.transaction():self.store.event(task['id'],{'action':'publication phase','phase':phase})

    def publication_digest(self, task, path, phase):
        self.publication_phase(task,phase)
        total=Path(path).stat().st_size;done=0;reported=time.monotonic();digest=hashlib.sha256()
        self._save(task,progress=dict(phase=phase,completed_bytes=0,total_bytes=total))
        with Path(path).open('rb') as stream:
            while chunk:=stream.read(8*1024*1024):
                digest.update(chunk);done+=len(chunk)
                if time.monotonic()-reported>=1:
                    self._save(task,progress=dict(phase=phase,completed_bytes=done,total_bytes=total));reported=time.monotonic()
        self._save(task,progress=dict(phase=phase,completed_bytes=done,total_bytes=total))
        return digest.hexdigest()

    def publication_log(self, key):
        self.get_task(key)
        return {'entries':self.store.publication_log(key)}

    def join_metadata_snapshot(self, item, include_art=True, client=None):
        snapshot=dict(rating_key=str(item.get('ratingKey')),guid=item.get('guid'),metadata=self.metadata_fields(item))
        if include_art:
            snapshot['art']={kind:Plex.artwork_path(item,kind) for kind in Plex.ARTWORK}
            if client is not None:snapshot['art_hashes']=self._art_hashes(client,item)
        return snapshot

    def check_join_metadata(self, plan, item, client=None):
        expected=plan.get('metadata_snapshot') or self.join_metadata_snapshot(plan['metadata_identity'],include_art=False)
        current=self.join_metadata_snapshot(item)
        changed=[]
        if current['rating_key']!=expected['rating_key'] or current['guid']!=expected['guid']:changed.append('Plex identity')
        changed.extend(field for field,value in expected['metadata'].items() if not self._same_metadata(current['metadata'],{field:value}))
        if 'art_hashes' in expected:
            hashes=self._art_hashes(client,item) if client is not None else {}
            if hashes!=expected['art_hashes']:changed.append('artwork image content')
        elif 'art' in expected and current['art']!=expected['art']:
            changed.append('artwork preview needs content verification')
        if changed:raise ValueError('Chosen source metadata changed ('+', '.join(changed)+'). Use Refresh metadata preview; the joined video is retained.')

    def refresh_join_metadata(self, key, version):
        with self.operation_lock(key):
            task=self.get_task(key)
            if task['kind']!='join' or task['status'] not in {'blocked','awaiting_review'} or task['version']!=version or not task.get('output') or task.get('validation'):
                raise ValueError('No validated joined output is available for metadata review')
            rows=self.file_sources(task);self._file_conflicts(task)
            if tools.digest(task['output'])!=task['output_hash']:raise ValueError('Joined output changed')
            source=next(r for r in rows if r['id']==task['plan']['metadata_asset'])
            client=self.checked_client(self.library(task['library']))
            item=client.item(source['rating_key'])
            if source['plex_path'] not in item_paths(item):raise ValueError('Chosen Plex source path changed')
            previous=task['plan'].get('metadata_snapshot') or task['plan'].get('metadata_identity')
            plan={**task['plan'],'metadata_snapshot':self.join_metadata_snapshot(item,client=client),'metadata_identity':identity(item)}
            with self.store.transaction():
                self.store.event(key,dict(action='join metadata preview refreshed',previous=previous))
            self._save(task,plan=plan,evidence={**task['evidence'],'metadata_title':item.get('title')},version=version+1,
                       status='awaiting_review',error=None,metadata_refreshed=True)
            return task

    def file_suggestions(self, aid):
        asset = self.store.get('assets',aid)
        if not asset or not asset.get('present',True):
            raise ValueError('Select an available file')
        return multipart.suggestions(self.store.all('assets'),asset)

    def _members(self, ids, library=None, check=True):
        if not isinstance(ids,list) or not 1 <= len(ids) <= 16 or any(not isinstance(aid,str) for aid in ids) or len(ids)!=len(set(ids)):
            raise ValueError('Choose 1–16 distinct files')
        rows=[]
        for aid in ids:
            row=self.asset({'asset':aid},check=check)
            library=library or row['library']
            if row['library']!=library:
                raise ValueError('All parts must belong to the selected library')
            rows.append(row)
        if len({r['local_path'] for r in rows})!=len(rows):
            raise ValueError('The same source file was selected more than once')
        return rows

    def _file_conflicts(self, task):
        ids=set(task.get('plan',{}).get('assets',[task['asset']]))
        paths={a['local_path'] for a in self._members(list(ids),check=False)}
        for other in self.store.all('tasks'):
            if other['id']==task['id'] or other['status'] not in ACTIVE:
                continue
            other_ids=other.get('plan',{}).get('assets',[other['asset']])
            if ids.intersection(other_ids) or any(self.store.get('assets',aid,{}).get('local_path') in paths for aid in other_ids):
                raise ValueError('Another queued/running task uses one of these files; finish or cancel it first')

    def _rename_moves(self, source, name):
        destination=source.with_name(multipart.basename(name,source.suffix))
        if destination==source:
            raise ValueError('Choose a different filename')
        moves=[(source,destination)]
        sidecars={'.srt','.ass','.ssa','.vtt','.sub','.idx','.nfo','.jpg','.jpeg','.png','.webp'}
        for child in source.parent.iterdir():
            if child==source:
                continue
            tail=None
            if child.name==source.name+'-old':
                tail=destination.name+'-old'
            elif child.name==source.stem+'-old'+source.suffix:
                tail=destination.stem+'-old'+destination.suffix
            elif child.name.startswith(source.stem+'.') and child.suffix.lower() in sidecars:
                tail=destination.stem+child.name[len(source.stem):]
            elif child.name.startswith(source.stem+'-') and (child.suffix.lower() in sidecars or any(x in child.stem.lower() for x in ('trailer','behindthescenes','deleted','featurette','interview','scene','short','other'))):
                tail=destination.stem+child.name[len(source.stem):]
            if tail:
                moves.append((child,child.with_name(multipart.basename(tail))))
        for old,new in moves:
            if old.is_symlink() or not old.is_file():
                raise ValueError('Rename supports regular files only; inspect related files')
            if new.exists() or new.is_symlink():
                raise ValueError('A proposed filename already exists; nothing was renamed')
        return [dict(source=str(old),destination=str(new),fingerprint=tools.fingerprint(old)) for old,new in moves]

    def file_plan(self, data):
        kind=data.get('kind')
        if kind not in FILE_KINDS:
            raise ValueError('Unknown file operation')
        rows=self._members(data.get('assets'))
        if any(Path(row['plex_path']).name != Path(row['local_path']).name for row in rows):
            raise ValueError('Symlink/alias filenames need manual inspection before file operations')
        if kind=='rename' and len(rows)!=1:
            raise ValueError('Rename one file at a time')
        if kind!='rename' and len(rows)<2:
            raise ValueError('Select at least two parts')
        library=self.library(rows[0]['library'])
        for row in rows:
            plex_path=PurePosixPath(row['plex_path'])
            matching=[m for m in library['mappings'] if plex_path.is_relative_to(PurePosixPath(m['plex_root']))]
            mapping=max(matching,key=lambda m:len(PurePosixPath(m['plex_root']).parts))
            if (Path(mapping['local_root'])/plex_path.relative_to(PurePosixPath(mapping['plex_root']))).is_symlink():
                raise ValueError('Symlink media files need manual inspection before file operations')
        title=data.get('title',rows[0]['title'])
        if not isinstance(title,str) or not title.strip() or len(title)>300:
            raise ValueError('Supply a title of up to 300 characters')
        plan=dict(assets=[r['id'] for r in rows],title=title.strip(),
                  sources=[dict(id=r['id'],fingerprint=r['fingerprint'],plex_path=r['plex_path']) for r in rows])
        evidence={'ordered':[dict(filename=Path(r['plex_path']).name,title=r['title']) for r in rows]}
        client=self.checked_client(library)
        if kind=='rename':
            source_path=Path(rows[0]['local_path'])
            if any(p!=source_path and p.stem==source_path.stem and p.suffix.lower() in {'.mp4','.mkv','.mov','.m4v'} for p in source_path.parent.iterdir()):
                raise ValueError('Multiple videos share this basename; resolve shared sidecars before renaming')
            client.automatic_trash()
            moves=self._rename_moves(Path(rows[0]['local_path']),data.get('filename'))
            plan.update(moves=moves,filename=Path(moves[0]['destination']).name)
            evidence.update(renames=[dict(before=Path(m['source']).name,after=Path(m['destination']).name) for m in moves],
                            note='Plex title and metadata stay unchanged. Same folder; related sidecars, extras and backups shown above move together. Folder branding files remain in place.')
        elif kind=='join':
            source=Path(rows[0]['local_path'])
            filename=multipart.basename(data.get('filename'))
            if Path(filename).suffix.lower() not in {'.mkv','.mp4','.mov','.m4v'}:
                raise ValueError('Choose MKV, MP4, MOV or M4V for the joined output')
            destination=source.with_name(filename)
            if destination.exists() or destination.is_symlink():
                raise ValueError('Output filename already exists; choose a new filename')
            for row in rows:
                p=Path(row['local_path'])
                if any(child.name.startswith(p.stem+'.') and child.suffix.lower() in {'.srt','.ass','.ssa','.vtt','.sub','.idx'} for child in p.parent.iterdir()):
                    raise ValueError('A part has external subtitles; embed or combine them before joining so no subtitles are lost')
            media=[tools.probe(r['local_path'],self.config()) for r in rows]
            compatible=multipart.compatibility(media)
            mode=data.get('mode','copy')
            if mode not in {'copy','normalize'}:
                raise ValueError('Choose stream copy or normalization')
            if mode=='copy' and not compatible:
                raise ValueError('Part stream settings differ. Choose Normalize and review its settings, or use matching parts.')
            canvas=multipart.normalization(media) if mode=='normalize' else None
            if canvas:canvas['encoder']=multipart.normalization_encoder(self.config())
            titles=data.get('chapter_titles') or [f'Part {i+1}' for i in range(len(rows))]
            if not isinstance(titles,list) or len(titles)!=len(rows) or any(not isinstance(t,str) or not t.strip() or len(t)>200 for t in titles):
                raise ValueError('Supply one chapter title per part (up to 200 characters)')
            chapters=multipart.chapters(media,titles)
            selected=data.get('metadata_asset',rows[0]['id'])
            if selected not in plan['assets']:
                raise ValueError('Choose metadata/artwork from one of the selected parts')
            plan.update(filename=filename,destination=str(destination),plex_destination=str(PurePosixPath(rows[0]['plex_path']).with_name(filename)),
                        mode=mode,canvas=canvas,chapters=chapters,media=media,metadata_asset=selected)
            chosen=next(r for r in rows if r['id']==selected)
            chosen_item=client.item(chosen['rating_key'])
            plan['metadata_identity']=identity(chosen_item)
            plan['metadata_snapshot']=self.join_metadata_snapshot(chosen_item,client=client)
            evidence.update(mode='Lossless stream copy' if mode=='copy' else canvas['description'],
                            chapters=chapters,filename=filename,total_seconds=sum(m['duration_seconds'] for m in media),
                            total_bytes=sum(m['size_bytes'] for m in media),metadata_title=chosen_item.get('title'),
                            note='Creates a new Plex item using the chosen part’s descriptive metadata/artwork and the new title. Original parts, playback history, collections and playlists stay in place; watch states are not merged.')
        else:
            group_mode=data.get('group_mode','both')
            if group_mode not in {'both','collection','playlist'}:
                raise ValueError('Choose collection, playlist, or both')
            if library['type']!='movie' or any(r['item'].get('type')!='movie' for r in rows):
                raise ValueError('Multipart collections currently support movie/Other Videos items')
            keys=[r['rating_key'] for r in rows]
            if len(set(keys))!=len(keys):
                raise ValueError('Each installment must be a distinct Plex item')
            ownership=self.store.get('settings','group:'+library['id']+':'+title.strip(),{})
            kinds=['collection','playlist'] if group_mode=='both' else [group_mode]
            for group_kind in kinds:
                client.group_state(library,group_kind,title.strip(),ownership.get(group_kind))
            plan.update(group_kinds=kinds,rating_keys=keys,ownership=ownership)
            evidence.update(note='Collection groups the installments; playlist follows this exact order. Individual metadata and watch history are preserved.')
        key=hashlib.sha256(uuid.uuid4().bytes).hexdigest()[:24]
        task=dict(id=key,asset=rows[0]['id'],library=library['id'],title=title.strip(),kind=kind,
                  reason={'rename':'Review the proposed disk filenames','join':'Review parts, chapters and output settings','group':'Review collection membership and viewing order'}[kind],
                  evidence=evidence,plan=plan,status='recommendation',version=1,created=now(),updated=now())
        self._file_conflicts(task)
        with self.store.transaction():
            self.store.put('tasks',key,task)
        return task

    def file_sources(self, task):
        rows=self._members(task['plan']['assets'],task['library'])
        for row,snapshot in zip(rows,task['plan']['sources']):
            if row['fingerprint']!=snapshot['fingerprint'] or row['plex_path']!=snapshot['plex_path']:
                raise ValueError('A source changed after preview; make a new plan')
        return rows

    def queue_file_task(self, task):
        if task.get('published') or task.get('rename_started') or task.get('group_started'):
            raise ValueError('Inspect the recorded operation before retrying; do not repeat an uncertain publication')
        rows=self.file_sources(task)
        self._file_conflicts(task)
        if self.scan_status.get(task['library'],{}).get('running') or self.presence_status.get(task['library'],{}).get('running'):
            raise ValueError('Wait for the library scan before queueing file operations')
        if task['kind']=='rename':
            self.checked_client(self.library(task['library'])).automatic_trash()
            if self._rename_moves(Path(rows[0]['local_path']),task['plan']['filename'])!=task['plan']['moves']:
                raise ValueError('Related files changed; preview the rename again')
        settings=self.config();settings.pop('plex_token',None)
        task['tool_settings']=settings

    def execute_file_task(self, task):
        rows=self.file_sources(task)
        if task['kind']=='rename':
            self._rename(task,rows[0])
        elif task['kind']=='join':
            self._join(task,rows)
        else:
            self._group(task,rows)

    def _wait_item_path(self, client, key, path):
        for attempt in range(60):
            item=client.item(key)
            if path in item_paths(item):
                return item
            time.sleep(.5)
        raise ValueError('Plex did not retain the same item at its new path')

    def _art_hashes(self, client, item):
        return {kind:hashlib.sha256(client.image(item['ratingKey'],kind)).hexdigest()
                for kind in Plex.ARTWORK if Plex.artwork_path(item,kind)}

    def same_rename_identity(self, before, after):
        for field in ('ratingKey','guid','year','originallyAvailableAt','userRating'):
            if before.get(field)!=after.get(field):return False
        for field in ('viewCount','viewOffset','lastViewedAt'):
            if (before.get(field) or 0)!=(after.get(field) or 0):return False
        return self._same_metadata(self.metadata_fields(after),self.metadata_fields(before))

    def _rename(self, task, asset):
        library=self.library(task['library']);client=self.checked_client(library)
        client.automatic_trash()
        before=client.item(asset['rating_key'])
        if asset['plex_path'] not in item_paths(before):
            raise ValueError('Plex source path changed; rescan and preview again')
        art=self._art_hashes(client,before)
        moves=task['plan']['moves'];moved=[]
        self._save(task,rename_started=True,rename_before=before,rename_art_hashes=art,
                   progress={'phase':'Renaming files'})
        self.publication_phase(task,'Renaming files')
        try:
            for move in moves:
                old,new=Path(move['source']),Path(move['destination'])
                if old.is_symlink() or tools.fingerprint(old)!=move['fingerprint']:
                    raise ValueError('A related file changed; rename stopped')
                def receipt(fingerprint):
                    record={**move,'destination_fingerprint':fingerprint}
                    if not any(m['source']==move['source'] for m in moved):moved.append(record)
                    self._save(task,rename_moved=list(moved))
                self.move_with_fallback(task,old,new,'Renaming file',receipt=receipt,force_copy=self.copy_install_required(new))
                destination_fingerprint=tools.fingerprint(new)
                if any(destination_fingerprint[k]!=move['fingerprint'][k] for k in ('size','modified')):
                    raise ValueError('File size or modification time changed while renaming')
            new_plex=str(PurePosixPath(asset['plex_path']).with_name(task['plan']['filename']))
            self.publication_phase(task,'Verifying Plex identity and metadata')
            client.scan_folder(library,str(PurePosixPath(new_plex).parent))
            after=self._wait_item_path(client,asset['rating_key'],new_plex)
            if not self.same_rename_identity(before,after) or art!=self._art_hashes(client,after):
                raise ValueError('Plex metadata/artwork/playback state changed during rename')
            destination=Path(moves[0]['destination'])
            if tools.fingerprint(destination)!=moved[0]['destination_fingerprint']:
                raise ValueError('Renamed file changed during verification')
            with self.store.transaction():
                # Preserve stable asset/task IDs; subsequent scans reuse this path alias.
                for row in self.store.all('assets'):
                    if row['library']==asset['library'] and row.get('local_path')==asset['local_path']:
                        row.update(local_path=str(destination),plex_path=new_plex,fingerprint=tools.fingerprint(destination),item=after)
                        self.store.put('assets',row['id'],row)
                for old in self.store.all('tasks'):
                    if old['id']==task['id']:
                        continue
                    if old['asset']==asset['id'] or asset['id'] in old.get('plan',{}).get('assets',[]):
                        self.store.event(old['id'],dict(action='source renamed',previous=old))
                        old.update(version=old['version']+1,comparison_loaded=False)
                        old.pop('approval',None)
                        # Finished history remains finished; unfinished plans must be rebuilt.
                        if old['status'] not in {'applied','resolved','rejected','cancelled'}:
                            old.update(status='blocked',error='Filename changed; rescan and review a fresh plan')
                        self.store.put('tasks',old['id'],old)
                for move in moves:
                    for old in self.store.all('tasks'):
                        if old.get('archive')==move['source']:
                            old['archive']=move['destination'];self.store.put('tasks',old['id'],old)
            self._save(task,status='applied',result={'verified':True,'filename':destination.name},rename_verified=True)
        except Exception as error:
            phase=task.get('progress',{}).get('phase','Renaming files');number=getattr(error,'errno',None)
            detail=str(error) if isinstance(error,ValueError) else (os.strerror(number) if number else type(error).__name__)
            diagnostic=dict(phase=phase,error_type=type(error).__name__,errno=number,detail=detail)
            with self.store.transaction():self.store.event(task['id'],dict(action='publication failed',**diagnostic))
            self._save(task,rename_error=diagnostic)
            failures=[]
            for move in reversed(moved):
                old,new=Path(move['source']),Path(move['destination'])
                try:
                    if not new.exists() and old.exists() and tools.fingerprint(old)==move['fingerprint']:
                        continue
                    if tools.fingerprint(new)!=move.get('destination_fingerprint',move['fingerprint']):
                        raise ValueError('Renamed file changed')
                    if old.exists():
                        if tools.fingerprint(old)!=move['fingerprint']:raise ValueError('Original path changed')
                        new.unlink()
                    else:
                        self.move_with_fallback(task,new,old,'Restoring original filename',force_copy=self.copy_install_required(old))
                except Exception:
                    failures.append(move)
            self._save(task,rename_rollback_failures=failures,rename_restored=not failures)
            if not failures and Path(moves[0]['source']).is_file():
                with self.store.transaction():
                    for row in self.store.all('assets'):
                        if row['library']==asset['library'] and row.get('local_path')==moves[0]['source']:
                            row['fingerprint']=tools.fingerprint(moves[0]['source']);self.store.put('assets',row['id'],row)
            try:
                client.scan_folder(library,str(PurePosixPath(asset['plex_path']).parent))
            except Exception:
                pass
            raise ValueError('Rename failed at '+phase+': '+detail+(f' (errno {number})' if number else '')+'. '+('Some names need manual recovery; inspect the retained receipt.' if failures else 'Original filenames restored; inspect Plex before trying again.')) from None

    def restore_rename(self, key, version):
        with self.operation_lock(key):
            task=self.get_task(key)
            if task['kind']!='rename' or task['status']!='blocked' or task['version']!=version or not task.get('rename_started'):
                raise ValueError('No interrupted rename is available to recover')
            self._file_conflicts(task)
            library=self.library(task['library']);client=self.checked_client(library)
            client.automatic_trash()
            self._save(task,status='publishing',progress={'phase':'Restoring original filenames'})
            try:
                recorded={m['source']:m for m in task.get('rename_moved',[])}
                for original in reversed(task['plan']['moves']):
                    move=recorded.get(original['source'],original)
                    old,new=Path(move['source']),Path(move['destination'])
                    if old.exists() and tools.fingerprint(old)!=move['fingerprint']:
                        raise ValueError('An original filename now contains another file; recovery stopped')
                    if new.exists():
                        if new.is_symlink() or tools.fingerprint(new)!=move.get('destination_fingerprint',move['fingerprint']):
                            raise ValueError('A renamed file changed; recovery stopped')
                        if old.exists():new.unlink()
                        else:self.move_with_fallback(task,new,old,'Restoring original filename',force_copy=self.copy_install_required(old))
                    elif not old.exists():
                        raise ValueError('A retained rename file is missing; recovery stopped')
                asset=self.asset(task,check=False)
                old_path=task['plan']['sources'][0]['plex_path']
                client.scan_folder(library,str(PurePosixPath(old_path).parent))
                restored=self._wait_item_path(client,asset['rating_key'],old_path)
                if not self.same_rename_identity(task['rename_before'],restored) or self._art_hashes(client,restored)!=task['rename_art_hashes']:
                    raise ValueError('Original filenames restored, but Plex metadata/state needs inspection')
                self._save(task,status='resolved',rename_restored=True,rename_recovery_verified=True,error=None,result={'restored':True})
            except Exception as error:
                message=str(error) if isinstance(error,ValueError) else 'Recovery stopped; inspect retained filenames'
                self._save(task,status='blocked',error=message)
                raise ValueError(message) from None
            return task

    def _run_file_tool(self, task, argv, output, phase, folder):
        log=folder/('tool-'+uuid.uuid4().hex+'.log')
        with log.open('wb') as stream:
            process=subprocess.Popen(argv,stdout=stream,stderr=subprocess.STDOUT)
            try:
                while process.poll() is None:
                    if task['id'] in self.cancels:
                        process.terminate()
                        try:process.wait(timeout=5)
                        except subprocess.TimeoutExpired:process.kill()
                        raise ValueError('Cancelled; original parts preserved')
                    self._save(task,progress={'phase':phase,'output_bytes':output.stat().st_size if output.exists() else 0})
                    time.sleep(.5)
                if process.returncode:
                    raise ValueError('FFmpeg failed; inspect the private task log. Original parts preserved.')
            finally:
                if process.poll() is None:process.kill()
                process.wait()

    def _join(self, task, rows):
        plan=task['plan'];settings=task['tool_settings']
        folder=self.store.root/'outputs'/task['id']/uuid.uuid4().hex
        folder.mkdir(parents=True,mode=0o700)
        inputs=[Path(row['local_path']) for row in rows]
        self._save(task,source_hashes=[tools.digest(p) for p in inputs],comparison_loaded=False)
        if plan['mode']=='normalize':
            normalized=[]
            for i,source in enumerate(inputs):
                out=folder/f'part-{i}.mkv'
                self._run_file_tool(task,multipart.normalize_command(source,out,plan['canvas'],settings,plan['media'][i]),out,
                                    f'Normalizing part {i+1} of {len(inputs)}',folder)
                normalized.append(out)
            inputs=normalized
            if not multipart.compatibility([tools.probe(p,settings) for p in inputs]):
                raise ValueError('Normalized stream parameters still differ; inspect parts before retrying')
        out=folder/('joined'+Path(plan['filename']).suffix.lower())
        metadata=folder/'chapters.txt';multipart.metadata_file(metadata,plan['chapters'])
        first=tools.probe(inputs[0],settings)
        argv=multipart.concat_command(inputs,folder/'parts.txt',metadata,out,settings,first)
        if out.suffix in {'.mov','.mp4','.m4v'}:
            args=['-movflags','+faststart']
            if first['codec']=='hevc':args+=['-tag:v','hvc1']
            argv[-1:-1]=args
        self._run_file_tool(task,argv,out,'Joining parts and writing chapters',folder)
        result=tools.probe(out,settings)
        issues=[]
        expected=task['evidence']['total_seconds']
        if abs(result['duration_seconds']-expected)>max(1,expected*.005):issues.append('Joined duration differs from sum of parts')
        for kind in ('video','audio','subtitle'):
            old=[s.get('tags',{}).get('language','und') for s in first['streams'] if s['codec_type']==kind]
            new=[s.get('tags',{}).get('language','und') for s in result['streams'] if s['codec_type']==kind]
            if old!=new:issues.append(kind+' tracks differ')
        if result['width']!=first['width'] or result['height']!=first['height']:
            issues.append('Joined output geometry differs')
        if out.suffix in {'.mov','.mp4','.m4v'} and result['codec']=='hevc' and any(s.get('codec_type')=='video' and s.get('codec_tag_string')!='hvc1' for s in result['streams']):
            issues.append('HEVC output needs hvc1 for QuickTime')
        observed=result.get('chapters',[])
        if len(observed)!=len(plan['chapters']) or any(abs(float(o['start_time'])-c['start'])>.1 or o.get('tags',{}).get('title')!=c['title'] for o,c in zip(observed,plan['chapters'])):
            issues.append('Chapter readback differs')
        self._run_file_tool(task,[tools.executable(settings,'ffmpeg'),'-nostdin','-v','error','-xerror','-i',str(out),
                                 '-map','0:v:0','-map','0:a?','-f','null','-'],out,'Checking complete output decode',folder)
        self.file_sources(task)
        if [tools.digest(row['local_path']) for row in rows]!=task['source_hashes']:
            raise ValueError('A part changed during processing')
        if task['id'] in self.cancels:raise ValueError('Cancelled; original parts preserved')
        self._save(task,output=str(out),output_hash=tools.digest(out),result=result,validation=issues,
                   status='blocked' if issues else 'awaiting_review',error='; '.join(issues) if issues else None)

    def join_comparison(self, key):
        task=self.get_task(key)
        if task['kind']!='join' or task['status']!='awaiting_review':
            raise ValueError('No joined output awaiting review')
        rows=self.file_sources(task)
        if tools.digest(task['output'])!=task['output_hash']:
            raise ValueError('Joined output changed')
        folder=self.store.root/'join-samples'/key/uuid.uuid4().hex;folder.mkdir(parents=True,mode=0o700)
        samples=[];offset=0
        for i,(row,media) in enumerate(zip(rows,task['plan']['media'])):
            for label,local in [('start',min(.25,media['duration_seconds']/4)),('end',max(0,media['duration_seconds']-.25))]:
                pair=[]
                for side,path,seconds in [('source',row['local_path'],local),('output',task['output'],offset+local)]:
                    name=f'{i}-{label}-{side}.jpg';target=folder/name
                    subprocess.run([tools.executable(self.config(),'ffmpeg'),'-nostdin','-n','-ss',str(seconds),'-i',str(path),
                                    '-frames:v','1','-vf','scale=640:-2',str(target)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60,check=True)
                    tools.image_bytes(target);pair.append(name)
                samples.append(dict(label=f'Part {i+1} {label}',files=pair))
            offset+=media['duration_seconds']
        self._save(task,comparison_loaded=True,sample_folder=str(folder),samples=samples)
        return dict(samples=samples)

    def join_sample(self, key, name):
        task=self.get_task(key)
        names=[n for pair in task.get('samples',[]) for n in pair['files']]
        if name not in names:raise ValueError('Unknown sample')
        return tools.image_bytes(Path(task['sample_folder'])/name)

    def publish_join(self, task):
        if not task.get('comparison_loaded') or task.get('validation'):
            raise ValueError('Load and review all part-boundary comparisons before publishing')
        self.publication_phase(task,'Checking approved join sources')
        rows=self.file_sources(task);plan=task['plan']
        self.publication_phase(task,'Checking Plex source metadata')
        self._file_conflicts(task)
        source=next(r for r in rows if r['id']==plan['metadata_asset'])
        library=self.library(task['library']);client=self.checked_client(library)
        item=client.item(source['rating_key'])
        self.check_join_metadata(plan,item,client)
        destination=map_path(plan['plex_destination'],library['mappings'],require_exists=False)
        if str(destination)!=plan['destination']:
            raise ValueError('Output mapping changed')
        already_published=bool(task.get('published'))
        if destination.is_symlink() or (destination.exists() and not already_published):
            raise ValueError('Output filename now exists; original parts preserved')
        if already_published and (not destination.is_file() or tools.digest(destination)!=task['output_hash']):
            raise ValueError('Previously published join changed; inspect before retrying verification')
        hashes=[self.publication_digest(task,r['local_path'],f'Verifying original part {i+1} of {len(rows)}') for i,r in enumerate(rows)]
        if hashes!=task['source_hashes'] or self.publication_digest(task,task['output'],'Verifying retained joined output')!=task['output_hash']:
            raise ValueError('A source or joined output changed')
        art={kind:client.image(source['rating_key'],kind) for kind in Plex.ARTWORK if Plex.artwork_path(item,kind)}
        approved=plan.get('metadata_snapshot',{}).get('art_hashes')
        if approved is not None and {kind:hashlib.sha256(image).hexdigest() for kind,image in art.items()}!=approved:
            raise ValueError('Artwork image content changed; use Refresh metadata preview. Joined output retained.')
        self._save(task,join_metadata_before=item,progress={'phase':'Publishing joined file; retaining every part'})
        stage=destination.parent/('.curator-'+uuid.uuid4().hex+destination.suffix)
        try:
            if not already_published and self.copy_install_required(destination,task):
                self.move_with_fallback(task,Path(task['output']),destination,'Installing joined file',force_copy=True,remove_source=False,preserve_time=False)
                self._save(task,published=True,published_path=str(destination))
            elif not already_published:
                self._copy_with_progress(task,Path(task['output']),stage,'Staging joined video')
                if self.publication_digest(task,stage,'Verifying staged joined video')!=task['output_hash']:raise ValueError('Staged output hash differs')
                self.publication_phase(task,'Checking source files before installation')
                self.file_sources(task)
                self.check_join_metadata(plan,client.item(source['rating_key']),client)
                self.publication_phase(task,'Installing verified joined file')
                self.move_with_fallback(task,stage,destination,'Installing joined file',preserve_time=False)
                self._save(task,published=True,published_path=str(destination))
        finally:
            stage.unlink(missing_ok=True)
        self.publication_phase(task,'Waiting for Plex to index the joined video')
        client.scan_folder(library,str(PurePosixPath(plan['plex_destination']).parent))
        found=[]
        for attempt in range(60):
            found=[]
            for candidate in client.items(library):
                parts=[p for m in candidate.get('Media',[]) for p in m.get('Part',[]) if p.get('file')==plan['plex_destination']]
                if not parts:continue
                # An automatic scanner may have seen the destination during an exclusive copy.
                if any('size' in p and int(p['size'])!=task['result']['size_bytes'] for p in parts):continue
                if 'duration' in candidate and abs(float(candidate['duration'])/1000-task['result']['duration_seconds'])>max(1,task['result']['duration_seconds']*.005):continue
                found.append(candidate)
            if found:break
            time.sleep(.5)
        if len(found)!=1 or str(found[0]['ratingKey']) in {r['rating_key'] for r in rows}:
            raise ValueError('Joined file retained, but Plex did not create one distinct item. Inspect Plex; source parts are unchanged.')
        target=found[0]
        self._save(task,joined_rating_key=str(target['ratingKey']))
        self.publication_phase(task,'Applying joined item metadata and artwork')
        changes=self.metadata_fields(item);changes['title']=plan['title']
        verified=client.edit(library,target,changes)
        if not self._same_metadata(self.metadata_fields(verified),changes):raise ValueError('Joined item metadata readback differs')
        for kind,image in art.items():client.artwork(target['ratingKey'],image,kind)
        self.publication_phase(task,'Verifying final metadata after artwork and indexing')
        self._save(task,metadata_copy_expected=changes)
        final=None
        for attempt in range(3):
            final=client.item(target['ratingKey'])
            observed=self.metadata_fields(final)
            differing=[field for field,value in changes.items() if not self._same_metadata(observed,{field:value})]
            self._save(task,metadata_copy_observed=observed,metadata_copy_checks=attempt+1)
            if differing:
                self._save(task,metadata_copy_differing=differing,plex_verified=False)
                raise ValueError('Copied metadata did not persist after artwork/indexing ('+', '.join(differing)+'). Joined file is retained; review metadata before retrying.')
            if plan['plex_destination'] not in item_paths(final):raise ValueError('Plex joined item path changed')
            if attempt<2:time.sleep(.5)
        self._save(task,metadata_copy_differing=[])
        from .service import identifier
        part=next(p for m in final.get('Media',[]) for p in m.get('Part',[]) if p.get('file')==plan['plex_destination'])
        aid=identifier(library['server'],library['key'],final['ratingKey'],part.get('id'),part['file'])
        joined=dict(id=aid,library=library['id'],rating_key=str(final['ratingKey']),title=final.get('title',plan['title']),item=final,plex_path=part['file'],local_path=str(destination),fingerprint=tools.fingerprint(destination),technical=task['result'],present=True,scanned=now())
        with self.store.transaction():
            self.store.put('assets',aid,joined)
            self.reconcile_findings(joined,assess(task['result'],self.config()))
        self.publication_phase(task,'Joined file and Plex item verified')
        self._save(task,status='applied',plex_verified=True,joined_asset=aid,result={**task['result'],'published_rating_key':str(target['ratingKey'])})

    def _group(self, task, rows):
        plan=task['plan'];library=self.library(task['library']);client=self.checked_client(library)
        for row in rows:
            item=client.item(row['rating_key'])
            if row['plex_path'] not in item_paths(item):raise ValueError('An installment changed in Plex')
        ownership=self.store.get('settings','group:'+library['id']+':'+plan['title'],{})
        if ownership!=plan['ownership']:raise ValueError('Managed grouping changed since preview')
        self._save(task,group_started=True,progress={'phase':'Applying collection and viewing order'})
        result=dict(ownership)
        for kind in plan['group_kinds']:
            def receipt(value):
                self._save(task,group_receipt={**task.get('group_receipt',{}),kind:value})
                if not value.get('uncertain'):
                    result[kind]=value
                    with self.store.transaction():self.store.put('settings','group:'+library['id']+':'+plan['title'],result)
            result[kind]=client.managed_group(library,kind,plan['title'],plan['rating_keys'],ownership.get(kind),receipt)
        self._save(task,status='applied',result={'verified':True,'groups':result})
