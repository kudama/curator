"""Lazy explicit Scan cadence; no startup, Home or presence refresh permission."""

import threading

from .errors import UserError
from .history import acting
from .maintenance_policy import permitted
from .store import now


class MaintenanceScheduler:
    def ensure_maintenance_scheduler(self):
        from .maintenance import POLICY_ACCEPTED

        with self.lock:
            if not POLICY_ACCEPTED or not any(rule.get('enabled') for rule in self.maintenance_rules()):
                return
            if self.maintenance_scheduler_thread and self.maintenance_scheduler_thread.is_alive():
                return
            self.maintenance_scheduler_stop.clear()
            self.maintenance_scheduler_thread = threading.Thread(
                target=self._maintenance_schedule_loop, daemon=True, name='curator-approved-arrivals'
            )
            self.maintenance_scheduler_thread.start()

    def stop_maintenance_scheduler(self):
        with self.lock:
            self.maintenance_scheduler_stop.set()
        if self.maintenance_scheduler_thread:
            self.maintenance_scheduler_thread.join(timeout=1)

    def _maintenance_schedule_loop(self):
        while not self.maintenance_scheduler_stop.is_set():
            try:
                self.maintenance_tick()
            except Exception:
                from .logs import log

                log.exception('Maintenance scheduler stopped this tick; no implicit replay')
            self.maintenance_scheduler_stop.wait(30)

    def maintenance_tick(self):
        from .maintenance import POLICY_ACCEPTED

        if not POLICY_ACCEPTED or self.maintenance_scheduler_stop.is_set():
            return []
        admitted = []
        with acting('rule'):
            for previous in self.maintenance_rules():
                with self.lock:
                    if self.maintenance_scheduler_stop.is_set():
                        break
                    rule = self.maintenance_rule(previous['id'])
                    if (
                        not rule.get('enabled')
                        or rule.get('paused')
                        or rule['values']['action'] != 'scan'
                        or self.maintenance_paused(rule['values']['library'])
                        or self.file_queue_paused()
                        or not permitted(rule['values'], self.maintenance_clock())
                    ):
                        continue
                    try:
                        run = self.admit_maintenance_scan(rule['id'])
                        if run:
                            admitted.append(run['id'])
                    except UserError as error:
                        with self.store.transaction():
                            rule.update(paused=True, last_exception=str(error)[:300], updated=now())
                            self.store.put('settings', rule['id'], rule)
                            self.store.record(
                                'maintenance_exception',
                                'Scan scheduling held for review',
                                library=rule['values']['library'],
                                details={'rule': rule['id'], 'error': str(error)[:300]},
                                level='warning',
                            )
            with self.lock:
                if not self.maintenance_scheduler_stop.is_set():
                    self.start_file_queue(maintenance_only=True)
                    self.start_pending_maintenance()
        return admitted

    def recover_maintenance_scans(self):
        with self.lock, self.store.transaction():
            for row in self.store.all('settings'):
                if not isinstance(row, dict):
                    continue
                if row.get('record_type') == 'maintenance_scan' and row.get('phase') in {'queued', 'running', 'paused'}:
                    row.update(
                        phase='interrupted',
                        error='Restarted scan held; no queued observation/probe replay',
                        updated=now(),
                    )
                    self.store.put('settings', row['id'], row)
                if row.get('record_type') == 'maintenance_claim' and row.get('phase') == 'probe_attempted':
                    row.update(phase='uncertain', updated=now())
                    self.store.put('settings', row['id'], row)
                    rule = self.maintenance_rule(row['rule'])
                    rule.update(
                        paused=True,
                        last_exception='Interrupted probe: inspect retained bounded output; no automatic replay',
                        updated=now(),
                    )
                    self.store.put('settings', rule['id'], rule)
