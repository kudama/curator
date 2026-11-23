"""Atomic shared maintenance allowance and source/action claims.

All reservations are conservative. Failed/uncertain actions keep their claims and
allowance; a revision or rule split cannot manufacture another automatic attempt.
"""

from datetime import datetime
import shutil
from zoneinfo import ZoneInfo

from .errors import UserError
from .maintenance_policy import PROCESSING, digest
from .store import now


def action_group(action):
    if action.endswith('upscale'):
        return 'upscale'
    if action.endswith('encode'):
        return 'optimize'
    return 'home' if action == 'local_ai' else 'scan'


class MaintenanceBudgets:
    def maintenance_allowances(self, rule):
        library = rule['values']['library']
        machine, aggregate = self.maintenance_caps(), self.maintenance_caps(library)
        if not machine or not aggregate:
            raise UserError('Machine and shared library maintenance allowances must both be approved')
        return [
            dict(scope='machine', **machine['values']),
            dict(scope='library:' + library, **aggregate['values']),
            dict(scope='rule:' + rule['id'], limits=rule['values']['limits'], timezone=rule['values']['timezone']),
        ]

    def maintenance_output_bound(self, rule):
        if rule['values']['action'] == 'scan':
            needed = 2 * rule['values']['options']['probe_output_bytes']
            if any(row['limits']['output_bytes_per_item'] < needed for row in self.maintenance_allowances(rule)):
                raise UserError('Scan stdout/stderr scratch bounds exceed a reviewed per-item allowance')
            return needed
        if rule['values']['action'] not in PROCESSING:
            return 0
        bound = min(row['limits']['output_bytes_per_item'] for row in self.maintenance_allowances(rule))
        if bound <= 0:
            raise UserError('Processing has no positive hard output-file allowance')
        return bound

    def reserve_maintenance(self, rule, arrival, task_id, standard, output_bound=None):
        """Caller holds service lock and one transaction covering task admission."""
        if not self.store.db.in_transaction:
            raise RuntimeError('Maintenance reservation must share the task-admission transaction')
        instant = self.maintenance_clock()
        clock = self.store.get('settings', 'maintenance-clock')
        if clock and instant < datetime.fromisoformat(clock['instant']):
            raise UserError('Clock moved backwards; maintenance allowance is held for review')
        group = action_group(rule['values']['action'])
        identity = 'maintenance-claim:' + digest((arrival['library'], arrival['id'], group))
        existing = self.store.get('settings', identity)
        if existing:
            raise UserError(
                'This arrival/action already has a retained maintenance attempt; review it instead of replaying'
            )
        bound = self.maintenance_output_bound(rule)
        if output_bound is not None:
            if type(output_bound) is not int or not 0 <= output_bound <= bound:
                raise UserError('Invalid bounded maintenance reservation')
            bound = output_bound
        storage_bound = bound * (2 if rule['values']['action'] in PROCESSING else 1)
        scopes = self.maintenance_allowances(rule)
        reserved = sum(
            row.get('storage_bound', row.get('output_bound', 0))
            for row in self.store.all('settings')
            if isinstance(row, dict)
            and row.get('record_type') == 'maintenance_claim'
            and row.get('phase') in {'reserved', 'attempted', 'probe_attempted'}
        )
        if (
            shutil.disk_usage(self.store.root).free
            < max(row['limits']['min_free_bytes'] for row in scopes) + reserved + storage_bound
        ):
            raise UserError('Available output space is below the approved reserve; no maintenance job admitted')
        run = (arrival['library'], arrival['last_sequence'])
        rows = []
        for scope in scopes:
            day = instant.astimezone(ZoneInfo(scope['timezone'])).date().isoformat()
            daily_id = 'maintenance-day:' + digest((scope['scope'], day))
            run_id = 'maintenance-run:' + digest((scope['scope'], run))
            daily = self.store.get(
                'settings',
                daily_id,
                dict(
                    id=daily_id, record_type='maintenance_usage', scope=scope['scope'], day=day, items=0, output_bytes=0
                ),
            )
            running = self.store.get(
                'settings', run_id, dict(id=run_id, record_type='maintenance_run_usage', scope=scope['scope'], items=0)
            )
            cap = scope['limits']
            if (
                daily['items'] + 1 > cap['items_per_day']
                or running['items'] + 1 > cap['items_per_run']
                or daily['output_bytes'] + bound > cap['output_bytes_per_day']
            ):
                raise UserError(
                    'Shared maintenance item/output allowance is exhausted; review limits or wait for a permitted day'
                )
            rows.append((daily, running))
        claim = dict(
            id=identity,
            record_type='maintenance_claim',
            library=arrival['library'],
            arrival=arrival['id'],
            rule=rule['id'],
            rule_revision=rule['revision'],
            action=rule['values']['action'],
            group=group,
            standard=standard,
            options=digest(rule['values']['options']),
            task=task_id,
            source=arrival['fingerprint'],
            output_bound=bound,
            storage_bound=storage_bound,
            phase='reserved',
            approved_by=rule['approval']['initiator'],
            standing_approval=rule['approval']['id'],
            initiator='rule',
            created=now(),
            updated=now(),
            allocations={daily['scope']: daily['id'] for daily, running in rows},
        )
        self.store.record(
            'maintenance_reservation',
            'Bounded arrival action and shared allowance reserved',
            library=arrival['library'],
            details={
                'claim': identity,
                'rule': rule['id'],
                'revision': rule['revision'],
                'action': claim['action'],
                'output_bytes': bound,
            },
        )
        for daily, running in rows:
            daily.update(items=daily['items'] + 1, output_bytes=daily['output_bytes'] + bound, updated=now())
            running.update(items=running['items'] + 1, updated=now())
            self.store.put('settings', daily['id'], daily)
            self.store.put('settings', running['id'], running)
        self.store.put('settings', identity, claim)
        self.store.put('settings', 'maintenance-clock', dict(instant=instant.isoformat()))
        return claim

    def maintenance_start_allowance(self, claim, rule):
        """Recheck free space and charge a newly crossed calendar day before exec.

        Old reservations stay consumed conservatively; changing the clock or
        waiting across midnight cannot create an unaccounted new processing start.
        Caller owns the start/revoke lock and its pre-exec audit transaction.
        """
        instant = self.maintenance_clock()
        clock = self.store.get('settings', 'maintenance-clock')
        if clock and instant < datetime.fromisoformat(clock['instant']):
            raise UserError('Clock moved backwards; do not start maintenance until its allowance is reconciled')
        scopes = self.maintenance_allowances(rule)
        reserved = sum(
            row.get('storage_bound', row.get('output_bound', 0))
            for row in self.store.all('settings')
            if isinstance(row, dict)
            and row.get('record_type') == 'maintenance_claim'
            and row.get('phase') in {'reserved', 'attempted', 'probe_attempted'}
        )
        if shutil.disk_usage(self.store.root).free < max(row['limits']['min_free_bytes'] for row in scopes) + reserved:
            raise UserError('Output free-space reserve is no longer available; no tool started')
        for scope in scopes:
            day = instant.astimezone(ZoneInfo(scope['timezone'])).date().isoformat()
            key = 'maintenance-day:' + digest((scope['scope'], day))
            if claim.get('allocations', {}).get(scope['scope']) == key:
                continue
            row = self.store.get(
                'settings',
                key,
                dict(id=key, record_type='maintenance_usage', scope=scope['scope'], day=day, items=0, output_bytes=0),
            )
            if (
                row['items'] + 1 > scope['limits']['items_per_day']
                or row['output_bytes'] + claim['output_bound'] > scope['limits']['output_bytes_per_day']
            ):
                raise UserError('The new calendar day has no shared allowance for this delayed start')
            row.update(items=row['items'] + 1, output_bytes=row['output_bytes'] + claim['output_bound'], updated=now())
            self.store.put('settings', key, row)
            claim.setdefault('allocations', {})[scope['scope']] = key
        self.store.put('settings', 'maintenance-clock', dict(instant=instant.isoformat()))
        return claim
