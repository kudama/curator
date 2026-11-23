"""Read-only, scoped Home summaries from cached facts and durable outcomes."""

from datetime import datetime, timezone, timedelta
import json
import math
from urllib.parse import quote, urlencode

from .errors import UserError
from .standard_evaluation import evaluate, summarize
from .standards import DIMENSIONS

RESULTS = {'upscale', 'optimize', 'join', 'preview_render'}
ARTWORK = {'artwork', 'mage_generation', 'portrait'}
METADATA = {'metadata', 'home', 'folder_metadata'}
COMPLETION_LIMIT = 5000


def epoch(value):
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) or isinstance(value, str) and value.isdigit():
            value = float(value)
        else:
            value = datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
        return value if math.isfinite(value) and value > 0 else None
    except (AttributeError, ValueError, TypeError, OverflowError):
        return None


def library_link(library, workspace='files', **query):
    return '#/library/' + quote(library, safe='') + '/' + workspace + ('?' + urlencode(query) if query else '')


def work_summary(records, truncated=False):
    seen, initiators = set(), dict(operator=0, rule=0, ai=0, unknown=0)
    result = dict(
        period_days=7,
        completed=0,
        published=0,
        known_space_saved_bytes=0,
        space_saving_items=0,
        space_unknown_items=0,
        initiators=initiators,
        history_complete=False,
        truncated=truncated,
    )
    for record in records:
        outcome = record.get('outcome') or {}
        key = outcome.get('identity')
        if not key or key in seen:
            continue
        seen.add(key)
        result['completed'] += 1
        initiator = outcome.get('initiator')
        initiators[initiator if initiator in {'operator', 'rule', 'ai'} else 'unknown'] += 1
        if outcome.get('published'):
            result['published'] += 1
            sizes = [outcome.get('source_bytes'), outcome.get('output_bytes')]
            if all(type(n) is int and n >= 0 for n in sizes):
                result['known_space_saved_bytes'] += max(0, sizes[0] - sizes[1])
                result['space_saving_items'] += int(sizes[0] > sizes[1])
            else:
                result['space_unknown_items'] += 1
    result['coverage'] = 'Recorded outcomes only; earlier completion dates are not inferred from mutable task records.'
    return result


class HomeSummary:
    def home_summary(self, library='all', view='full', limit=12):
        if view not in {'full', 'compact'} or type(limit) is not int or not 1 <= limit <= 30:
            raise UserError('Choose a Home view and 1–30 recent arrivals')
        clock = datetime.now(timezone.utc)
        at, cutoff = clock.isoformat(), (clock - timedelta(days=7)).isoformat()
        with self.store.transaction():
            libraries = {row['id']: row for row in self.store.all('libraries')}
            if library != 'all' and library not in libraries:
                raise UserError('Choose a connected Home library')
            scoped = libraries if library == 'all' else {library: libraries[library]}
            assets = [
                row
                for row in self.store.all('assets')
                if row.get('library') in scoped and not row.get('artwork_target')
            ]
            tasks = [row for row in self.store.all('tasks') if row.get('library') in scoped and not row.get('deleted')]
            config = self.config()
            query = "SELECT at,data FROM events WHERE category='job' AND at>=? AND at<=?"
            args = [cutoff, at]
            if library != 'all':
                query += ' AND library=?'
                args.append(library)
            query += " AND data LIKE '%\"record_type\": \"completion\"%' ORDER BY id DESC LIMIT ?"
            args.append(COMPLETION_LIMIT + 1)
            records = self.store.db.execute(query, args).fetchall()
            work = work_summary(
                [json.loads(data) for _, data in records[:COMPLETION_LIMIT]], len(records) > COMPLETION_LIMIT
            )
            coverage = self.store.get('settings', 'home-outcome-coverage', {}).get('observed_since')
            work['history_complete'] = bool(
                epoch(coverage) and epoch(coverage) <= epoch(cutoff) and not work['truncated']
            )
            file_jobs = [
                job
                for job in self.store.where('settings', record_type='file_operation')
                if job.get('library') in scoped
            ]
            health, completions = [], {}
            for key, row in scoped.items():
                effective = self.library_standard(row)
                members = [asset for asset in assets if asset['library'] == key]
                for asset in members:
                    completions[asset['id']] = evaluate(asset, effective, config)[0]
                    scanned = epoch(asset.get('scanned'))
                    if scanned and scanned > clock.timestamp():
                        completions[asset['id']]['status'] = 'unknown'
                        for dimension in completions[asset['id']]['dimensions'].values():
                            if dimension['state'] != 'disabled':
                                dimension.update(state='unknown', reason='Observation time is in the future')
                aggregate = summarize([completions[asset['id']] for asset in members])
                enabled = [dimension for dimension in DIMENSIONS if effective['values'][dimension]['enabled']]
                dimensions = []
                for dimension in enabled:
                    counts = aggregate['dimensions'][dimension]
                    dimensions.append(
                        dict(
                            dimension=dimension,
                            **counts,
                            percent=round(100 * counts['met'] / len(members)) if members else None,
                            href=library_link(key, view='files', dimension=dimension),
                        )
                    )
                observed = [epoch(asset.get('scanned')) for asset in members]
                observed = [value if value and value <= clock.timestamp() else None for value in observed]
                observed_at = min(observed) if observed and all(observed) else None
                health.append(
                    dict(
                        library=key,
                        title=row['title'],
                        kind=effective['kind'],
                        enabled_dimensions=len(enabled),
                        **{key: value for key, value in aggregate.items() if key != 'dimensions'},
                        dimensions=dimensions,
                        observed_at=datetime.fromtimestamp(observed_at, timezone.utc).isoformat()
                        if observed_at
                        else None,
                        stale=observed_at is None or clock.timestamp() - observed_at > 86400,
                        href=library_link(key, view='files'),
                        standards_href='#/configuration/library/' + quote(key, safe=''),
                    )
                )
            publication_pending = {
                job.get('payload', {}).get('task')
                for job in file_jobs
                if job['phase'] in {'waiting', 'running'} and job['operation'] == 'publish'
            }
            ready = [
                task
                for task in tasks
                if task.get('status') == 'awaiting_review' and task['id'] not in publication_pending
            ]
            artwork = [
                dict(
                    library=key,
                    title=row['title'],
                    count=sum(task.get('kind') in ARTWORK and task['library'] == key for task in ready),
                    href=library_link(key, 'artwork', status='review'),
                )
                for key, row in scoped.items()
            ]
            artwork = [row for row in artwork if row['count']]
            attention = {task['id'] for task in tasks if task.get('status') in {'failed', 'blocked'}}
            cleanup_attention, export_attention = set(), {}
            for job in file_jobs:
                outcome = job.get('result') if isinstance(job.get('result'), dict) else {}
                if job['phase'] in {'failed', 'interrupted'} or outcome.get('phase') in {
                    'partial',
                    'failed',
                }:
                    key = job.get('payload', {}).get('task') or job.get('payload', {}).get('receipt') or job['id']
                    attention.add(key)
                    if job.get('operation') in {'cleanup', 'restore_cleanup'}:
                        cleanup_attention.add(key)
                    elif job.get('operation') == 'nfo_export' and outcome.get('phase') == 'partial':
                        export_attention.setdefault(job['library'], set()).add(key)
            for receipt in self.store.where('settings', record_type='backup_cleanup'):
                if receipt.get('library') in scoped and (
                    receipt.get('phase') == 'interrupted'
                    or any(
                        item.get('status') == 'failed'
                        for item in receipt.get('items', [])
                        if item.get('id') in receipt.get('selected', [])
                    )
                ):
                    attention.add(receipt['id'])
                    cleanup_attention.add(receipt['id'])
            exports = set().union(*export_attention.values()) if export_attention else set()
            work_attention = attention - cleanup_attention - exports
            attention_routes = []
            if work_attention:
                attention_routes.append(
                    dict(
                        label='Jobs need attention',
                        count=len(work_attention),
                        href=library_link(library, 'queue', status='attention'),
                    )
                )
            if cleanup_attention:
                attention_routes.append(
                    dict(
                        label='Cleanup outcomes need inspection',
                        count=len(cleanup_attention),
                        href='#/history?' + urlencode(dict(view='jobs', library=library, period='all', status='all')),
                    )
                )
            for key, rows in export_attention.items():
                attention_routes.append(
                    dict(
                        label='Partial exports · ' + scoped[key]['title'],
                        count=len(rows),
                        href=library_link(key, 'filemanagement'),
                    )
                )
            missing = [
                asset
                for asset in assets
                if any(
                    completions[asset['id']]['dimensions'][dimension]['state'] == 'needs_attention'
                    for dimension in ('metadata', 'cast', 'artwork')
                )
            ]
            decisions = dict(
                results=sum(task.get('kind') in RESULTS for task in ready),
                metadata=sum(task.get('kind') in METADATA for task in ready),
                artwork=artwork,
                needs_attention=len(attention),
                attention_routes=attention_routes,
                missing_required=len(missing),
                standards_questions=sum(bool(row.get('standard_type_notice')) for row in scoped.values()),
            )
            arrivals = {}
            for asset in assets:
                item = asset.get('item') or {}
                added = epoch(item.get('addedAt'))
                if (
                    not added
                    or not epoch(cutoff) <= added <= clock.timestamp()
                    or asset.get('present') is False
                    or asset.get('missing_file')
                ):
                    continue
                if str(item.get('ratingKey')) != str(asset.get('rating_key')):
                    continue
                key = (asset['library'], str(asset['rating_key']))
                candidate = dict(
                    asset=asset['id'],
                    library=asset['library'],
                    title=asset['title'],
                    added_at=added,
                    completion=completions[asset['id']]['status'],
                    href=library_link(asset['library'], asset=asset['id'], view='files'),
                )
                previous = arrivals.get(key)
                if previous is None:
                    arrivals[key] = candidate
                elif previous['completion'] == 'complete' and candidate['completion'] != 'complete':
                    arrivals[key]['completion'] = candidate['completion']
        observed_at = (
            min((row['observed_at'] for row in health), default=None)
            if health and all(row['observed_at'] for row in health)
            else None
        )
        stale = (
            not health
            or any(row['stale'] for row in health)
            or bool(self.plex_failure)
            or any(status.get('error') for key, status in self.scan_status.items() if key in scoped)
        )
        counts = {
            name: sum(task.get('status') == status for task in tasks)
            for name, status in [('running', 'running'), ('waiting', 'queued'), ('publishing', 'publishing')]
        }
        tasks_by_id = {task['id']: task for task in tasks}
        for job in file_jobs:
            if job['phase'] in {'waiting', 'running'}:
                expected = 'queued' if job['phase'] == 'waiting' else 'running'
                owner = tasks_by_id.get(job.get('payload', {}).get('task')) or {}
                if owner.get('status') not in {expected, 'publishing'}:
                    counts['waiting' if job['phase'] == 'waiting' else 'running'] += 1
        counts.update(
            ready=decisions['results'] + decisions['metadata'] + sum(row['count'] for row in artwork),
            needs_attention=len(attention),
            missing_required=len(missing),
        )
        links = dict(
            home='#/home',
            queue=library_link(library, 'queue'),
            ready='#/home',
            results=library_link(library, 'review'),
            metadata=library_link(library, 'queue', status='review', lane='metadata'),
            attention='#/home',
            history='#/history?' + urlencode(dict(view='jobs', library=library, period=7)),
            standards='#/configuration/standards/movie',
        )
        result = dict(
            schema_version=1,
            generated_at=at,
            observed_at=observed_at,
            stale=stale,
            scope=library,
            counts=counts,
            work=work,
            health=dict(
                libraries=len(health),
                assessed_items=sum(row['total'] - row['unknown'] for row in health),
                complete_items=sum(row['complete'] for row in health),
                unknown_items=sum(row['unknown'] for row in health),
            ),
            links=links,
        )
        if view == 'full':
            result.update(
                decisions=decisions,
                libraries=health,
                arrivals=sorted(arrivals.values(), key=lambda row: (-row['added_at'], row['library'], row['asset']))[
                    :limit
                ],
                arrivals_total=len(arrivals),
                loading=any(status.get('running') for key, status in self.scan_status.items() if key in scoped),
                empty=not scoped,
                integrations=dict(discovery=hasattr(self, 'discovery'), seerr=hasattr(self, 'seerr_arrivals')),
            )
        return result
