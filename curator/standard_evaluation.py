"""Pure scan findings and completion from a reviewed effective standard.

Only observed catalogue/probe facts count. This module never reads a provider,
creates work, approves a plan or treats optional transformations as unfinished.
"""

from datetime import date
import math

from .plex import Plex
from .quality import assess, display_geometry
from .standards import DIMENSIONS, type_digest


def identity(effective, config=None):
    config = config or {}
    encoding = effective['values']['encoding']
    return {key: effective[key] for key in ('kind', 'revision', 'type_revision', 'type_digest')} | {
        'effective_digest': type_digest(effective['values']),
        'encoding_thresholds': {
            field: encoding[field] if encoding[field] is not None else config.get(field, default)
            for field, default in (('max_mbps_1080', 18), ('max_mbps_4k', 55))
        },
    }


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _present(item, field):
    value = item.get(
        {'originally_available_at': 'originallyAvailableAt', 'content_rating': 'contentRating'}.get(field, field)
    )
    if field in {'genres', 'collections'}:
        return any(
            str(row.get('tag') or '').strip() for row in item.get('Genre' if field == 'genres' else 'Collection', [])
        )
    if field == 'year':
        return not isinstance(value, bool) and str(value).isdigit() and 1 <= int(value) <= 9999
    if field == 'originally_available_at':
        try:
            date.fromisoformat(value)
            return True
        except (TypeError, ValueError):
            return False
    return isinstance(value, str) and bool(value.strip())


def evaluate(asset, effective, config=None):
    """Return findings plus per-dimension completion; inputs remain unchanged.

    Cast completion means the current named credits satisfy the configured mode;
    it is not an assertion that computer vision identified everyone in the video.
    An empty cast needs explicit human identification, never invented people.
    """
    values, item = effective['values'], asset.get('item') or {}
    stamp = identity(effective, config)
    dimensions = {key: dict(state='met' if values[key]['enabled'] else 'disabled', missing=[]) for key in DIMENSIONS}
    findings = []

    def missing(dimension, fields, kind, reason, **evidence):
        dimensions[dimension].update(state='needs_attention', missing=fields)
        findings.append(dict(kind=kind, reason=reason, evidence=dict(dimension=dimension, missing=fields, **evidence)))

    if values['metadata']['enabled']:
        absent = [field for field in values['metadata']['required'] if not _present(item, field)]
        if absent:
            missing('metadata', absent, 'metadata', 'Required metadata is missing: ' + ', '.join(absent))
    if values['cast']['enabled']:
        credits = item.get('Role') or []
        if not credits or any(not str(row.get('tag') or '').strip() for row in credits):
            # Metadata is the existing review workflow for credits and known people.
            absent = ['known_people' if values['cast']['mode'] == 'known_people' else 'credits']
            dimensions['cast'].update(state='needs_attention', missing=absent)
            metadata = next((row for row in findings if row['kind'] == 'metadata'), None)
            if metadata:
                metadata['reason'] += '; cast needs review'
                metadata['evidence']['cast_missing'] = absent
            else:
                findings.append(
                    dict(kind='metadata', reason='Cast needs review', evidence=dict(dimension='cast', missing=absent))
                )
    if values['artwork']['enabled']:
        absent = [
            kind
            for kind in values['artwork']['required']
            if not Plex.artwork_path(item, 'cover' if kind == 'poster' else kind)
        ]
        if absent:
            missing('artwork', absent, 'artwork', 'Required artwork is missing: ' + ', '.join(absent), discovery=True)

    technical = asset.get('technical') or {}
    valid_probe = not asset.get('blocked') and _positive(technical.get('width')) and _positive(technical.get('height'))
    if valid_probe:
        technical_findings = assess(technical, config, values)
        findings.extend(technical_findings)
        if any(row['kind'] == 'upscale' and not row.get('evidence', {}).get('optional') for row in technical_findings):
            dimensions['upscaling'].update(state='needs_attention', missing=['resolution_target'])
        # assess folds efficient encoding into required upscale; count both facts.
        encoding_only = dict(values, upscaling=dict(values['upscaling'], enabled=False))
        if any(row['kind'] == 'optimize' for row in assess(technical, config, encoding_only)):
            dimensions['encoding'].update(state='needs_attention', missing=['bitrate_threshold'])
        bitrate_known = _positive(technical.get('bitrate')) or _positive(technical.get('size_bytes'))
        if (
            values['encoding']['enabled']
            and not values['encoding']['preserve_originals']
            and not technical.get('preserve_quality')
            and not (_positive(technical.get('duration_seconds')) and bitrate_known)
        ):
            dimensions['encoding'].update(state='unknown', reason='Duration or bitrate is not available')
        # An observation outside the supported ceiling is never a request to upscale.
        width, height = display_geometry(technical)
        if max(width, height) > 4096 or min(width, height) > 2160:
            findings = [row for row in findings if row['kind'] != 'upscale']
            if values['upscaling']['enabled'] and dimensions['upscaling']['state'] == 'needs_attention':
                dimensions['upscaling'].update(state='unknown', reason='Source geometry exceeds the processing ceiling')
    else:
        for key in ('upscaling', 'encoding'):
            if values[key]['enabled']:
                dimensions[key].update(state='unknown', reason='Technical analysis is unavailable')
        if any(values[key]['enabled'] for key in ('upscaling', 'encoding')):
            findings.append(
                dict(
                    kind='inspect',
                    reason=asset.get('blocked') or 'Technical analysis is unavailable',
                    evidence={'scan_error': asset.get('blocked') or 'Probe this media before processing'},
                )
            )
    if values['metadata']['enabled'] and values['metadata']['local_ai_suggestions']:
        findings.append(
            dict(
                kind='home',
                reason='Suggest a title, description, collections and cover frames using local AI',
                evidence=dict(optional=True, dimension='metadata'),
            )
        )
    for row in findings:
        row['evidence'] = dict(row.get('evidence') or {}, standard=stamp)
    states = {row['state'] for row in dimensions.values()}
    unavailable = (
        not asset.get('scanned')
        or asset.get('present') is False
        or asset.get('needs_scan')
        or asset.get('availability_error')
    )
    status = (
        'unknown'
        if unavailable or 'unknown' in states
        else 'needs_attention'
        if 'needs_attention' in states
        else 'complete'
    )
    return dict(standard=stamp, status=status, dimensions=dimensions, observed_at=asset.get('scanned')), findings


def summarize(rows):
    """Aggregate only observed items; an empty library is unassessed, not 100%."""
    result = dict(
        total=len(rows),
        complete=0,
        needs_attention=0,
        unknown=0,
        dimensions={key: dict(met=0, needs_attention=0, unknown=0, disabled=0) for key in DIMENSIONS},
    )
    for row in rows:
        result[row['status']] += 1
        for key, value in row['dimensions'].items():
            result['dimensions'][key][value['state']] += 1
    result['status'] = (
        'unknown' if not rows or result['unknown'] else 'needs_attention' if result['needs_attention'] else 'complete'
    )
    return result
