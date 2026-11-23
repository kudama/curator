"""Finite, read-only operator projections; never permission or scheduler input."""

from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

from .maintenance_policy import PROCESSING, boundary, digest, minute, permitted
from .rules import scheduling_kind


def next_window(values, instant):
    if permitted(values, instant):
        return instant.isoformat()
    zone = ZoneInfo(values['timezone'])
    today = instant.astimezone(zone).date()
    candidates = set()
    # Eight named days include the next weekly window even across DST. Evaluate
    # only known interval boundaries, never minute polling or tool/media reads.
    for offset in range(8):
        day = today + timedelta(days=offset)
        for quiet, rows in ((False, values['windows']), (True, values['quiet'])):
            for row in rows:
                if day.weekday() not in row['days']:
                    continue
                for start in (True, False):
                    point = boundary(day, minute(row['start' if start else 'end']), zone, start, quiet)
                    if point is not None and point >= instant:
                        candidates.add(point)
    return next((point.isoformat() for point in sorted(candidates) if permitted(values, point)), None)


def summary(service, rule, records, tasks):
    instant = service.maintenance_clock().astimezone(timezone.utc)
    values, identity = rule['values'], rule['id']
    counts = dict(queued=0, running=0, waiting=0, review=0, blocked=0)
    for task in tasks:
        provenance = task.get('maintenance') or task.get('maintenance_proposal') or {}
        if provenance.get('rule') != identity or task.get('deleted'):
            continue
        status = task['status']
        key = (
            'queued'
            if status == 'queued'
            else 'running'
            if status in {'running', 'publishing'}
            else 'review'
            if status in {'awaiting_review', 'recommendation'}
            else 'blocked'
            if status in {'blocked', 'failed'}
            else None
        )
        if key:
            counts[key] += 1
            if status == 'queued' and (
                service.maintenance_holds(task)
                or service.store.get('settings', service.pause_key(None, scheduling_kind(task['kind'])), False)
            ):
                counts['waiting'] += 1
    for row in records.values():
        if row.get('record_type') != 'maintenance_scan' or row['rule'] != identity:
            continue
        if row['phase'] in {'queued', 'paused'}:
            counts['queued'] += 1
            if (
                row['phase'] == 'paused'
                or rule.get('paused')
                or service.maintenance_paused(values['library'])
                or service.file_queue_paused()
                or not permitted(values, instant)
            ):
                counts['waiting'] += 1
        elif row['phase'] == 'running':
            counts['running'] += 1
        elif row['phase'] in {'failed', 'partial', 'interrupted'}:
            counts['blocked'] += 1
    baseline = records.get('maintenance-arrivals:' + values['library'], {})
    sequences = [
        row['run_sequence']
        for row in records.values()
        if row.get('record_type') == 'maintenance_claim'
        and row.get('library') == values['library']
        and type(row.get('run_sequence')) is int
    ]
    run_sequence = max(sequences, default=baseline.get('sequence'))
    remaining = []
    try:
        for scope in service.maintenance_allowances(rule):
            day = instant.astimezone(ZoneInfo(scope['timezone'])).date().isoformat()
            daily = records.get('maintenance-day:' + digest((scope['scope'], day)), {})
            run = records.get('maintenance-run:' + digest((scope['scope'], (values['library'], run_sequence))), {})
            cap = scope['limits']
            remaining.append(
                dict(
                    scope=scope['scope'],
                    day=day,
                    timezone=scope['timezone'],
                    daily_items=max(0, cap['items_per_day'] - daily.get('items', 0)),
                    daily_output_bytes=max(0, cap['output_bytes_per_day'] - daily.get('output_bytes', 0)),
                    latest_run_items=max(0, cap['items_per_run'] - run.get('items', 0)),
                    run_sequence=run_sequence,
                )
            )
        allowance_error = None
    except ValueError as error:
        allowance_error = str(error)
    due = instant
    if values['action'] == 'scan':
        last = records.get('maintenance-schedule:' + values['library'], {})
        if last.get('admitted'):
            from datetime import datetime

            due = max(
                due, datetime.fromisoformat(last['admitted']) + timedelta(minutes=values['options']['cadence_minutes'])
            )
    queue_paused = (
        service.file_queue_paused()
        if values['action'] == 'scan'
        else service.store.get(
            'settings',
            service.pause_key(None, 'upscale' if values['action'].endswith('upscale') else 'optimize'),
            False,
        )
        if values['action'] in PROCESSING
        else False
    )
    held = (
        not rule.get('enabled')
        or rule.get('paused')
        or service.maintenance_paused(values['library'])
        or queue_paused
        or not permitted(values, instant)
    )
    return dict(
        counts=counts,
        remaining=remaining,
        allowance_error=allowance_error,
        next_permitted_window=next_window(values, instant),
        next_scan_window=next_window(values, due) if values['action'] == 'scan' else None,
        held=bool(held),
        projection_only=True,
        observed_at=instant.isoformat(),
    )
