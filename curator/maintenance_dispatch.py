"""New-arrival admission into existing tasks; no publication/file/provider grants."""

import copy

from .errors import UserError
from .history import acting
from .maintenance_budget import action_group
from .maintenance_facts import evaluated, finding_for
from .maintenance_policy import PREPARATION, PROCESSING, digest, excluded, permitted
from .rules import stable_id
from .store import now
from . import tools


class MaintenanceHeld(UserError):
    """Known not-started work may wait; never replay an attempted subprocess."""


class MaintenanceDispatch:
    def maintenance_holds(self, task):
        """Cheap selection guard. Full immutable/source/tool checks precede start."""
        permission = task.get('maintenance')
        if not permission:
            return False
        try:
            rule = self.maintenance_rule(permission['rule'])
            return bool(
                rule.get('paused')
                or self.maintenance_paused(task['library'])
                or not permitted(rule['values'], self.maintenance_clock())
            )
        except Exception:
            # Select corrupt/stale records for the full preflight to block with
            # an inspectable task result, rather than stranding a worker loop.
            return False

    def maintenance_start_guard(self, task, starting=False):
        permission = task.get('maintenance')
        if not permission:
            raise UserError('This task has no standing maintenance approval')
        current_task = self.get_task(task['id'])
        if (
            current_task['version'] != task['version']
            or current_task.get('maintenance') != permission
            or current_task['status'] not in ({'running'} if starting else {'queued', 'running'})
            or task['id'] in self.cancels
        ):
            raise UserError('Maintenance task ownership changed or the task was cancelled')
        rule = self.maintenance_rule(permission['rule'])
        snapshot = self.validate_maintenance_permission(rule)
        if rule['revision'] != permission['revision'] or rule['approval']['id'] != permission['approval']:
            raise UserError('This queued maintenance permission was superseded')
        if self.maintenance_holds(task) or self.store.get('settings', self.pause_key(None, task['kind']), False):
            raise MaintenanceHeld('Maintenance or the task queue is paused/outside its permitted window')
        if rule['values']['action'] not in PROCESSING or action_group(rule['values']['action']) != task['kind']:
            raise UserError('This standing action does not authorize subprocess execution')
        claim = self.store.get('settings', permission['claim'], {})
        if (
            claim.get('phase') != 'reserved'
            or claim.get('task') != task['id']
            or claim.get('rule_revision') != rule['revision']
        ):
            raise UserError('Maintenance outcome is no longer unstarted; inspect its retained receipt')
        asset = self.asset(task)
        facts = evaluated(self, asset)
        if (
            facts['standard'] != snapshot['standard']
            or asset['fingerprint'] != permission['source']
            or excluded(rule['values'], asset)
        ):
            raise UserError('Source, scope or effective standard changed since standing approval')
        if finding_for(rule['values']['action'], facts) is None:
            raise UserError('This source no longer requires the approved processing action')
        if digest(task.get('tool_settings')) != permission['tool_settings']:
            raise UserError('Queued processing options changed since maintenance admission')
        return claim

    def maintenance_decision(self, rule, arrival, phase, reason, task=None):
        key = 'maintenance-decision:' + digest((rule['id'], rule['revision'], arrival['id']))
        row = dict(
            id=key,
            record_type='maintenance_decision',
            library=arrival['library'],
            rule=rule['id'],
            revision=rule['revision'],
            arrival=arrival['id'],
            phase=phase,
            reason=reason,
            task=task,
            updated=now(),
        )
        self.store.put('settings', key, row)
        self.store.record(
            'maintenance_decision',
            reason,
            library=arrival['library'],
            level='warning' if phase == 'exception' else 'info',
            details={
                'rule': rule['id'],
                'revision': rule['revision'],
                'arrival': arrival['id'],
                'phase': phase,
                'task': task,
            },
        )
        return row

    def dispatch_maintenance(self, library):
        results = []
        if self.maintenance_paused(library):
            return results
        for arrival in self.maintenance_arrivals(library):
            if arrival.get('phase') != 'ready':
                continue
            for record in self.maintenance_rules():
                if record['values']['library'] != library or not record.get('enabled') or record.get('paused'):
                    continue
                with self.lock, acting('rule'):
                    rule = self.maintenance_rule(record['id'])
                    if self.maintenance_paused(library) or rule.get('paused') or not rule.get('enabled'):
                        continue
                    decision_id = 'maintenance-decision:' + digest((rule['id'], rule['revision'], arrival['id']))
                    if self.store.get('settings', decision_id):
                        continue
                    snapshot = (rule.get('approval') or {}).get('snapshot')
                    if (
                        not snapshot
                        or arrival['generation'] != snapshot.get('baseline')
                        or arrival['first_sequence'] <= snapshot['watermark']
                    ):
                        continue
                    if not permitted(rule['values'], self.maintenance_clock()):
                        continue
                    try:
                        self.validate_maintenance_permission(rule)
                        asset = self.asset({'asset': arrival['asset']})
                        if asset['fingerprint'] != arrival['fingerprint']:
                            raise UserError('Arrival source changed after its stable scan; inspect it before retrying')
                        if excluded(rule['values'], asset):
                            with self.store.transaction():
                                results.append(
                                    self.maintenance_decision(
                                        rule, arrival, 'skipped', 'Arrival is outside the approved roots or excluded'
                                    )
                                )
                            continue
                        facts = evaluated(self, asset)
                        finding = finding_for(rule['values']['action'], facts)
                        if finding is None:
                            with self.store.transaction():
                                results.append(
                                    self.maintenance_decision(
                                        rule, arrival, 'skipped', 'Arrival already meets the action-relevant standard'
                                    )
                                )
                            continue
                        if rule['values']['action'] == 'scan' and arrival.get('scan_claim'):
                            with self.store.transaction():
                                results.append(
                                    self.maintenance_decision(
                                        rule,
                                        arrival,
                                        'complete',
                                        'This new arrival was already assessed by its reserved bounded Scan probe',
                                    )
                                )
                            continue
                        group = action_group(rule['values']['action'])
                        claim_id = 'maintenance-claim:' + digest((library, arrival['id'], group))
                        if self.store.get('settings', claim_id):
                            with self.store.transaction():
                                results.append(
                                    self.maintenance_decision(
                                        rule,
                                        arrival,
                                        'skipped',
                                        'Source/action already has a retained attempt; no duplicate execution',
                                    )
                                )
                            continue
                        kind = finding['kind']
                        key = stable_id(asset['id'], kind)
                        old = self.store.get('tasks', key)
                        if old and (
                            old['status'] != 'recommendation'
                            or old.get('plan')
                            or old.get('version') != 1
                            or old.get('maintenance_proposal')
                        ):
                            raise UserError(
                                'Existing work or a manual draft reserves this action; review it instead of replacing it'
                            )
                        if rule['values']['action'] in PROCESSING and self.store.get(
                            'settings', self.pause_key(None, kind), False
                        ):
                            continue
                        with self.store.transaction():
                            claim = self.reserve_maintenance(
                                rule, arrival, None if kind == 'scan' else key, facts['standard']
                            )
                            if kind == 'scan':
                                claim.update(phase='complete', updated=now())
                                self.store.put('settings', claim['id'], claim)
                                results.append(
                                    self.maintenance_decision(
                                        rule,
                                        arrival,
                                        'complete',
                                        'New arrival assessed against its current standard; findings remain for manual review',
                                    )
                                )
                                continue
                            task = self.task(asset, finding)
                            task.update(
                                version=task['version'] + 1,
                                plan=copy.deepcopy(rule['values']['options']),
                                source=asset['fingerprint'],
                                error=None,
                            )
                            provenance = dict(
                                rule=rule['id'],
                                revision=rule['revision'],
                                approval=rule['approval']['id'],
                                claim=claim['id'],
                                standard=facts['standard'],
                                source=asset['fingerprint'],
                                initiator='rule',
                                output_bound=claim['output_bound'],
                            )
                            if rule['values']['action'] in PREPARATION:
                                task.update(maintenance_proposal=provenance, status='recommendation')
                                claim['phase'] = 'prepared'
                                decision_phase = 'prepared'
                            else:
                                task.update(
                                    tool_settings=copy.deepcopy(snapshot['tools']['settings']),
                                    status='queued',
                                    approval=task['version'],
                                    metadata_before=self.metadata_fields(asset['item']),
                                    preflight_retry_count=0,
                                    retry_at=None,
                                )
                                tools.command(
                                    kind,
                                    asset['local_path'],
                                    '/tmp/curator-maintenance-plan.mkv',
                                    task['tool_settings'],
                                )
                                if kind == 'upscale':
                                    tools.validate_upscale_target(asset.get('technical'), task['tool_settings'])
                                provenance['tool_settings'] = digest(task['tool_settings'])
                                task['maintenance'] = provenance
                                decision_phase = 'queued'
                            self.store.put('tasks', task['id'], task)
                            self.store.put('settings', claim['id'], claim)
                            self.store.event(
                                task['id'],
                                dict(
                                    action='maintenance proposal'
                                    if decision_phase == 'prepared'
                                    else 'maintenance queued',
                                    rule=rule['id'],
                                    revision=rule['revision'],
                                    standing_approval=rule['approval']['id'],
                                ),
                            )
                            results.append(
                                self.maintenance_decision(
                                    rule,
                                    arrival,
                                    decision_phase,
                                    'Bounded maintenance action admitted; publication and data/file saves remain manual',
                                    task['id'],
                                )
                            )
                    except Exception as error:
                        reason = (
                            str(error)
                            if isinstance(error, UserError)
                            else 'Maintenance checks failed; inspect the source, tools and permission before a fresh manual review'
                        )
                        with self.store.transaction():
                            rule = self.maintenance_rule(record['id'])
                            failure = rule.get('last_failure', {})
                            repeats = failure.get('count', 0) + 1 if failure.get('digest') == digest(reason) else 1
                            rule.update(
                                last_failure=dict(digest=digest(reason), count=repeats),
                                paused=bool(rule.get('paused') or repeats >= 2),
                                updated=now(),
                            )
                            self.store.put('settings', rule['id'], rule)
                            results.append(self.maintenance_decision(rule, arrival, 'exception', reason))
        self.start_pending_maintenance()
        return results

    def finish_maintenance_task(self, task):
        approval = task.get('maintenance')
        if not approval:
            return
        with self.lock, self.store.transaction(), acting('rule'):
            claim = self.store.get('settings', approval['claim'])
            if not claim or claim.get('phase') not in {'reserved', 'attempted'}:
                return
            uncertain = claim['phase'] == 'attempted' and task['status'] != 'awaiting_review'
            claim.update(
                phase='uncertain'
                if uncertain
                else 'complete'
                if task['status'] == 'awaiting_review'
                else 'blocked_unstarted',
                updated=now(),
            )
            self.store.put('settings', claim['id'], claim)
            if uncertain:
                rule = self.maintenance_rule(approval['rule'])
                rule.update(paused=True, updated=now())
                self.store.put('settings', rule['id'], rule)
            self.store.event(
                task['id'],
                dict(
                    action='maintenance result retained for manual review', rule=approval['rule'], phase=claim['phase']
                ),
            )

    def recover_maintenance(self):
        with self.lock, self.store.transaction(), acting('curator'):
            for task in self.store.all('tasks'):
                permission = task.get('maintenance')
                if not permission:
                    continue
                claim = self.store.get('settings', permission['claim'])
                if not claim or claim.get('phase') not in {'reserved', 'attempted'}:
                    continue
                if task['status'] in {'queued', 'running', 'blocked'}:
                    task.update(
                        status='blocked',
                        approval=None,
                        version=task['version'] + 1,
                        error='Restarted maintenance work is held; inspect retained output and prepare a fresh manual review',
                        updated=now(),
                    )
                    self.store.put('tasks', task['id'], task)
                    uncertain = claim['phase'] == 'attempted'
                    claim.update(phase='uncertain' if uncertain else 'interrupted_unstarted', updated=now())
                    self.store.put('settings', claim['id'], claim)
                    if uncertain:
                        rule = self.maintenance_rule(permission['rule'])
                        rule.update(paused=True, updated=now())
                        self.store.put('settings', rule['id'], rule)
                    self.store.event(
                        task['id'], dict(action='maintenance restart hold', rule=permission['rule'], replay=False)
                    )
