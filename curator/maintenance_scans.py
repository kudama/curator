"""Explicit, finite new-arrival scans on the existing durable File queue.

Inventory reads precede all media access. Only post-baseline identities inside
reviewed roots can consume a probe reservation; ambiguous rematches stay manual.
"""

from datetime import datetime
from pathlib import Path, PurePosixPath
import os
import stat
import subprocess
import sys
import time
import uuid

from . import tools
from .errors import UserError
from .history import acting
from .maintenance_arrivals import identity_tokens, STABILITY_SECONDS
from .maintenance_dispatch import MaintenanceHeld
from .maintenance_facts import evaluated
from .maintenance_inventory import verified_inventory
from .maintenance_policy import digest, excluded, permitted
from .paths import map_path
from .rules import stable_id
from .store import now

DEMUXERS = {
    '.mp4': 'mov',
    '.m4v': 'mov',
    '.mov': 'mov',
    '.mkv': 'matroska',
    '.webm': 'matroska',
    '.avi': 'avi',
    '.mpg': 'mpeg',
    '.mpeg': 'mpeg',
    '.ts': 'mpegts',
    '.m2ts': 'mpegts',
    '.wmv': 'asf',
}


class MaintenanceScans:
    def maintenance_scan_run(self, identity):
        row = self.store.get('settings', identity, {})
        if row.get('record_type') != 'maintenance_scan':
            raise UserError('Maintenance scan receipt was not found')
        return row

    def maintenance_scan_guard(self, run):
        rule = self.maintenance_rule(run['rule'])
        snapshot = self.validate_maintenance_permission(rule)
        if rule['revision'] != run['revision'] or rule['approval']['id'] != run['approval']:
            raise UserError('Scan permission was revoked or replaced; no further media access')
        if rule['values']['action'] != 'scan':
            raise UserError('This permission does not authorize scheduled scans')
        if (
            rule.get('paused')
            or self.maintenance_paused(run['library'])
            or self.file_queue_paused()
            or not permitted(rule['values'], self.maintenance_clock())
        ):
            raise MaintenanceHeld('Scan held by its window, maintenance pause or File operations pause')
        return rule, snapshot

    def maintenance_scan_job_holds(self, job):
        try:
            run = self.maintenance_scan_run(job['payload']['run'])
            self.maintenance_scan_guard(run)
            return bool(
                self.scan_status.get(run['library'], {}).get('running')
                or self.presence_status.get(run['library'], {}).get('running')
            )
        except MaintenanceHeld:
            return True
        except (UserError, KeyError, ValueError):
            return False  # Worker records the stale permission as a failed receipt.

    def admit_maintenance_scan(self, identity):
        with self.lock, acting('rule'):
            rule = self.maintenance_rule(identity)
            snapshot = self.validate_maintenance_permission(rule)
            if rule['values']['action'] != 'scan':
                raise UserError('Only an explicitly enabled Scan permission may schedule an inventory')
            library = rule['values']['library']
            if any(
                j['operation'] == 'maintenance_scan'
                and j['library'] == library
                and j['phase'] in {'waiting', 'running'}
                for j in self.file_jobs()
            ):
                return None
            last = self.store.get('settings', 'maintenance-schedule:' + library, {})
            if (
                last
                and (self.maintenance_clock() - datetime.fromisoformat(last['admitted'])).total_seconds()
                < rule['values']['options']['cadence_minutes'] * 60
            ):
                return None
            run = dict(
                id='maintenance-scan:' + uuid.uuid4().hex,
                record_type='maintenance_scan',
                library=library,
                rule=identity,
                revision=rule['revision'],
                approval=rule['approval']['id'],
                phase='queued',
                created=now(),
                items=[],
                options=rule['values']['options'],
                scope=rule['values']['roots'],
                exclusions=rule['values']['excluded_paths'],
                limits=rule['values']['limits'],
                windows=rule['values']['windows'],
                quiet=rule['values']['quiet'],
                timezone=rule['values']['timezone'],
                inventory=None,
            )
            self.maintenance_scan_guard(run)
            baseline = self.store.get('settings', 'maintenance-arrivals:' + library)
            arrival = dict(library=library, id=run['id'], last_sequence=baseline['sequence'] + 1, fingerprint=None)
            run['sequence'] = arrival['last_sequence']

            def admit(job):
                claim = self.reserve_maintenance(rule, arrival, run['id'], snapshot['standard'], output_bound=0)
                run.update(job=job['id'], claim=claim['id'])
                self.store.record(
                    'maintenance_scan',
                    'Bounded scheduled inventory admitted under explicit Scan permission',
                    library=library,
                    details={'run': run['id'], 'rule': identity, 'options': run['options']},
                )
                self.store.put('settings', run['id'], run)
                self.store.put(
                    'settings',
                    'maintenance-schedule:' + library,
                    dict(admitted=self.maintenance_clock().isoformat(), run=run['id']),
                )

            self.queue_file_operation(
                'maintenance_scan',
                dict(run=run['id'], library=library, title='New-arrival scan'),
                background=True,
                start=False,
                admit=admit,
            )
            return run

    def execute_maintenance_scan(self, identity):
        run = self.maintenance_scan_run(identity)
        library = self.library(run['library'])
        with self.lock:
            if run['phase'] not in {'queued', 'paused'}:
                raise UserError('This scan receipt cannot be replayed; inspect retained observations')
            if self.scan_status.get(library['id'], {}).get('running') or self.presence_status.get(
                library['id'], {}
            ).get('running'):
                run.update(phase='paused', error='A library scan/presence check is already active')
                with self.store.transaction():
                    self.store.put('settings', identity, run)
                return run
            self.scan_status[library['id']] = dict(running=True, count=0, maintenance=identity)
        try:

            def guard():
                with self.lock, self.store.transaction():
                    self.maintenance_scan_guard(run)
                    self.store.record(
                        'maintenance_inventory_read',
                        'Approved bounded Plex inventory request',
                        library=library['id'],
                        details={'run': identity},
                    )

            guard()
            service, client = self, self.client()

            class GuardedClient:
                def request(self, path, **kwargs):
                    # The same lock serializes the final actual request start
                    # with pause/disable, not merely its earlier permission check.
                    with service.lock:
                        guard()
                        return client.request(path, **kwargs)

            deadline = time.monotonic() + run['options']['scan_timeout_seconds']
            inventory = verified_inventory(GuardedClient(), library, run['options'], guard, deadline=deadline)
            with self.lock, self.store.transaction():
                rule, snapshot = self.maintenance_scan_guard(run)
                run.update(
                    phase='running',
                    inventory={key: value for key, value in inventory.items() if key != 'items'},
                    started=now(),
                )
                registry = self.store.get('settings', 'maintenance-arrivals:' + library['id'])
                registry['sequence'] += 1
                registry.update(completed_scan=now(), observed_at=self.maintenance_clock().isoformat())
                self.store.put('settings', registry['id'], registry)
                self.store.put('settings', identity, run)
            for item in inventory['items']:
                if time.monotonic() >= deadline:
                    raise UserError('Approved overall scan deadline reached; inspect partial observations')
                # All metadata exclusions run before path resolution or stat.
                parts = [part for media in item.get('Media', []) for part in media.get('Part', []) if part.get('file')]
                if len(parts) != 1:
                    continue
                part = parts[0]
                asset = dict(
                    id=stable_id(library['server'], library['key'], item['ratingKey'], part.get('id'), part['file']),
                    library=library['id'],
                    rating_key=str(item['ratingKey']),
                    item=item,
                    plex_path=part['file'],
                    title=item.get('title', 'Untitled'),
                    present=True,
                )
                with self.lock:
                    rule, snapshot = self.maintenance_scan_guard(run)
                    values = rule['values']
                    if excluded(values, asset) or not any(
                        PurePosixPath(asset['plex_path']).is_relative_to(PurePosixPath(root))
                        for root in values['roots']
                    ):
                        continue
                    registry = self.store.get('settings', 'maintenance-arrivals:' + library['id'])
                    tokens = identity_tokens(asset)
                    aliases = {registry['known'][token] for token in tokens if token in registry['known']}
                    if aliases:  # Baseline, renamed, rematched or already handled.
                        continue
                    candidate_id = 'maintenance-candidate:' + digest(
                        (library['id'], asset['rating_key'], asset['plex_path'])
                    )
                    candidate = self.store.get('settings', candidate_id)
                    if candidate and (
                        candidate['rule'] != rule['id']
                        or candidate['revision'] != rule['revision']
                        or candidate['phase'] not in {'observing'}
                    ):
                        continue
                    if candidate is None:
                        with self.store.transaction():
                            arrival = dict(
                                id=candidate_id,
                                library=library['id'],
                                last_sequence=registry['sequence'],
                                fingerprint=None,
                            )
                            claim = self.reserve_maintenance(rule, arrival, candidate_id, snapshot['standard'])
                            candidate = dict(
                                id=candidate_id,
                                record_type='maintenance_candidate',
                                library=library['id'],
                                rule=rule['id'],
                                revision=rule['revision'],
                                phase='observing',
                                claim=claim['id'],
                                first_sequence=registry['sequence'],
                                generation=registry['generation'],
                                observations=0,
                                created=now(),
                            )
                            self.store.put('settings', candidate_id, candidate)
                    # The first filesystem observation is durably authorized too.
                    with self.store.transaction():
                        self.store.record(
                            'maintenance_observation',
                            'Reserved new identity source observation',
                            library=library['id'],
                            details={'run': identity, 'candidate': candidate_id},
                        )
                    with self.store.transaction():
                        if candidate['observations'] >= 3:
                            raise UserError('Approved source-observation attempt bound reached; inspect manually')
                        if candidate['observations']:
                            observation = dict(
                                id=candidate_id + ':observation:' + str(candidate['observations'] + 1),
                                library=library['id'],
                                last_sequence=registry['sequence'],
                                fingerprint=candidate.get('fingerprint'),
                            )
                            self.reserve_maintenance(
                                rule, observation, candidate_id, snapshot['standard'], output_bound=0
                            )
                        candidate['observations'] += 1
                        self.store.put('settings', candidate_id, candidate)
                result = dict(asset=asset['id'], title=asset['title'], candidate=candidate_id, phase='observing')
                try:
                    with self.lock:
                        self.maintenance_scan_guard(run)
                        path = map_path(asset['plex_path'], library['mappings'])
                        fp = tools.fingerprint(path)
                    with self.lock, self.store.transaction():
                        self.maintenance_scan_guard(run)
                        registry = self.store.get('settings', 'maintenance-arrivals:' + library['id'])
                        asset.update(local_path=str(path), fingerprint=fp)
                        if any(token in registry['known'] for token in identity_tokens(asset)):
                            candidate.update(phase='skipped', reason='Existing source/rematch/copy identity; no probe')
                            result.update(phase='skipped', reason=candidate['reason'])
                            self.store.put('settings', candidate_id, candidate)
                        else:
                            instant = self.maintenance_clock()
                            stable = (
                                candidate.get('fingerprint') == fp
                                and (instant - datetime.fromisoformat(candidate['stable_since'])).total_seconds()
                                >= STABILITY_SECONDS
                            )
                            if candidate.get('fingerprint') != fp:
                                candidate.update(fingerprint=fp, stable_since=instant.isoformat())
                            if candidate['observations'] >= 3 and not stable:
                                candidate.update(
                                    phase='blocked',
                                    reason='Source did not stabilize within the approved observation attempts',
                                )
                                result.update(phase='blocked', reason=candidate['reason'])
                            self.store.put('settings', candidate_id, candidate)
                    if candidate['phase'] == 'observing' and stable:
                        technical = self.maintenance_probe(run, candidate, path, fp, deadline=deadline)
                        asset.update(technical=technical, scanned=now())
                        facts = evaluated(self, asset)
                        with self.lock, self.store.transaction():
                            self.maintenance_scan_guard(run)
                            # Do not overwrite a concurrently created/manual-edited asset.
                            if self.store.get('assets', asset['id']):
                                raise UserError('Source was added or edited concurrently; review it manually')
                            self.store.put('assets', asset['id'], asset)
                            self.reconcile_findings(asset, facts['findings'])
                            registry = self.store.get('settings', 'maintenance-arrivals:' + library['id'])
                            aid = 'maintenance-arrival:' + uuid.uuid4().hex
                            arrival = dict(
                                id=aid,
                                record_type='maintenance_arrival',
                                library=library['id'],
                                asset=asset['id'],
                                scan_claim=candidate['claim'],
                                generation=candidate['generation'],
                                first_sequence=candidate['first_sequence'],
                                last_sequence=registry['sequence'],
                                phase='ready',
                                fingerprint=fp,
                                stable_since=candidate['stable_since'],
                                created=candidate['created'],
                                updated=now(),
                            )
                            for token in identity_tokens(asset):
                                registry['known'][token] = aid
                            self.store.put('settings', aid, arrival)
                            self.store.put('settings', registry['id'], registry)
                            candidate['phase'] = 'complete'
                            result['phase'] = 'complete'
                            claim = self.store.get('settings', candidate['claim'])
                            claim.update(phase='complete', updated=now())
                            self.store.put('settings', claim['id'], claim)
                            self.store.put('settings', candidate_id, candidate)
                except MaintenanceHeld:
                    raise
                except (ValueError, OSError, subprocess.SubprocessError) as error:
                    result.update(phase='blocked', reason=str(error)[:300])
                    with self.lock, self.store.transaction():
                        candidate.update(phase='blocked', reason=result['reason'])
                        self.store.put('settings', candidate_id, candidate)
                        claim = self.store.get('settings', candidate['claim'])
                        attempted = claim['phase'] == 'probe_attempted'
                        claim.update(phase='uncertain' if attempted else 'blocked_unstarted', updated=now())
                        self.store.put('settings', claim['id'], claim)
                        if attempted:
                            rule = self.maintenance_rule(run['rule'])
                            rule.update(
                                paused=True,
                                last_exception='Probe outcome requires inspection; retained output is never replayed',
                                updated=now(),
                            )
                            self.store.put('settings', rule['id'], rule)
                with self.lock, self.store.transaction():
                    run['items'].append(result)
                    self.store.put('settings', identity, run)
                    if self.maintenance_rule(run['rule']).get('paused'):
                        break
            run.update(
                phase='partial' if any(row['phase'] == 'blocked' for row in run['items']) else 'complete',
                finished=now(),
            )
            with self.lock, self.store.transaction():
                claim = self.store.get('settings', run['claim'])
                claim.update(phase='complete', updated=now())
                self.store.put('settings', claim['id'], claim)
                self.store.put('settings', identity, run)
            self.dispatch_maintenance(library['id'])
        except MaintenanceHeld as error:
            run.update(phase='paused', error=str(error))
            with self.lock, self.store.transaction():
                self.store.put('settings', identity, run)
        except Exception as error:
            run.update(
                phase='failed',
                error=str(error)[:300]
                if isinstance(error, (ValueError, OSError))
                else 'Scan stopped; inspect retained observations',
                finished=now(),
            )
            with self.lock, self.store.transaction():
                self.store.put('settings', identity, run)
                rule = self.maintenance_rule(run['rule'])
                rule.update(paused=True, updated=now())
                self.store.put('settings', rule['id'], rule)
                self.store.record(
                    'maintenance_scan_failed',
                    'Bounded Scan stopped; rule paused for review',
                    library=library['id'],
                    details={'run': identity, 'error': run['error']},
                    level='warning',
                )
        finally:
            with self.lock:
                self.scan_status[library['id']]['running'] = False
        return run

    def maintenance_probe(self, run, candidate, path, fingerprint, deadline=None):
        demuxer = DEMUXERS.get(path.suffix.lower())
        if demuxer is None:
            raise UserError('No bounded local-only demuxer is approved for this file; scan manually')
        folder = self.store.root / 'maintenance-probes' / uuid.uuid4().hex
        folder.mkdir(parents=True)
        output, error = folder / 'stdout.json', folder / 'stderr.txt'
        with output.open('xb') as stdout, error.open('xb') as stderr:

            def runner(command, **kwargs):
                restricted = [command[0], '-protocol_whitelist', 'file', '-f', demuxer]
                if demuxer == 'mov':
                    restricted += ['-enable_drefs', '0']
                restricted += command[1:-1]
                with self.lock:
                    with self.store.transaction():
                        rule, snapshot = self.maintenance_scan_guard(run)
                        claim = self.store.get('settings', candidate['claim'])
                        if claim['phase'] != 'reserved' or tools.fingerprint(path) != fingerprint:
                            raise UserError('Probe source/attempt changed; no automatic replay')
                        self.maintenance_start_allowance(claim, rule)
                        claim.update(phase='probe_attempted', artifacts=[str(output), str(error)], updated=now())
                        self.store.put('settings', claim['id'], claim)
                        self.store.record(
                            'maintenance_probe',
                            'Approved bounded new-arrival media probe started',
                            library=run['library'],
                            details={'candidate': candidate['id'], 'run': run['id']},
                        )
                    source_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                    current = os.fstat(source_fd)
                    pinned = dict(
                        size=current.st_size, modified=current.st_mtime_ns, inode=current.st_ino, device=current.st_dev
                    )
                    if not stat.S_ISREG(current.st_mode) or pinned != fingerprint:
                        os.close(source_fd)
                        raise UserError('Probe source changed before descriptor pinning')
                    restricted.append('/dev/fd/' + str(source_fd))
                    try:
                        process = subprocess.Popen(
                            [
                                sys.executable,
                                str(Path(__file__).with_name('limited_exec.py')),
                                str(run['options']['probe_output_bytes']),
                                '--',
                                *restricted,
                            ],
                            stdout=stdout,
                            stderr=stderr,
                            start_new_session=True,
                            pass_fds=(source_fd,),
                        )
                    finally:
                        os.close(source_fd)
                try:
                    remaining = (
                        max(0.001, deadline - time.monotonic()) if deadline else run['options']['probe_timeout_seconds']
                    )
                    code = process.wait(timeout=min(run['options']['probe_timeout_seconds'], remaining))
                except BaseException:
                    from .maintenance_execution import stop_group

                    stop_group(process, hard=True)
                    process.wait(timeout=5)
                    raise
                if tools.fingerprint(path) != fingerprint:
                    raise UserError('Probe source changed; no automatic action')
                return subprocess.CompletedProcess(restricted, code, output.read_bytes(), error.read_bytes())

            return tools.probe(path, self.config(), runner=runner)
