"""Default-disabled new-arrival rules, immutable opt-ins and revocation.

The pure policy, standard-facts adapter and execution dispatcher are separate.
Accepting this engineering implementation never enables a live rule.
"""

import copy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import socket
import uuid
from zoneinfo import ZoneInfo

from .errors import UserError
from .history import current_initiator
from .maintenance_policy import POLICY_VERSION, PROCESSING, digest, limits, rule_values
from .maintenance_facts import standard_identity
from .store import now

# The policy/configuration review gate is separate from each rule's standing
# permission. Tests may accept the contract only in disposable synthetic state.
POLICY_ACCEPTED = False


def operator():
    if current_initiator() != 'operator':
        raise UserError('Only an explicit operator action can change maintenance permissions')


class MaintenanceRules:
    def maintenance_clock(self):
        return datetime.now(timezone.utc)

    def maintenance_rules(self):
        return [
            row
            for row in self.store.all('settings')
            if isinstance(row, dict) and row.get('record_type') == 'maintenance_rule'
        ]

    def maintenance_rule(self, identity):
        row = self.store.get('settings', identity)
        if not isinstance(row, dict) or row.get('record_type') != 'maintenance_rule':
            raise UserError('Maintenance rule was not found')
        return row

    def maintenance_caps(self, library=None):
        key = 'maintenance-caps:' + ('library:' + library if library is not None else 'machine')
        return self.store.get('settings', key)

    def save_maintenance_caps(self, library, revision, value):
        operator()
        if library is not None:
            self.library(library)
        if not isinstance(value, dict) or set(value) != {'limits', 'timezone'}:
            raise UserError('Specify finite aggregate limits and their named calendar timezone')
        try:
            ZoneInfo(value['timezone'])
        except (KeyError, TypeError, ValueError):
            raise UserError('Choose an installed named timezone for these aggregate limits') from None
        values = dict(limits=limits(value['limits']), timezone=value['timezone'])
        key = 'maintenance-caps:' + ('library:' + library if library is not None else 'machine')
        with self.lock, self.store.transaction():
            previous = self.maintenance_caps(library)
            if type(revision) is not int or revision != (previous or {}).get('revision', 0):
                raise UserError('Aggregate maintenance limits changed; reload before saving')
            if previous and previous['values'] == values:
                return previous
            record = dict(
                id=key,
                record_type='maintenance_caps',
                library=library,
                revision=revision + 1,
                values=values,
                approved_by='operator',
                updated=now(),
            )
            self.store.record(
                'maintenance_caps',
                'Maintenance aggregate limits changed; existing unstarted approvals require review',
                library=library,
                details={'revision': record['revision']},
            )
            self.store.put('settings', key, record)
            self.invalidate_maintenance_tasks(
                library=library, reason='Aggregate allowance changed; review a fresh maintenance permission'
            )
            return record

    def save_maintenance_rule(self, identity, revision, value):
        operator()
        values = rule_values(value)
        library = self.library(values['library'])
        mapped = {str(PurePosixPath(row['plex_root'])) for row in library.get('mappings', [])}
        if not set(values['roots']) <= mapped:
            raise UserError('Select only exact mapped roots in this library; new mappings need separate review')
        if any(
            not any(PurePosixPath(path).is_relative_to(PurePosixPath(root)) for root in values['roots'])
            for path in values['excluded_paths']
        ):
            raise UserError('Excluded folders must remain within this rule scope')
        with self.lock, self.store.transaction():
            previous = self.maintenance_rule(identity) if identity else None
            if type(revision) is not int or revision != (previous or {}).get('revision', 0):
                raise UserError('Maintenance rule changed; reload before saving')
            if previous and previous['values']['library'] != library['id']:
                raise UserError('A rule cannot move to another library; create a separate disabled rule')
            if previous and previous['values'] == values:
                return previous
            identity = identity or 'maintenance-rule:' + uuid.uuid4().hex
            record = dict(
                id=identity,
                record_type='maintenance_rule',
                revision=revision + 1,
                values=values,
                enabled=False,
                paused=True,
                approval=None,
                created=(previous or {}).get('created', now()),
                updated=now(),
            )
            self.store.record(
                'maintenance_rule',
                'Maintenance draft saved; it is disabled and grants no action',
                library=library['id'],
                details={'rule': identity, 'revision': record['revision'], 'action': values['action']},
            )
            self.store.put('settings', identity, record)
            self.invalidate_maintenance_tasks(
                rule=identity, reason='Rule changed; its previous standing permission was revoked'
            )
            return record

    def maintenance_scope(self, library):
        return {
            key: copy.deepcopy(library.get(key))
            for key in ('id', 'server', 'key', 'type', 'kind', 'agent', 'profile', 'mappings', 'themes')
        }

    def maintenance_contract(self):
        files = [path.name for path in sorted(Path(__file__).parent.glob('maintenance*.py'))] + ['limited_exec.py']
        return dict(
            policy=POLICY_VERSION,
            implementation=digest({name: Path(__file__).with_name(name).read_text() for name in files}),
        )

    def maintenance_enable_snapshot(self, rule, captured=None):
        if not POLICY_ACCEPTED:
            raise UserError('Maintenance policy/configuration review is pending; every rule remains disabled')
        library = self.library(rule['values']['library'])
        machine, aggregate = self.maintenance_caps(), self.maintenance_caps(library['id'])
        if not machine or not aggregate:
            raise UserError('Approve finite machine and shared library limits before enabling any rule')
        if rule['values']['timezone'] != aggregate['values']['timezone']:
            raise UserError('Rules sharing one library must use its approved accounting timezone')
        baseline = self.store.get('settings', 'maintenance-arrivals:' + library['id'])
        if not baseline or not baseline.get('completed_scan'):
            raise UserError('Complete an authoritative baseline scan before enabling new-arrival maintenance')
        return dict(
            contract=self.maintenance_contract(),
            rule=rule['id'],
            revision=rule['revision'],
            values=digest(rule['values']),
            library=self.maintenance_scope(library),
            standard=standard_identity(self, library['id']),
            caps=dict(machine=machine['revision'], library=aggregate['revision']),
            watermark=baseline['sequence'],
            baseline=baseline['generation'],
            connection=digest(self.config().get('plex_url')),
            tools=self.maintenance_tool_snapshot(rule['values'], captured=captured),
            output_bound=self.maintenance_output_bound(rule),
            queue_limit=self.queue_limit('upscale' if rule['values']['action'].endswith('upscale') else 'optimize')
            if rule['values']['action'] in PROCESSING
            else None,
            execution_host=dict(
                host=socket.gethostname(),
                state=str(self.store.root),
                device=self.store.root.stat().st_dev,
                inode=self.store.root.stat().st_ino,
            ),
        )

    def preview_maintenance_enable(self, identity, revision):
        operator()
        with self.lock:
            rule = self.maintenance_rule(identity)
            if type(revision) is not int or rule['revision'] != revision:
                raise UserError('Maintenance draft changed; reload before enabling')
            snapshot = self.maintenance_enable_snapshot(rule)
            record = dict(
                id='maintenance-enable:' + uuid.uuid4().hex,
                record_type='maintenance_enable',
                snapshot=snapshot,
                digest=digest(snapshot),
                created=now(),
                phase='review',
            )
            with self.store.transaction():
                self.store.put('settings', record['id'], record)
            return dict(
                preview=record['id'],
                digest=record['digest'],
                snapshot=snapshot,
                rule=rule,
                remaining_manual=[
                    'Metadata/cast saves',
                    'Artwork generation/publication',
                    'Output publication',
                    'File operations/cleanup',
                    'Provider spend',
                ],
                global_paused=self.maintenance_paused(rule['values']['library']),
            )

    def enable_maintenance_rule(self, identity, reviewed_digest, action):
        operator()
        with self.lock, self.store.transaction():
            preview = self.store.get('settings', identity, {})
            if (
                preview.get('record_type') != 'maintenance_enable'
                or preview.get('phase') != 'review'
                or preview.get('digest') != reviewed_digest
            ):
                raise UserError('Review a current maintenance enable preview')
            rule = self.maintenance_rule(preview['snapshot']['rule'])
            if rule['values']['action'] == 'scan' and any(
                other['id'] != rule['id']
                and other.get('enabled')
                and other['values']['library'] == rule['values']['library']
                and other['values']['action'] == 'scan'
                for other in self.maintenance_rules()
            ):
                raise UserError(
                    'This library already has an enabled Scan rule; edit/review that single schedule instead'
                )
            if (
                action != rule['values']['action']
                or self.maintenance_enable_snapshot(rule, captured=preview['snapshot']['tools']) != preview['snapshot']
            ):
                raise UserError('Rule/scope/standard/caps/baseline changed; prepare a fresh enable preview')
            stamp = now()
            rule.update(
                enabled=True,
                paused=False,
                approval=dict(
                    id=preview['id'],
                    digest=reviewed_digest,
                    snapshot=preview['snapshot'],
                    initiator='operator',
                    approved=stamp,
                ),
                updated=stamp,
            )
            preview.update(phase='approved', approved=stamp)
            self.store.record(
                'maintenance_enable',
                'Explicit per-action new-arrival maintenance permission enabled',
                library=rule['values']['library'],
                details={
                    'rule': rule['id'],
                    'revision': rule['revision'],
                    'action': action,
                    'watermark': preview['snapshot']['watermark'],
                },
            )
            self.store.put('settings', rule['id'], rule)
            self.store.put('settings', preview['id'], preview)
            return rule

    def maintenance_paused(self, library):
        return bool(
            self.store.get('settings', 'maintenance-paused:machine', True)
            or self.store.get('settings', 'maintenance-paused:' + library, False)
        )

    def change_maintenance_state(self, identity, revision, action):
        operator()
        if action not in {'pause', 'resume', 'disable'}:
            raise UserError('Choose pause, resume or disable')
        with self.lock, self.store.transaction():
            rule = self.maintenance_rule(identity)
            if type(revision) is not int or rule['revision'] != revision:
                raise UserError('Maintenance rule changed; reload before changing its state')
            if action == 'resume':
                if not rule.get('enabled') or not rule.get('approval'):
                    raise UserError('Review and enable this disabled rule explicitly')
                self.validate_maintenance_permission(rule)
                rule['paused'] = False
            else:
                rule['paused'] = True
                if action == 'disable':
                    rule.update(enabled=False, approval=None, revision=rule['revision'] + 1)
                    self.invalidate_maintenance_tasks(
                        rule=identity, reason='Standing permission was explicitly revoked'
                    )
            rule['updated'] = now()
            self.store.record(
                'maintenance_state',
                'Maintenance rule ' + action,
                library=rule['values']['library'],
                details={'rule': identity, 'revision': rule['revision']},
            )
            self.store.put('settings', identity, rule)
            return rule

    def pause_maintenance_scope(self, library, paused):
        operator()
        if library is not None:
            self.library(library)
        if type(paused) is not bool:
            raise UserError('Choose an explicit maintenance pause state')
        with self.lock, self.store.transaction():
            if not paused:
                for rule in self.maintenance_rules():
                    if rule.get('enabled') and (library is None or rule['values']['library'] == library):
                        self.validate_maintenance_permission(rule)
            self.store.record(
                'maintenance_pause',
                'Maintenance scope paused'
                if paused
                else 'Maintenance scope resumed; manual queue pauses are unchanged',
                library=library,
            )
            self.store.put('settings', 'maintenance-paused:' + (library or 'machine'), paused)
        return dict(paused=paused)

    def invalidate_maintenance_tasks(self, rule=None, library=None, reason='Maintenance approval changed'):
        # Caller owns the service lock and transaction; running work keeps its
        # already-approved separate-output step and original provenance.
        for task in self.store.all('tasks'):
            approval = task.get('maintenance')
            if (
                not approval
                or task['status'] != 'queued'
                or rule
                and approval['rule'] != rule
                or library
                and task['library'] != library
            ):
                continue
            task.update(status='blocked', approval=None, error=reason, version=task['version'] + 1, updated=now())
            self.store.put('tasks', task['id'], task)
            self.store.event(task['id'], dict(action='maintenance permission invalidated', rule=approval['rule']))

        for job in self.file_jobs():
            if job['operation'] != 'maintenance_scan' or job['phase'] != 'waiting':
                continue
            scan = self.maintenance_scan_run(job['payload']['run'])
            if (rule and scan['rule'] != rule) or (library and scan['library'] != library):
                continue
            scan.update(phase='revoked', error=reason, updated=now())
            job.update(phase='cancelled', error=reason, updated=now())
            self.store.put('settings', scan['id'], scan)
            self.store.put('settings', job['id'], job)
