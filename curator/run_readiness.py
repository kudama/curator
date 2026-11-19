"""Read-only unattended-run checks and explicit per-library defaults."""

import heapq
import math
import shutil
import statistics
from pathlib import Path
from . import tools
from .store import now
from .errors import UserError


class RunReadiness:
    def processing_defaults(self):
        return {
            r['library']: r['values']
            for r in self.store.all('settings')
            if isinstance(r, dict) and r.get('record_type') == 'processing_defaults'
        }

    def save_processing_defaults(self, library, kind, values):
        self.library(library)
        allowed = {
            'optimize': {'handbrake_preset'},
            'upscale': {'topaz_filter', 'topaz_rate_control', 'topaz_quality', 'topaz_bitrate_mbps'},
        }
        if (
            kind not in allowed
            or not isinstance(values, dict)
            or not values
            or set(values) - allowed[kind]
            or any(not isinstance(v, (str, int, float)) or isinstance(v, bool) for v in values.values())
        ):
            raise UserError('Invalid processing defaults')
        if kind == 'optimize' and (
            not isinstance(values.get('handbrake_preset'), str)
            or not values['handbrake_preset'].strip()
            or len(values['handbrake_preset']) > 512
        ):
            raise UserError('Choose an installed encoding preset')
        if kind == 'upscale':
            if 'topaz_filter' in values and (
                not isinstance(values['topaz_filter'], str) or len(values['topaz_filter']) > 8192
            ):
                raise UserError('Invalid upscale filter')
            tools.topaz_encoding({**self.config(), **values})
        with self.store.transaction():
            key = 'processing-defaults:' + library
            record = self.store.get(
                'settings', key, dict(id=key, record_type='processing_defaults', library=library, values={})
            )
            record['values'][kind] = dict(values)
            record['updated'] = now()
            self.store.put('settings', key, record)
        return record['values']

    def run_readiness(self, library=None):
        if library is not None:
            self.library(library)
        tasks = self.waiting_tasks(library)
        all_tasks = self.store.all('tasks')
        assets = {a['id']: a for a in self.store.all('assets')}
        issues = []
        volumes = {}
        checked = {}
        ratios = {}
        costs = {}
        unknown_by_volume = {}
        for task in all_tasks:
            source = assets.get(task.get('asset'), {})
            duration = source.get('technical', {}).get('duration_seconds')
            elapsed = task.get('processing_seconds')
            size = task.get('source', {}).get('size')
            output = task.get('result', {}).get('size_bytes')
            if task['status'] not in {'awaiting_review', 'applied'}:
                continue
            if (
                isinstance(duration, (int, float))
                and duration > 0
                and isinstance(elapsed, (int, float))
                and elapsed > 0
                and math.isfinite(elapsed)
            ):
                costs.setdefault(task['kind'], []).append(elapsed / duration)
            if isinstance(size, (int, float)) and size > 0 and isinstance(output, (int, float)) and output > 0:
                ratios.setdefault(task['kind'], []).append(output / size)

        def volume(path, label):
            try:
                path = Path(path)
                info = path.stat()
                key = str(info.st_dev)
                if key not in volumes:
                    volumes[key] = dict(
                        device=key,
                        locations=[],
                        free_bytes=shutil.disk_usage(path).free,
                        estimated_extra_bytes=0,
                        unknown_jobs=0,
                    )
                row = volumes[key]
                if label not in row['locations']:
                    row['locations'].append(label)
                return row
            except OSError:
                return None

        scratch = volume(self.store.root, 'Scratch / processed outputs')
        if scratch is None:
            issues.append(dict(id=None, message='Scratch/output storage is unavailable'))
        durations = {}
        unknown_estimates = 0
        for task in tasks:
            try:
                key = task.get('asset')
                if key not in checked:
                    checked[key] = self.asset(task, check=task['kind'] != 'mage_generation')
                asset = checked[key]
                if task['kind'] in {'upscale', 'optimize'}:
                    tools.command(
                        task['kind'],
                        asset['local_path'],
                        self.store.root / 'readiness-output.mkv',
                        task.get('tool_settings', {}),
                    )
                if task['kind'] == 'join':
                    self.file_sources(task)
            except (OSError, ValueError, KeyError):
                issues.append(
                    dict(
                        id=task['id'],
                        title=task.get('title', task['id']),
                        message='Source, mapping or required processing tool is unavailable; inspect this job',
                    )
                )
                continue
            duration = asset.get('technical', {}).get('duration_seconds')
            samples = costs.get(task['kind'])
            if samples and isinstance(duration, (int, float)) and duration > 0:
                durations.setdefault(task['kind'], []).append(duration * statistics.median(samples[-20:]))
            else:
                unknown_estimates += 1
            if task['kind'] not in {'upscale', 'optimize', 'join'}:
                continue
            destination = volume(
                Path(asset['local_path']).parent,
                'Destination: ' + self.library(asset['library']).get('title', asset['library']),
            )
            if destination is None:
                issues.append(dict(id=task['id'], message='Destination storage is unavailable'))
            source_size = asset.get('fingerprint', {}).get('size')
            samples = ratios.get(task['kind'])
            estimate = (
                int(source_size * statistics.median(samples[-20:]))
                if samples and isinstance(source_size, int) and source_size > 0
                else None
            )
            for row in (scratch, destination):
                if row is not None:
                    if estimate is None:
                        unknown_by_volume.setdefault(row['device'], set()).add(task['id'])
                    else:
                        row['estimated_extra_bytes'] += estimate
        for job in self.file_jobs():
            if job['phase'] != 'waiting' or library is not None and job['library'] != library:
                continue
            try:
                if job['operation'] == 'publish':
                    task = self.get_task(job['payload']['task'])
                    asset = self.asset(task, check=task['kind'] not in {'artwork', 'portrait'})
                    if task['kind'] in {'upscale', 'optimize', 'join'}:
                        size = Path(task['output']).stat().st_size
                        destination = volume(
                            Path(asset['local_path']).parent,
                            'Destination: ' + self.library(asset['library']).get('title', asset['library']),
                        )
                        if destination is None:
                            raise UserError('Destination unavailable')
                        destination['estimated_extra_bytes'] += size
                elif job['operation'] == 'cleanup':
                    receipt = self.cleanup_receipt(job['payload']['receipt'])
                    for item in receipt['items']:
                        if item['id'] in receipt['selected']:
                            self.backup_candidate(self.get_task(item['id']))
            except (OSError, ValueError, KeyError):
                issues.append(
                    dict(id=job['id'], message='Queued file operation needs source/output/storage inspection')
                )
        for row in volumes.values():
            row['unknown_jobs'] = len(unknown_by_volume.get(row['device'], set()))
            row['low_space'] = row['free_bytes'] < row['estimated_extra_bytes']
        estimates = []
        running = [t for t in all_tasks if t['status'] == 'running' and (library is None or t['library'] == library)]
        for kind in set(durations) | {t['kind'] for t in running}:
            etas = [t.get('progress', {}).get('eta_seconds') for t in running if t['kind'] == kind]
            if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in etas):
                unknown_estimates += 1
                continue
            limit = self.queue_limit(kind)
            slots = sorted(etas)[max(0, len(etas) - limit) :]
            slots += [0] * (limit - len(slots))
            heapq.heapify(slots)
            for seconds in durations.get(kind, []):
                earliest = heapq.heappop(slots)
                heapq.heappush(slots, earliest + seconds)
            estimates.append(max(slots, default=0))
        return dict(
            checked_at=now(),
            waiting=len(tasks),
            running=len(running),
            file_waiting=sum(j['phase'] == 'waiting' for j in self.file_jobs()),
            limits=self.queue_limits(),
            issues=issues,
            volumes=list(volumes.values()),
            unknown_estimates=unknown_estimates,
            processing_eta_seconds=max(estimates, default=None) if not unknown_estimates and not issues else None,
            estimate_note='Approximate processing time from recent measured jobs; publication time is additional. Unknown output sizes and online-service availability are not assumed.',
        )
