"""Explicit, per-output resolution exceptions and reviewed original-source 4x plans."""

import hashlib
import json

from . import tools
from .errors import UserError
from .history import current_initiator
from .store import now


PROCESSING_KEYS = {
    'topaz',
    'ffmpeg',
    'ffprobe',
    'topaz_filter',
    'topaz_rate_control',
    'topaz_quality',
    'topaz_bitrate_mbps',
}


def stamp(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def exception_binding(task):
    return stamp({k: task.get(k) for k in ('version', 'source_hash', 'output_hash', 'result', 'validation')})


def processing_validation(task):
    issues = task.get('validation') or []
    exception = task.get('resolution_exception') or {}
    if (
        task.get('kind') == 'upscale'
        and issues == [tools.RESOLUTION_FLOOR]
        and exception.get('binding') == exception_binding(task)
        and exception.get('operator') == 'operator'
        and exception.get('reason')
    ):
        return []
    return issues


class UpscaleRecovery:
    def _upscale_recovery_task(self, key, version):
        task = self.get_task(key)
        if (
            type(version) is not int
            or task['version'] != version
            or task.get('deleted')
            or task['kind'] != 'upscale'
            or task['status'] not in {'recommendation', 'failed', 'blocked', 'cancelled'}
            or task.get('published')
            or task.get('publication_error')
        ):
            raise UserError('Task changed or is unavailable for upscale recovery; reopen it')
        self.check_busy_sources(task)
        return task, self.asset(task)

    def _upscale_recovery_snapshot(self, key, version):
        task, asset = self._upscale_recovery_task(key, version)
        settings = task.get('tool_settings') or {
            **self.config(),
            **self.processing_defaults().get(task['library'], {}).get('upscale', {}),
        }
        settings = {k: v for k, v in settings.items() if k in PROCESSING_KEYS}
        source = asset.get('technical') or {}
        redo, error = None, None
        try:
            redo = tools.upscale_4x_settings(source, settings)
        except UserError as failure:
            error = str(failure)
        identity = {
            k: task.get(k)
            for k in ('version', 'status', 'source_hash', 'output_hash', 'output', 'validation', 'result', 'plan')
        }
        token = stamp(dict(task=identity, fingerprint=asset['fingerprint'], technical=source, settings=settings))
        predicted = tools.upscale_output_geometry(source, settings)
        shortfall = bool(predicted and (max(predicted) < 1920 or min(predicted) < 720))
        return (
            task,
            asset,
            settings,
            redo,
            dict(
                needs_recovery=shortfall or tools.RESOLUTION_FLOOR in (task.get('validation') or []),
                id=key,
                version=version,
                token=token,
                source_dimensions=list(tools.display_geometry(source))
                if source.get('width') and source.get('height')
                else None,
                output_dimensions=list(tools.display_geometry(task['result'])) if task.get('result') else None,
                target='1080-class: long edge at least 1920, short edge at least 720; ceiling 4096 × 2160',
                validation=task.get('validation') or [],
                can_review=bool(
                    task['status'] == 'blocked'
                    and task.get('output')
                    and task.get('source_hash')
                    and task.get('output_hash')
                    and task.get('validation') == [tools.RESOLUTION_FLOOR]
                ),
                redo=dict(
                    allowed=redo is not None,
                    error=error,
                    dimensions=list(tools.upscale_output_geometry(source, redo)) if redo else None,
                    filter=redo.get('topaz_filter') if redo else settings.get('topaz_filter'),
                    encoding={
                        k: (redo or settings).get(k)
                        for k in ('topaz_rate_control', 'topaz_quality', 'topaz_bitrate_mbps')
                    },
                ),
            ),
        )

    def upscale_recovery_preview(self, key, version):
        with self.operation_lock(key):
            return self._upscale_recovery_snapshot(key, version)[-1]

    def upscale_recover(self, key, version, action, token):
        if action not in {'review_resolution', 'prepare_4x'} or not isinstance(token, str):
            raise UserError('Choose a displayed upscale recovery option')
        if current_initiator() != 'operator':
            raise UserError('Upscale recovery requires explicit operator approval')
        with self.operation_lock(key):
            task, asset, settings, redo, preview = self._upscale_recovery_snapshot(key, version)
            if preview['token'] != token:
                raise UserError('Recovery preview changed; review the current plan first')
            evidence = None
            if action == 'review_resolution':
                if not preview['can_review']:
                    raise UserError('Only a retained output with a resolution-only failure can be reviewed')
                evidence = self._revalidate_resolution_output(task, asset, settings)
            elif redo is None:
                raise UserError(preview['redo']['error'])
            with self.store.transaction():
                current, current_asset, _, _, current_preview = self._upscale_recovery_snapshot(key, version)
                if current_preview['token'] != token:
                    raise UserError('Task or source changed during recovery; reopen it')
                if evidence and (
                    tools.fingerprint(current['output']) != evidence['output_fingerprint']
                    or current_asset['fingerprint'] != evidence['source_fingerprint']
                ):
                    raise UserError('Source or retained output changed during validation')
                current.update(version=version + 1, comparison_loaded=False, error=None, updated=now())
                current.pop('approval', None)
                if action == 'review_resolution':
                    current.update(status='awaiting_review', result=evidence['result'])
                    current['resolution_exception'] = dict(
                        operator='operator',
                        reason='Explicitly review retained output below the resolution floor',
                        at=now(),
                        source_hash=current['source_hash'],
                        output_hash=current['output_hash'],
                        binding=exception_binding(current),
                        target=preview['target'],
                    )
                else:
                    if current.get('output'):
                        retained = {
                            k: current.get(k)
                            for k in (
                                'output',
                                'source_hash',
                                'output_hash',
                                'result',
                                'validation',
                                'tool_settings',
                                'resolution_exception',
                            )
                        }
                        self.store.event(key, dict(action='previous upscale output retained', attempt=retained))
                        current.setdefault('retained_attempts', []).append(retained)
                    for field in (
                        'output',
                        'source_hash',
                        'output_hash',
                        'result',
                        'validation',
                        'resolution_exception',
                        'progress',
                        'publication_error',
                    ):
                        current.pop(field, None)
                    current.update(
                        status='recommendation',
                        plan={
                            **current.get('plan', {}),
                            'upscale_recovery': dict(
                                settings=redo,
                                source=current_asset['fingerprint'],
                                dimensions=preview['redo']['dimensions'],
                            ),
                        },
                    )
                self.store.put('tasks', key, current)
                self.store.event(
                    key,
                    dict(
                        action=action,
                        version=current['version'],
                        output_hash=current.get('output_hash'),
                        predicted=preview['redo']['dimensions'],
                    ),
                )
            return current

    def _revalidate_resolution_output(self, task, asset, settings):
        source, output = asset['local_path'], task['output']
        before = tools.fingerprint(output)
        if tools.digest(source) != task['source_hash'] or tools.digest(output) != task['output_hash']:
            raise UserError('Source or retained output changed after processing')
        source_media, result = tools.probe(source, settings), tools.probe(output, settings)
        if tools.validate(source_media, result) != [tools.RESOLUTION_FLOOR] or not tools.output_decodes(
            output, settings
        ):
            raise UserError('Retained output has other validation failures; resolution cannot waive them')
        if (
            tools.digest(source) != task['source_hash']
            or tools.digest(output) != task['output_hash']
            or tools.fingerprint(output) != before
        ):
            raise UserError('Source or retained output changed during validation')
        self.asset(task)
        return dict(result=result, output_fingerprint=before, source_fingerprint=asset['fingerprint'])
