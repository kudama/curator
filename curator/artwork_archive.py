"""Append-only artwork archives, executed within the shared file-operation limit."""
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from .store import now


def archive_root(value, check_write=False):
    if not isinstance(value,str):raise ValueError('Artwork archive path must be text')
    if not value.strip():return None
    path=Path(value.strip()).expanduser()
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ValueError('Choose an existing absolute artwork archive folder, not a symlink')
    path=path.resolve(strict=True)
    if check_write:
        try:
            with tempfile.NamedTemporaryFile(prefix='.curator-write-check-',dir=path) as probe:
                probe.write(b'Curator archive check');probe.flush();os.fsync(probe.fileno())
        except OSError:raise ValueError('Artwork archive folder is unavailable or not writable') from None
    return path


def readable(value):
    value=unicodedata.normalize('NFKC',str(value))
    return re.sub(r'[^\w .-]','_',value).strip(' .')[:80] or 'Untitled'


def directory(root,parts):
    target=root
    for part in parts:
        target=target/part
        if target.is_symlink():raise ValueError('Artwork archive contains a symlink; choose a safe folder')
        target.mkdir(mode=0o700,exist_ok=True)
        if not target.is_dir():raise ValueError('Artwork archive destination is not a folder')
    return target


def retain(path,data):
    if path.is_symlink():raise ValueError('Archive file is a symlink')
    digest=hashlib.sha256(data).hexdigest()
    if path.exists():
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('Archive filename already contains different data; existing files were kept')
        return digest
    fd,temporary=tempfile.mkstemp(prefix='.curator-artwork-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        try:os.link(temporary,path,follow_symlinks=False)
        except FileExistsError:
            # Another archive worker may have retained this exact immutable file.
            if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                raise ValueError('Archive filename already contains different data; existing files were kept') from None
    finally:
        os.unlink(temporary)
    return digest


class ArtworkArchives:
    def archive_artwork_task(self, task):
        root=archive_root(self.config().get('artwork_archive_path',''))
        if root is None:return None
        with self.operation_lock(task['id']):
            current=self.get_task(task['id'])
            if current['version']!=task['version'] or current['plan'].get('candidate')!=task['plan'].get('candidate'):
                raise ValueError('Artwork changed before archive copy')
            asset=self.asset(task,check=False);plan=task['plan']
            if not plan.get('candidate'):raise ValueError('There is no downloaded artwork candidate to archive')
            kind=plan['kind'];types={'cover':'Posters','background':'Backgrounds','square':'Squares','logo':'Logos'}
            if kind not in types:raise ValueError('Unsupported artwork archive type')
            identity=hashlib.sha256(json.dumps([asset['library'],asset['rating_key']]).encode()).hexdigest()[:12]
            target=directory(root,['Collections' if asset.get('artwork_target')=='collection' else 'Movies',types[kind],readable(task['title'])+'--'+identity])
            directory(root,['Cast'])
            for owner in ('Movies','Collections'):
                for folder in types.values():directory(root,[owner,folder])
            files={};photos={};prefix=readable(task['id'])+'-v'+str(task['version'])
            sources=[(role,plan.get(role)) for role in ('candidate','source_image','original')]+[('reference-'+str(i+1),photo) for i,photo in enumerate(plan.get('reference_photos',[]))]
            for role,photo in sources:
                if not photo:continue
                if photo in photos:
                    files[role]=dict(photos[photo]);continue
                data=self.folder_image(photo);suffix='.png' if data.startswith(b'\x89PNG') else '.jpg'
                filename=prefix+'-'+role+'-'+hashlib.sha256(data).hexdigest()[:12]+suffix
                digest=retain(target/filename,data);files[role]=dict(file=filename,sha256=digest);photos[photo]=files[role]
            manifest=dict(version=1,task=task['id'],task_version=task['version'],target=dict(library=asset['library'],rating_key=asset['rating_key'],kind=asset.get('artwork_target','media'),title=task['title']),artwork=kind,files=files,style=plan.get('style'),settings=plan.get('settings'),references=plan.get('reference_photos',[]),billing=(task.get('provider') or {}).get('billing'),created=task.get('created'))
            name=prefix+'-manifest.json'
            retain(target/name,json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2).encode())
            record=dict(root=str(root),directory=str(target.relative_to(root)),manifest=name)
            with self.store.transaction():
                latest=self.get_task(task['id'])
                if latest['version']!=task['version']:raise ValueError('Artwork task changed while archiving')
                locations=latest.get('archive_locations',[])
                if record not in locations:locations.append(record)
                latest.update(archive_locations=locations,archive_error=None,updated=now())
                self.store.put('tasks',latest['id'],latest)
            task.update(archive_locations=locations,archive_error=None)
            return record

    def queue_artwork_archive(self, task):
        if not self.config().get('artwork_archive_path'):return
        self.queue_file_operation('archive_artwork',{'task':task['id'],'version':task['version']},background=True)

    def archive_portrait(self, profile_id, revision):
        root=archive_root(self.config().get('artwork_archive_path',''))
        if root is None:return None
        with self.operation_lock('portrait:'+profile_id):
            profiles=self.store.get('settings','cast_profiles',{})
            profile=profiles.get(profile_id)
            if not profile or profile['revision']!=revision or not profile.get('photo'):
                raise ValueError('Person portrait changed before archive copy')
            data=self.cast_profile_image(profile_id)
            suffix='.png' if data.startswith(b'\x89PNG') else '.jpg'
            target=directory(root,['Cast'])
            filename=readable(profile['name'])+'--'+profile_id[:12]+'-v'+str(revision)+'-'+hashlib.sha256(data).hexdigest()[:12]+suffix
            retain(target/filename,data)
            manifest=dict(version=1,person=profile_id,name=profile['name'],revision=revision,photo=filename,sha256=hashlib.sha256(data).hexdigest(),identity=profile.get('identity'))
            retain(target/(filename+'.json'),json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2).encode())
            with self.store.transaction():
                latest=self.store.get('settings','cast_profiles',{})
                if profile_id in latest and latest[profile_id]['revision']==revision:
                    locations=latest[profile_id].get('archive_locations',[])
                    entry=dict(root=str(root),file='Cast/'+filename)
                    if entry not in locations:locations.append(entry)
                    latest[profile_id].update(archive_locations=locations,archive_error=None)
                    self.store.put('settings','cast_profiles',latest)
            return manifest

    def queue_portrait_archive(self, profile_id, revision):
        if self.config().get('artwork_archive_path'):
            self.queue_file_operation('archive_portrait',{'profile':profile_id,'revision':revision},background=True)
