"""Durable admission for media copy/delete work; at most four I/O jobs."""
import threading
import uuid
from .store import now
from .logs import log
from .errors import UserError


class FileQueueWorkflows:
    def file_jobs(self):
        records=[r for r in self.store.all('settings') if isinstance(r,dict) and r.get('record_type')=='file_operation']
        running=sorted((r for r in records if r['phase']=='running'),key=lambda r:r['created'])
        positions={key:index for index,key in enumerate(self.store.get('settings','file-queue-order:global',{}).get('ids',[]))}
        waiting=sorted((r for r in records if r['phase']=='waiting'),key=lambda r:(positions.get(r['id'],len(positions)),r['created']))
        recent=sorted((r for r in records if r['phase'] not in {'waiting','running'}),key=lambda r:r['created'],reverse=True)[:30]
        return running+waiting+recent

    def file_queue_snapshot(self):
        return [dict(id=j['id'],updated=j.get('updated')) for j in self.file_jobs() if j['phase']=='waiting']

    def change_file_queue_order(self,expected,order):
        if (not isinstance(expected,list) or len(expected)>20000 or
            any(not isinstance(row,dict) or set(row)!={'id','updated'} or not isinstance(row['id'],str) or
                (row['updated'] is not None and not isinstance(row['updated'],str)) for row in expected) or
            not isinstance(order,list) or any(not isinstance(key,str) for key in order) or len(order)!=len(set(order))):
            raise UserError('Choose a valid waiting file-queue order')
        with self.lock:
            with self.store.transaction():
                current=self.file_queue_snapshot()
                if expected!=current:raise UserError('Waiting file queue changed; refresh and try again')
                if set(order)!={row['id'] for row in current}:raise UserError('Reorder only the current waiting file operations')
                self.store.put('settings','file-queue-order:global',dict(ids=order,updated=now()))
        return dict(waiting=len(order))

    def recover_file_jobs(self):
        with self.store.transaction():
            for record in self.file_jobs():
                if record['phase'] in {'waiting','running'}:
                    record.update(phase='interrupted',error='Restarted: inspect retained files before explicit recovery',updated=now())
                    self.store.put('settings',record['id'],record)

    def file_queue_paused(self):
        return bool(self.store.get('settings',self.pause_key(None,'file_operations'),False))

    def queue_file_operation(self,operation,payload,background=False):
        if operation not in {'publish','cleanup','restore_cleanup','repair','file_task','restore_rename','archive_artwork','archive_portrait','local_artwork'}:
            raise UserError('Unsupported file operation')
        task=self.get_task(payload['task']) if 'task' in payload else None
        local=operation=='local_artwork'
        profile=self.store.get('settings','cast_profiles',{}).get(payload.get('profile')) if operation=='archive_portrait' else None
        if operation=='archive_portrait' and (not profile or profile['revision']!=payload.get('revision')):raise UserError('Person portrait changed')
        job=dict(id='file-operation:'+uuid.uuid4().hex,record_type='file_operation',operation=operation,payload=payload,
                 library=payload.get('library') if local else task['library'] if task else None if profile else self.cleanup_receipt(payload['receipt'])['library'],
                 title=payload['title'] if local else task.get('title',operation) if task else profile['name'] if profile else 'Clean up originals',phase='waiting',synchronous=not background,created=now(),updated=now())
        with self.store.transaction():self.store.put('settings',job['id'],job)
        self.start_file_queue()
        if background:return job
        while True:
            with self.lock:current=self.store.get('settings',job['id'])
            if current['phase'] not in {'waiting','running'}:break
            threading.Event().wait(.05)
        if current['phase']!='complete':
            with self.lock:error=self.file_errors.pop(job['id'],None)
            if error is not None:raise error
            raise UserError(current.get('error','File operation needs inspection'))
        if operation=='cleanup':return self.cleanup_receipt(payload['receipt'])
        return self.get_task(payload['task'])

    def start_file_queue(self,resume=False):
        threads=[]
        with self.lock:
            if resume:
                with self.store.transaction():self.store.put('settings',self.pause_key(None,'file_operations'),False)
            waiting=sum(j['phase']=='waiting' for j in self.file_jobs())
            if self.file_queue_paused() or not waiting:return
            for _ in range(min(waiting,max(0,self.queue_limits().get('file_operations',4)-len(self.file_workers)))):
                wake=threading.Event();self.file_workers[wake]=True;threads.append(wake)
            if self.file_workers:self.active.add('file-queue')
        for wake in threads:threading.Thread(target=self._run_file_queue,args=(wake,),daemon=True).start()

    def _run_file_queue(self,wake):
        try:
            while True:
                with self.lock:
                    limit=self.queue_limits().get('file_operations',4)
                    if wake not in self.file_workers or list(self.file_workers).index(wake)>=limit or self.file_queue_paused():
                        self._release_file_worker(wake);return
                    with self.store.transaction():
                        jobs=self.file_jobs();waiting=[j for j in jobs if j['phase']=='waiting']
                        if not waiting:self._release_file_worker(wake);return
                        if sum(j['phase']=='running' for j in jobs)>=limit:job=None
                        else:
                            job=waiting[0];job.update(phase='running',updated=now());self.store.put('settings',job['id'],job)
                if job is None:wake.wait(.1);wake.clear();continue
                try:
                    self._execute_file_operation(job)
                    job.update(phase='complete',updated=now())
                except Exception as error:
                    log.exception('File operation %s failed', job['operation'])
                    job.update(phase='failed',updated=now(),error=str(error)[:300] if isinstance(error, UserError) else 'File operation failed; inspect retained files')
                    if job.get('synchronous'):
                        with self.lock:self.file_errors[job['id']]=error
                    if job['operation']=='archive_portrait':
                        with self.store.transaction():
                            profiles=self.store.get('settings','cast_profiles',{})
                            if job['payload']['profile'] in profiles:
                                profiles[job['payload']['profile']]['archive_error']=job['error']
                                self.store.put('settings','cast_profiles',profiles)
                    if job['operation']=='archive_artwork':
                        with self.store.transaction():
                            owner=self.get_task(job['payload']['task']);owner.update(archive_error=job['error'],updated=now());self.store.put('tasks',owner['id'],owner)
                    if job['operation']=='publish':
                        task=self.get_task(job['payload']['task'])
                        if task['status']=='publishing':self._save(task,status='blocked',error=job['error'])
                with self.lock:
                    with self.store.transaction():
                        self.store.put('settings',job['id'],job);self.refresh_run_receipts()
                    if not any(j['phase']=='waiting' for j in self.file_jobs()):
                        self._release_file_worker(wake);return
        finally:
            self._release_file_worker(wake)

    def _release_file_worker(self,wake):
        with self.lock:
            self.file_workers.pop(wake,None)
            if not self.file_workers:self.active.discard('file-queue')

    def _execute_file_operation(self,job):
        payload=job['payload'];operation=job['operation']
        if operation=='local_artwork':job['result']=self.render_local_artwork(payload)
        elif operation=='publish':
            task=self.get_task(payload['task'])
            if task['version']!=payload['version'] or task['status']!='publishing':raise UserError('Publication task changed while waiting')
            asset=self.asset(task,check=task['kind'] not in {'artwork','portrait'})
            result=self._finish_review(task,asset,False)
            if result['status']!='applied':raise UserError(result.get('error','Publication needs inspection'))
        elif operation=='cleanup':
            identity=payload['receipt']
            with self.lock:
                with self.store.transaction():
                    record=self.cleanup_receipt(identity)
                    if record['phase']!='queued':raise UserError('Cleanup receipt changed while waiting')
                    record.update(phase='deleting',updated=now());self.store.put('settings',identity,record)
                self.active.add(identity)
            self._delete_backup_batch(identity)
        elif operation=='restore_cleanup':self.restore_cleanup_backup(payload['task'],allow_active=True)
        elif operation=='repair':self._repair_quicktime(payload['task'],payload['version'])
        elif operation=='restore_rename':self._restore_rename(payload['task'],payload['version'])
        elif operation=='archive_portrait':self.archive_portrait(payload['profile'],payload['revision'])
        elif operation=='archive_artwork':
            task=self.get_task(payload['task'])
            if task['version']!=payload['version']:raise UserError('Artwork archive task changed')
            self.archive_artwork_task(task)
        elif operation=='file_task':self.execute_file_task(self.get_task(payload['task']))
