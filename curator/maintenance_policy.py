"""Closed maintenance permission contract; standards and preferences grant nothing.

This module is pure validation/time policy. It performs no provider, filesystem,
queue or scheduler operations. Runtime permissions are separately reviewed records.
"""

from datetime import datetime, time, timedelta, timezone
import hashlib
import json
from pathlib import PurePosixPath
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import UserError

POLICY_VERSION = 1
SCAN_CADENCES = (15, 30, 60, 180, 360, 1440)
ACTIONS = frozenset({'scan', 'local_ai', 'prepare_upscale', 'prepare_encode', 'process_upscale', 'process_encode'})
PROCESSING = frozenset({'process_upscale', 'process_encode'})
PREPARATION = frozenset({'prepare_upscale', 'prepare_encode'})
LIMITS = frozenset(
    {'items_per_run', 'items_per_day', 'output_bytes_per_day', 'output_bytes_per_item', 'min_free_bytes'}
)
RULE_FIELDS = frozenset(
    {
        'name',
        'library',
        'action',
        'roots',
        'excluded_paths',
        'excluded_assets',
        'limits',
        'timezone',
        'windows',
        'quiet',
        'options',
    }
)


def digest(value):
    try:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        ).hexdigest()
    except (TypeError, ValueError):
        raise UserError('Maintenance settings must contain finite JSON values') from None


def finite_int(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise UserError('Choose a finite bounded ' + label)
    return value


def limits(value):
    if not isinstance(value, dict) or set(value) != LIMITS:
        raise UserError('Specify every maintenance item/output/free-space limit')
    return dict(
        items_per_run=finite_int(value['items_per_run'], 1, 2000, 'per-run item limit'),
        items_per_day=finite_int(value['items_per_day'], 1, 100000, 'daily item limit'),
        output_bytes_per_day=finite_int(value['output_bytes_per_day'], 0, 2**60, 'daily output limit'),
        output_bytes_per_item=finite_int(value['output_bytes_per_item'], 0, 2**50, 'per-item output limit'),
        min_free_bytes=finite_int(value['min_free_bytes'], 1, 2**60, 'minimum free space'),
    )


def minute(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d|24:00', value):
        raise UserError('Use an explicit HH:MM maintenance boundary')
    hour, minutes = map(int, value.split(':'))
    return 60 * hour + minutes


def windows(value):
    if not isinstance(value, list) or len(value) > 14:
        raise UserError('Choose at most 14 explicit maintenance windows')
    cleaned = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {'days', 'start', 'end'}:
            raise UserError('Each time window needs weekdays, start and end')
        days = row['days']
        if (
            not isinstance(days, list)
            or not days
            or any(type(day) is not int or not 0 <= day <= 6 for day in days)
            or len(days) != len(set(days))
        ):
            raise UserError('Choose distinct weekdays from Monday (0) to Sunday (6)')
        if minute(row['start']) >= minute(row['end']):
            raise UserError('Use a positive same-day window; split an overnight window explicitly')
        cleaned.append(dict(days=sorted(days), start=row['start'], end=row['end']))
    return cleaned


def paths(value, label, allow_empty=True):
    if not isinstance(value, list) or len(value) > 1000 or not value and not allow_empty:
        raise UserError('Choose explicit maintenance ' + label)
    out = []
    for entry in value:
        if not isinstance(entry, str) or not entry or '\x00' in entry or '\\' in entry:
            raise UserError('Maintenance paths must be absolute without traversal')
        path = PurePosixPath(entry)
        if not path.is_absolute() or '..' in path.parts or entry.startswith('//'):
            raise UserError('Maintenance paths must be absolute without traversal')
        if str(path) in out:
            raise UserError('Choose distinct maintenance paths')
        out.append(str(path))
    return sorted(out)


def options(action, value):
    if not isinstance(value, dict):
        raise UserError('Choose explicit maintenance action options')
    if action == 'scan':
        required = {
            'cadence_minutes',
            'inventory_limit',
            'page_size',
            'request_timeout_seconds',
            'scan_timeout_seconds',
            'probe_timeout_seconds',
            'response_limit_bytes',
            'probe_output_bytes',
            'max_pages',
        }
        if (
            set(value) != required
            or type(value['cadence_minutes']) is not int
            or value['cadence_minutes'] not in SCAN_CADENCES
        ):
            raise UserError('Choose an explicit bounded scan cadence (15, 30, 60, 180, 360 or 1440 minutes)')
        cleaned = dict(
            cadence_minutes=value['cadence_minutes'],
            inventory_limit=finite_int(value['inventory_limit'], 100, 10000, 'catalogue record cap'),
            page_size=finite_int(value['page_size'], 1, 200, 'inventory page size'),
            max_pages=finite_int(value['max_pages'], 1, 200, 'inventory page-request cap per verification pass'),
            request_timeout_seconds=finite_int(value['request_timeout_seconds'], 1, 20, 'Plex request timeout'),
            scan_timeout_seconds=finite_int(value['scan_timeout_seconds'], 10, 600, 'overall scan deadline'),
            probe_timeout_seconds=finite_int(value['probe_timeout_seconds'], 1, 60, 'new-media probe timeout'),
            response_limit_bytes=finite_int(
                value['response_limit_bytes'], 1024, 8 * 1024 * 1024, 'inventory response bound'
            ),
            probe_output_bytes=finite_int(
                value['probe_output_bytes'], 65536, 4 * 1024 * 1024, 'probe output-file bound'
            ),
        )
        if cleaned['page_size'] > cleaned['inventory_limit']:
            raise UserError('The page size cannot exceed the complete-inventory cap')
        return cleaned
    if action == 'local_ai':
        if (
            set(value) != {'model', 'model_digest', 'max_frames', 'max_input_bytes'}
            or not isinstance(value['model'], str)
            or not value['model'].strip()
            or len(value['model']) > 256
            or not re.fullmatch(r'[a-f0-9]{64}', str(value['model_digest']))
        ):
            raise UserError('Pin a verified local model and content limits')
        return dict(
            model=value['model'],
            model_digest=value['model_digest'],
            max_frames=finite_int(value['max_frames'], 1, 4, 'frame limit'),
            max_input_bytes=finite_int(value['max_input_bytes'], 1, 10 * 1024 * 1024, 'local provider input limit'),
        )
    allowed = (
        {'handbrake_preset'}
        if action.endswith('encode')
        else {'topaz_filter', 'topaz_rate_control', 'topaz_quality', 'topaz_bitrate_mbps'}
    )
    if set(value) != allowed:
        raise UserError('Pin every option for this exact processing action')
    if action.endswith('encode'):
        if (
            not isinstance(value['handbrake_preset'], str)
            or not value['handbrake_preset'].strip()
            or len(value['handbrake_preset']) > 512
        ):
            raise UserError('Choose an exact installed encoding preset')
    else:
        if (
            not isinstance(value['topaz_filter'], str)
            or not value['topaz_filter'].strip()
            or len(value['topaz_filter']) > 8192
        ):
            raise UserError('Choose an exact upscale filter')
        if value['topaz_rate_control'] not in {'quality', 'bitrate'}:
            raise UserError('Choose an explicit upscale rate mode')
        finite_int(value['topaz_quality'], 0, 100, 'upscale quality')
        finite_int(value['topaz_bitrate_mbps'], 1, 1000, 'upscale bitrate')
    digest(value)
    return dict(value)


def rule_values(value):
    if not isinstance(value, dict) or set(value) != RULE_FIELDS:
        raise UserError('Choose a complete maintenance rule without unknown fields')
    if not isinstance(value['name'], str) or not value['name'].strip() or len(value['name']) > 128:
        raise UserError('Choose a short maintenance rule name')
    if not isinstance(value['library'], str) or not value['library'] or len(value['library']) > 256:
        raise UserError('Choose one exact library')
    action = value['action']
    if not isinstance(action, str) or action not in ACTIONS:
        raise UserError('This action has no standing maintenance permission; use manual review')
    try:
        ZoneInfo(value['timezone'])
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise UserError('Choose an installed named timezone') from None
    excluded = value['excluded_assets']
    if (
        not isinstance(excluded, list)
        or len(excluded) > 1000
        or any(not isinstance(key, str) or not key or len(key) > 256 for key in excluded)
        or len(excluded) != len(set(excluded))
    ):
        raise UserError('Choose explicit distinct excluded item identities')
    result = dict(
        name=value['name'].strip(),
        library=value['library'],
        action=action,
        roots=paths(value['roots'], 'roots', False),
        excluded_paths=paths(value['excluded_paths'], 'exclusions'),
        excluded_assets=sorted(excluded),
        limits=limits(value['limits']),
        timezone=value['timezone'],
        windows=windows(value['windows']),
        quiet=windows(value['quiet']),
        options=options(action, value['options']),
    )
    if not result['windows']:
        raise UserError('Choose at least one permitted execution window')
    if action in PROCESSING and (
        not result['limits']['output_bytes_per_item']
        or result['limits']['output_bytes_per_item'] > result['limits']['output_bytes_per_day']
    ):
        raise UserError('Processing requires an enforceable per-item bound within its daily output allowance')
    return result


def boundary(day, minutes, zone, start, quiet=False):
    wall = datetime.combine(day, time()) + timedelta(minutes=minutes)
    candidates = set()
    for fold in (0, 1):
        instant = wall.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if instant.astimezone(zone).replace(tzinfo=None) == wall:
            candidates.add(instant)
    if not candidates:
        return None
    # Allowed intervals shrink across ambiguity. Quiet intervals expand.
    return (min if start == quiet else max)(candidates)


def permitted(rule, instant):
    if not isinstance(instant, datetime) or instant.tzinfo is None:
        raise UserError('Maintenance requires an explicit aware clock instant')
    zone = ZoneInfo(rule['timezone'])
    day = instant.astimezone(zone).date()
    instant = instant.astimezone(timezone.utc)

    def contains(row, quiet=False):
        if day.weekday() not in row['days']:
            return False
        start = boundary(day, minute(row['start']), zone, True, quiet)
        end = boundary(day, minute(row['end']), zone, False, quiet)
        return quiet if start is None or end is None else start <= instant < end

    return any(contains(row) for row in rule['windows']) and not any(contains(row, True) for row in rule['quiet'])


def excluded(rule, asset):
    path = PurePosixPath(asset.get('plex_path', ''))
    return (
        asset.get('id') in rule['excluded_assets']
        or not any(path.is_relative_to(PurePosixPath(root)) for root in rule['roots'])
        or any(path.is_relative_to(PurePosixPath(root)) for root in rule['excluded_paths'])
    )
