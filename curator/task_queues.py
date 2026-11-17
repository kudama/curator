"""One processing worker per task type; pause only between claims."""
import threading


class TaskQueues:
    @staticmethod
    def pause_key(library, kind):
        return 'queue-paused:'+library+':'+kind

    def task_queues(self, tasks, libraries):
        with self.lock:workers={kind:dict(info) for kind,info in self.queue_workers.items()}
        result=[]
        for library in libraries:
            key=library['id'];rows=[t for t in tasks if t['library']==key and t['status'] in {'queued','running'} and not t.get('deleted')]
            kinds={t['kind'] for t in rows}|{kind for kind,w in workers.items() if w['library']==key}
            for kind in sorted(kinds):
                worker=workers.get(kind);owned=bool(worker and worker['library']==key)
                result.append(dict(library=key,kind=kind,active=owned,busy_elsewhere=bool(worker and not owned),
                    paused=bool(self.store.get('settings',self.pause_key(key,kind),False)),
                    waiting=sum(t['kind']==kind and t['status']=='queued' for t in rows),
                    running=sum(t['kind']==kind and t['status']=='running' for t in rows),
                    waiting_for_source=bool(owned and worker.get('waiting_for_source'))))
        return result

    def start(self, library, kind=None):
        self.library(library);threads=[];busy=[];started=[]
        with self.lock:
            waiting=self.waiting_tasks(library)
            kinds={t['kind'] for t in waiting}
            if kind is not None:
                if not isinstance(kind,str) or kind not in kinds:raise ValueError('No waiting jobs in this task-type queue')
                kinds={kind}
            if not kinds:raise ValueError('No waiting jobs to run')
            with self.store.transaction():
                for task_kind in sorted(kinds):
                    worker=self.queue_workers.get(task_kind)
                    if worker and worker['library']!=library:busy.append(task_kind);continue
                    self.store.put('settings',self.pause_key(library,task_kind),False)
                    if worker:worker['wake'].set();continue
                    wake=threading.Event();self.queue_workers[task_kind]=dict(library=library,wake=wake)
                    self.active.add('queue:'+task_kind);threads.append((task_kind,wake));started.append(task_kind)
        for task_kind,wake in threads:
            threading.Thread(target=self._run,args=(library,task_kind,wake),daemon=True).start()
        return dict(started=started,busy=busy)

    def pause_queues(self, library, kind=None):
        self.library(library)
        with self.lock:
            kinds={t['kind'] for t in self.waiting_tasks(library)}|{k for k,w in self.queue_workers.items() if w['library']==library}
            if kind is not None:
                if not isinstance(kind,str) or kind not in kinds:raise ValueError('Task-type queue unavailable')
                kinds={kind}
            with self.store.transaction():
                for task_kind in kinds:self.store.put('settings',self.pause_key(library,task_kind),True)
            for task_kind in kinds:
                worker=self.queue_workers.get(task_kind)
                if worker and worker['library']==library:worker['wake'].set()
        return dict(pausing=sorted(kinds))

    def _run(self, library, kind=None, wake=None):
        try:
            while True:
                with self.lock:
                    waiting=self.waiting_tasks(library,kind=kind)
                    if not waiting or (kind is not None and self.store.get('settings',self.pause_key(library,kind),False)):
                        self._release_queue_worker(library,kind,wake)
                        return
                result=self._execute(waiting[0]['id'],queue_head=True,**({'queue_kind':kind} if kind is not None else {}))
                if kind is not None:
                    with self.lock:
                        worker=self.queue_workers.get(kind)
                        if worker and worker['wake'] is wake:worker['waiting_for_source']=result=='source_busy'
                    if result=='source_busy':wake.wait(.5);wake.clear()
        finally:
            self._release_queue_worker(library,kind,wake)

    def _release_queue_worker(self,library,kind,wake):
        with self.lock:
            if kind is None:self.active.discard(library);return
            worker=self.queue_workers.get(kind)
            if worker and worker['wake'] is wake:
                self.queue_workers.pop(kind,None);self.active.discard('queue:'+kind)
