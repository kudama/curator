"""Coordinate a supervised, idle-only restart without replaying work."""

from . import development
from contextlib import contextmanager
import os
import socket
import threading
import uuid
from .build import RUNNING_BUILD
from .errors import UserError


RESTART_EXIT_CODE = 75


class RestartBlocked(UserError):
    pass


class Restarting(Exception):
    pass


class ServiceRuntime:
    def __init__(self, service, managed=False):
        self.service = service
        self.managed = managed
        self.environment = 'development' if development.root() else 'production'
        self.instance_id = uuid.uuid4().hex
        self.hostname = socket.gethostname()
        self.build = dict(RUNNING_BUILD)
        self.condition = threading.Condition()
        self.requests = 0
        self.mutations = 0
        self.restart_requested = False
        self.restart_error = None

    @contextmanager
    def request(self, mutate=False):
        with self.condition:
            if self.restart_requested:
                raise Restarting()
            self.requests += 1
            self.mutations += int(mutate)
        try:
            yield
        finally:
            with self.condition:
                self.requests -= 1
                self.mutations -= int(mutate)
                self.condition.notify_all()

    def busy_reason(self):
        if self.service.active:
            return 'A processing queue is running.'
        if any(item.get('running') for item in tuple(self.service.scan_status.values())):
            return 'A library scan is running.'
        if any(item.get('running') for item in tuple(self.service.presence_status.values())):
            return 'A file availability check is running.'
        if any(task['status'] in {'running', 'publishing'} for task in self.service.store.all('tasks')):
            return 'A task is processing or publishing.'
        return None

    def status(self):
        with self.condition:
            return {
                'environment': self.environment,
                'restart_available': self.managed,
                'restarting': self.restart_requested,
                'instance_id': self.instance_id,
                'hostname': self.hostname,
                'startup': ('boot' if os.environ.get('CURATOR_SERVICE_STARTUP') == 'boot' else 'after_login')
                if self.managed
                else 'manual',
                'busy_reason': self.busy_reason(),
                'restart_error': self.restart_error,
                'build': dict(self.build),
                'capabilities': [
                    'bulk_review',
                    'backup_cleanup',
                    'encoding_controls',
                    'queue_order',
                    'task_queues',
                    'universal_queue',
                    'bulk_decisions',
                    'continuous_review',
                    'unattended_runs',
                ],
            }

    def request_restart(self):
        with self.condition:
            if not self.managed:
                raise RestartBlocked('Restart is available when Curator runs as the managed service.')
            if self.restart_requested:
                raise RestartBlocked('A restart is already pending.')
            if self.mutations > 1:
                raise RestartBlocked('Another request is changing data; wait and retry.')
            reason = self.busy_reason()
            if reason:
                raise RestartBlocked(reason + ' Finish active work before restarting.')
            self.restart_requested = True
            self.restart_error = None
            return {'accepted': True, 'instance_id': self.instance_id}

    def wait_for_idle(self, timeout=30):
        with self.condition:
            return self.condition.wait_for(lambda: self.requests == 0, timeout)

    def cancel_restart(self):
        with self.condition:
            self.restart_requested = False
            self.restart_error = 'Restart paused because a request did not finish. Wait and retry.'
