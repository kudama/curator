"""Preview and explicitly delete only receipt-backed retained originals."""
from pathlib import Path
import stat
import threading
import uuid
from . import tools
from .paths import map_path
from .file_workflows import exclusive_move
from .store import now


def file_identity(path):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode):raise ValueError('Expected a regular file; symlinks are not eligible')
    return dict(device=info.st_dev,inode=info.st_ino,size=info.st_size,mtime=info.st_mtime_ns)


class BackupCleanupWorkflows:
    def recover_backup_cleanups(self):
        with self.store.transaction():
            for record in self.store.all('settings'):
                if isinstance(record,dict) and record.get('record_type')=='backup_cleanup' and record.get('phase')=='deleting':
                    record.update(phase='interrupted',updated=now());self.store.put('settings',record['id'],record)

    def backup_candidate(self,task):
        if task.get('deleted') or task['kind'] not in {'upscale','optimize'} or task['status']!='applied' or not all(task.get(k) for k in ('published','plex_verified','original_renamed')) or task.get('archive_deleted'):
            raise ValueError('No verified retained original is eligible')
        if task.get('cleanup_pending'):raise ValueError('An unfinished cleanup needs recovery first')
        asset=self.asset(task,check=False);source=Path(asset['local_path'])
        if str(map_path(asset['plex_path'],self.library(asset['library'])['mappings']))!=str(source):
            raise ValueError('Media mapping changed; inspect before cleanup')
        backup=source.with_name(source.stem+'-old'+source.suffix)
        if task.get('archive')!=str(backup):raise ValueError('Retained original does not match its publication receipt')
        if any(not isinstance(task.get(k),str) or len(task[k])!=64 for k in ('source_hash','output_hash')):raise ValueError('Publication hashes unavailable')
        source_identity=file_identity(source);backup_identity=file_identity(backup)
        if (source_identity['device'],source_identity['inode'])==(backup_identity['device'],backup_identity['inode']):
            raise ValueError('Original and replacement identities are ambiguous')
        assets={a['id']:a for a in self.store.all('assets')}
        for other in self.store.all('tasks'):
            if other['id']==task['id'] or other['status'] not in {'queued','running','publishing'}:continue
            members=[assets.get(key,{}) for key in other.get('plan',{}).get('assets',[other.get('asset')])]
            if any(member.get('id')==asset['id'] or member.get('local_path')==str(source) or (asset.get('rating_key') and member.get('library')==asset['library'] and member.get('rating_key')==asset['rating_key']) for member in members):
                raise ValueError('This file has active or waiting work')
        return dict(id=task['id'],version=task['version'],title=asset.get('title') or source.name,
                    backup=str(backup),source=str(source),bytes=backup_identity['size'],
                    source_identity=source_identity,backup_identity=backup_identity,status='available')

    def cleanup_receipt(self,identity):
        record=self.store.get('settings',identity)
        if not isinstance(record,dict) or record.get('record_type')!='backup_cleanup':raise ValueError('Cleanup preview unavailable')
        return record

    def cleanup_preview(self,library):
        items=[];blocked=[]
        for task in self.store.all('tasks'):
            if task.get('library')!=library or not task.get('archive') or task.get('archive_deleted'):continue
            try:items.append(self.backup_candidate(task))
            except (ValueError,OSError) as error:
                blocked.append(dict(id=task['id'],reason=str(error) if isinstance(error,ValueError) else 'Retained file unavailable',recoverable=bool(task.get('cleanup_pending'))))
        record=dict(id='backup-cleanup:'+uuid.uuid4().hex,record_type='backup_cleanup',library=library,
                    phase='preview',created=now(),items=items,blocked=blocked)
        history=[r for r in self.store.all('settings') if isinstance(r,dict) and r.get('record_type')=='backup_cleanup' and r.get('library')==library and r.get('phase')!='preview']
        record['history']=[{'id':r['id'],'phase':r['phase'],'created':r['created']} for r in sorted(history,key=lambda r:r['created'],reverse=True)[:10]]
        with self.store.transaction():self.store.put('settings',record['id'],record)
        return record

    def delete_backups(self,identity,ids,count,confirmation,background=True):
        if not isinstance(ids,list) or not ids or any(not isinstance(k,str) for k in ids) or len(ids)!=len(set(ids)) or type(count) is not int or count!=len(ids) or confirmation!='DELETE RETAINED ORIGINALS':
            raise ValueError('Confirm the exact selected backup count')
        with self.lock:
            if any(str(k).startswith('backup-cleanup:') for k in self.active):raise ValueError('Another backup cleanup is active')
            with self.store.transaction():
                record=self.cleanup_receipt(identity)
                if record['phase']!='preview' or set(ids)-{item['id'] for item in record['items']}:
                    raise ValueError('Cleanup selection changed; create a fresh preview')
                record.update(phase='deleting',selected=ids,approved_count=count,approved_at=now())
                self.store.put('settings',identity,record)
            self.active.add(identity)
        if background:threading.Thread(target=self._delete_backup_batch,args=(identity,),daemon=True).start()
        else:self._delete_backup_batch(identity)
        return self.cleanup_receipt(identity)

    def _delete_backup_batch(self,identity):
        try:
            record=self.cleanup_receipt(identity)
            for row in record['items']:
                if row['id'] not in record['selected']:continue
                try:self._delete_one_backup(row,identity);row['status']='deleted'
                except Exception as error:
                    row.update(status='failed',error=str(error)[:300] if isinstance(error,ValueError) else 'Cleanup failed; retained files require inspection')
                with self.store.transaction():
                    record['updated']=now();self.store.put('settings',identity,record)
            record.update(phase='complete',updated=now())
            with self.store.transaction():self.store.put('settings',identity,record)
        except Exception:
            with self.store.transaction():
                record=self.cleanup_receipt(identity);record.update(phase='interrupted',updated=now())
                self.store.put('settings',identity,record)
        finally:
            with self.lock:self.active.discard(identity)

    def _delete_one_backup(self,row,receipt):
        with self.operation_lock(row['id']):
            with self.store.transaction():
                task=self.get_task(row['id']);candidate=self.backup_candidate(task)
                if any(candidate[k]!=row[k] for k in ('version','source','backup','source_identity','backup_identity')):
                    raise ValueError('File or task changed since preview; backup preserved')
                source=Path(row['source']);backup=Path(row['backup'])
                stage=backup.parent/('.curator-cleanup-'+uuid.uuid4().hex+backup.suffix)
                task.update(cleanup_in_progress=True,cleanup_pending=dict(original=str(backup),staged=str(stage),receipt=receipt))
                self.store.put('tasks',task['id'],task);self.store.event(task['id'],dict(action='backup cleanup requested',receipt=receipt,bytes=row['bytes']))
            try:
                if tools.digest(source)!=task['output_hash'] or tools.digest(backup)!=task['source_hash']:
                    raise ValueError('Original or published replacement changed; backup preserved')
                if file_identity(source)!=row['source_identity'] or file_identity(backup)!=row['backup_identity']:
                    raise ValueError('File changed during verification; backup preserved')
                exclusive_move(backup,stage)
                if tools.digest(stage)!=task['source_hash'] or tools.digest(source)!=task['output_hash']:
                    raise ValueError('Files changed during cleanup; retained original requires recovery')
                staged=file_identity(stage)
                if file_identity(source)!=row['source_identity'] or staged!=row['backup_identity']:
                    raise ValueError('File identity changed; retained original requires recovery')
                stage.unlink()
                with self.store.transaction():
                    latest=self.get_task(task['id']);latest.update(archive_deleted=True,cleanup_in_progress=False,cleanup_pending=None,
                        backup_cleanup=dict(receipt=receipt,deleted_at=now(),bytes=row['bytes']),version=latest['version']+1,updated=now())
                    self.store.put('tasks',task['id'],latest);self.store.event(task['id'],dict(action='backup cleanup deleted',receipt=receipt,bytes=row['bytes']))
            except Exception:
                # Never unlink an uncertain staged file. Restore only without overwriting.
                if stage.exists() or stage.is_symlink():
                    try:self.restore_cleanup_backup(task['id'],allow_active=True)
                    except (ValueError,OSError):pass  # Keep the recovery marker and retained file.
                elif backup.exists() and not backup.is_symlink():
                    with self.store.transaction():
                        latest=self.get_task(task['id']);latest.update(cleanup_in_progress=False,cleanup_pending=None)
                        self.store.put('tasks',task['id'],latest)
                raise

    def restore_cleanup_backup(self,key,allow_active=False):
        with self.operation_lock(key):
            task=self.get_task(key);pending=task.get('cleanup_pending')
            if not pending:raise ValueError('No unfinished backup cleanup')
            if not allow_active and pending['receipt'] in self.active:raise ValueError('Wait for the current cleanup to finish')
            original=Path(pending['original']);stage=Path(pending['staged']);asset=self.asset(task,check=False);source=Path(asset['local_path'])
            if original!=source.with_name(source.stem+'-old'+source.suffix) or stage.parent!=original.parent or not stage.name.startswith('.curator-cleanup-'):
                raise ValueError('Cleanup paths do not match the publication receipt')
            if stage.exists() or stage.is_symlink():
                file_identity(stage)
                if tools.digest(stage)!=task['source_hash']:raise ValueError('Staged original changed; inspect it before recovery')
                exclusive_move(stage,original)
            elif not original.is_file() or original.is_symlink():
                raise ValueError('Retained original unavailable; inspect cleanup receipt before recovery')
            if tools.digest(original)!=task['source_hash']:raise ValueError('Restored original differs from its receipt')
            with self.store.transaction():
                task=self.get_task(key);task.update(cleanup_in_progress=False,cleanup_pending=None,updated=now())
                self.store.put('tasks',key,task);self.store.event(key,dict(action='backup cleanup restored'))
            return {'restored':True}
