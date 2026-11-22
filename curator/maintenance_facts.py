"""Narrow adapter to the canonical #107 standard resolver/evaluator.

No fallback to historical recommendations: absent, unknown or inconsistent facts
cannot authorize maintenance. Effective inherited/global thresholds are pinned.
"""

import copy

from .errors import UserError
from .maintenance_policy import digest

FACTS_VERSION = 1


def evaluated(service, asset):
    try:
        from .standard_evaluation import identity, evaluate
    except ImportError:
        raise UserError('Standards evaluation is unavailable; maintenance stays disabled for this item') from None
    if (
        not asset.get('scanned')
        or not asset.get('present', True)
        or asset.get('blocked')
        or asset.get('availability_error')
    ):
        raise UserError('A completed scan and available, stable source are required')
    effective = service.library_standard(asset['library'])
    config = service.config()
    stamp = identity(effective, config)
    completion, findings = evaluate(asset, effective, config)
    required = {'kind', 'revision', 'type_revision', 'type_digest', 'effective_digest', 'encoding_thresholds'}
    if (
        not isinstance(stamp, dict)
        or not required <= set(stamp)
        or completion.get('standard') != stamp
        or completion.get('status') not in {'complete', 'needs_attention'}
        or completion.get('observed_at') != asset['scanned']
    ):
        raise UserError('Standard facts are unknown, stale or inconsistent; refresh and review first')
    if any(row.get('evidence', {}).get('standard') != stamp for row in findings):
        raise UserError('Finding provenance does not match the current effective standard')
    return copy.deepcopy(dict(version=FACTS_VERSION, standard=stamp, completion=completion, findings=findings))


def standard_identity(service, library):
    try:
        from .standard_evaluation import identity
    except ImportError:
        raise UserError('Standards integration is not available; no maintenance rule can be enabled') from None
    value = identity(service.library_standard(library), service.config())
    if not isinstance(value, dict) or not {
        'kind',
        'revision',
        'type_revision',
        'type_digest',
        'effective_digest',
        'encoding_thresholds',
    } <= set(value):
        raise UserError('Effective standard identity is incomplete')
    digest(value)
    return value


def finding_for(action, facts):
    completion = facts['completion']
    if completion['status'] == 'complete':
        return None
    if action == 'scan':
        return dict(
            kind='scan',
            reason='Assess this new arrival using its current effective standard',
            evidence={'standard': facts['standard']},
        )
    kind, dimension = (
        ('home', 'metadata')
        if action == 'local_ai'
        else ('upscale', 'upscaling')
        if action.endswith('upscale')
        else ('optimize', 'encoding')
    )
    current = completion.get('dimensions', {}).get(dimension, {})
    if current.get('state') in {'disabled', 'met'}:
        return None
    if current.get('state') != 'needs_attention':
        raise UserError('The action-relevant standard facts are unknown')
    if action == 'local_ai':
        return dict(
            kind='home',
            reason='Propose metadata locally; all saves remain manual',
            evidence={'standard': facts['standard'], 'ai_assisted': True},
        )
    choices = [
        row for row in facts['findings'] if row.get('kind') == kind and not row.get('evidence', {}).get('optional')
    ]
    if len(choices) != 1:
        raise UserError('There is no unique required processing plan for this standard')
    return copy.deepcopy(choices[0])
