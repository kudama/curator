"""Bounded task-type workers over a shared, persistent waiting queue."""

import threading
import time
from .queue_workflows import SourceBusy
from .errors import UserError


class TaskQueues:
    @staticmethod
    def pause_key(library, kind):
        return 'queue-paused:global:' + kind

    def queue_limits(self):
        return self.store.get('settings', 'queue-limits', {})

    def queue_limit(self, kind):
        return self.queue_limits().get(kind, 4 if kind == 'file_operations' else 1)

    def set_queue_limits(self, limits):
        kinds = {
            'upscale',
            'optimize',
            'home',
            'metadata',
            'folder_metadata',
            'playlist',
            'join',
            'rename',
            'group',
            'mage_generation',
            'file_operations',
        }
        if (
            not isinstance(limits, dict)
            or set(limits) - kinds
            or any(type(v) is not int or not 1 <= v <= (4 if k == 'file_operations' else 8) for k, v in limits.items())
        ):
            raise UserError('Choose 1–8 processing jobs per type, or 1–4 file operations')
        threads = []
        with self.lock:
            with self.store.transaction():
                saved = self.queue_limits()
                saved.update(limits)
                self.store.put('settings', 'queue-limits', saved)
            # Only already active, unpaused queues gain workers. Never start a
            # stopped queue merely because its configured capacity changed.
            for kind, workers in list(self.queue_workers.items()):
                for worker in workers.values():
                    worker['wake'].set()
                if workers and not self.store.get('settings', self.pause_key(None, kind), False):
                    threads.extend(self._fill_queue_workers(kind, next(iter(workers.values()))['library']))
            for wake in self.file_workers:
                wake.set()
        self._launch_queue_workers(threads)
        return self.queue_limits()

    def task_queues(self, tasks, libraries):
        with self.lock:
            kinds = {t['kind'] for t in tasks if t['status'] in {'queued', 'running'} and not t.get('deleted')} | set(
                self.queue_workers
            )
            return [
                dict(
                    library=None,
                    kind=kind,
                    active=bool(self.queue_workers.get(kind)),
                    busy_elsewhere=False,
                    paused=bool(self.store.get('settings', self.pause_key(None, kind), False)),
                    limit=self.queue_limit(kind),
                    waiting=sum(t['kind'] == kind and t['status'] == 'queued' and not t.get('deleted') for t in tasks),
                    running=sum(t['kind'] == kind and t['status'] == 'running' and not t.get('deleted') for t in tasks),
                    waiting_for_source=any(
                        w.get('waiting_for_source') for w in self.queue_workers.get(kind, {}).values()
                    ),
                    waiting_for_retry=any(
                        w.get('waiting_for_retry') for w in self.queue_workers.get(kind, {}).values()
                    ),
                )
                for kind in sorted(kinds)
            ]

    def start(self, library=None, kind=None):
        if library is not None:
            self.library(library)
        files = (
            library is None
            and (kind is None or kind == 'file_operations')
            and any(j['phase'] == 'waiting' for j in self.file_jobs())
        )
        if kind == 'file_operations':
            self.create_run_receipt(library, kind)
            self.start_file_queue(resume=True)
            return dict(started=['file_operations'], busy=[])
        threads = []
        started = []
        busy = []
        with self.lock:
            kinds = {t['kind'] for t in self.waiting_tasks(library)}
            if kind is not None:
                if not isinstance(kind, str) or kind not in kinds:
                    raise UserError('No waiting jobs in this task-type queue')
                kinds = {kind}
            if not kinds and not files:
                raise UserError('No waiting jobs to run')
            with self.store.transaction():
                for task_kind in sorted(kinds):
                    workers = self.queue_workers.setdefault(task_kind, {})
                    if library is None:
                        for worker in workers.values():
                            worker['library'] = None
                    elif workers and all(w['library'] not in {None, library} for w in workers.values()):
                        busy.append(task_kind)
                        continue
                    self.store.put('settings', self.pause_key(None, task_kind), False)
                    for worker in workers.values():
                        worker['wake'].set()
                    threads.extend(self._fill_queue_workers(task_kind, library))
                    self.active.add('queue:' + task_kind)
                    started.append(task_kind)
        if started or files:
            self.create_run_receipt(library, kind)
        self._launch_queue_workers(threads)
        if files:
            self.start_file_queue(resume=True)
            started.append('file_operations')
        return dict(started=started, busy=busy)

    def _fill_queue_workers(self, kind, library):
        """Called under self.lock; register slots before threads can claim work."""
        workers = self.queue_workers.setdefault(kind, {})
        threads = []
        for _ in range(max(0, self.queue_limit(kind) - len(workers))):
            wake = threading.Event()
            workers[wake] = dict(library=library, wake=wake)
            threads.append((library, kind, wake))
        return threads

    def _launch_queue_workers(self, threads):
        for library, kind, wake in threads:
            threading.Thread(target=self._run, args=(library, kind, wake), daemon=True).start()

    def pause_queues(self, library=None, kind=None):
        if library is not None:
            self.library(library)
        with self.lock:
            kinds = {t['kind'] for t in self.waiting_tasks(library)} | set(self.queue_workers)
            if library is None and any(j['phase'] in {'waiting', 'running'} for j in self.file_jobs()):
                kinds.add('file_operations')
            if kind is not None:
                if not isinstance(kind, str) or kind not in kinds:
                    raise UserError('Task-type queue unavailable')
                kinds = {kind}
            with self.store.transaction():
                for task_kind in kinds:
                    self.store.put('settings', self.pause_key(None, task_kind), True)
            for task_kind in kinds:
                for worker in self.queue_workers.get(task_kind, {}).values():
                    worker['wake'].set()
            for wake in self.file_workers:
                wake.set()
        return dict(pausing=sorted(kinds))

    def next_waiting(self, library, kind):
        for task in self.waiting_tasks(library, kind=kind):
            if (task.get('retry_at') or 0) > time.time():
                continue
            try:
                self.check_busy_sources(task)
            except SourceBusy:
                continue
            return task
        return None

    def _run(self, library, kind=None, wake=None):
        try:
            while True:
                with self.lock:
                    if kind is not None:
                        workers = self.queue_workers.get(kind, {})
                        worker = workers.get(wake)
                        if worker is None:
                            return
                        library = worker['library']
                        if list(workers).index(wake) >= self.queue_limit(kind) or self.store.get(
                            'settings', self.pause_key(None, kind), False
                        ):
                            self._release_queue_worker(library, kind, wake)
                            return
                    waiting = self.waiting_tasks(library, kind=kind)
                    if not waiting and not (
                        kind is not None and any(w.get('executing') for w in workers.values())
                    ):
                        self._release_queue_worker(library, kind, wake)
                        return
                    task = self.next_waiting(library, kind) if kind is not None else waiting[0]
                    if kind is not None:
                        worker['waiting_for_retry'] = task is None and any(
                            (t.get('retry_at') or 0) > time.time() for t in waiting
                        )
                        worker['waiting_for_source'] = bool(waiting) and task is None and not worker['waiting_for_retry']
                        worker['executing'] = task is not None
                if task is None:
                    wake.wait(0.2)
                    wake.clear()
                    continue
                try:
                    result = self._execute(
                        task['id'],
                        queue_head=True,
                        **({'queue_kind': kind, 'queue_library': library, 'queue_wake': wake} if kind is not None else {}),
                    )
                finally:
                    if kind is not None:
                        with self.lock:
                            worker['executing'] = False
                            for slot in self.queue_workers.get(kind, {}).values():
                                slot['wake'].set()
                if result == 'capacity_busy':
                    wake.wait(0.2)
                    wake.clear()
        finally:
            self._release_queue_worker(library, kind, wake)

    def _release_queue_worker(self, library, kind, wake):
        with self.lock:
            if kind is None:
                self.active.discard(library)
                return
            workers = self.queue_workers.get(kind)
            if workers is None or wake not in workers:
                return
            workers.pop(wake)
            if not workers:
                self.queue_workers.pop(kind, None)
                self.active.discard('queue:' + kind)
                with self.store.transaction():
                    self.refresh_run_receipts()
