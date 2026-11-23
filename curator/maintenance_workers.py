"""Maintenance-only scopes on the existing ordered/concurrency-limited workers."""

from .history import acting
from .rules import scheduling_kind


class MaintenanceWorkers:
    def start_pending_maintenance(self, kind=None):
        threads = []
        with self.lock:
            groups = {}
            for task in self.waiting_tasks():
                task_kind = scheduling_kind(task['kind'])
                if not task.get('maintenance') or kind is not None and task_kind != kind:
                    continue
                if self.store.get('settings', self.pause_key(None, task_kind), False) or self.maintenance_holds(task):
                    continue
                groups.setdefault((task_kind, task['library']), []).append(task)
            for (task_kind, library), tasks in groups.items():
                workers = self.queue_workers.get(task_kind, {})
                assigned = sum(worker.get('library') in {None, library} for worker in workers.values())
                count = max(0, len(tasks) - assigned)
                if count:
                    threads.extend(self._fill_queue_workers(task_kind, library, maintenance_only=True, count=count))
                    if self.queue_workers.get(task_kind):
                        self.active.add('queue:' + task_kind)
        self._launch_queue_workers(threads)
        return [kind for library, kind, wake in threads]

    def execute_queued_with_maintenance(self, key, **kwargs):
        task = self.get_task(key)
        if not task.get('maintenance'):
            return self._execute(key, **kwargs)
        with acting('rule'):
            try:
                return self._execute(key, **kwargs)
            finally:
                current = self.get_task(key)
                if current['status'] not in {'queued', 'running'}:
                    self.finish_maintenance_task(current)
