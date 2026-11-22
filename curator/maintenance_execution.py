"""Pinned maintenance execution tools and the final revoke/start boundary."""

import copy
import os
from pathlib import Path
import re
import signal
import subprocess
import sys

from . import tools
from .errors import UserError
from .history import acting
from .maintenance_policy import PROCESSING, PREPARATION, digest
from .store import now

TOOL_CONFIG = ('ffmpeg', 'ffprobe', 'handbrake', 'handbrake_preset_import', 'topaz')


def file_identity(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise UserError('A pinned maintenance tool/model/preset file is unavailable')
    before = tools.fingerprint(path)
    result = dict(path=str(path), fingerprint=before, sha256=tools.digest(path))
    if tools.fingerprint(path) != before:
        raise UserError('A maintenance tool/model/preset changed while being checked')
    return result


def stop_group(process, hard=False):
    try:
        os.killpg(process.pid, signal.SIGKILL if hard else signal.SIGTERM)
    except ProcessLookupError:
        pass


class MaintenanceExecution:
    def maintenance_tool_snapshot(self, values, captured=None):
        action = values['action']
        config = {key: self.config().get(key) for key in TOOL_CONFIG}
        if action == 'scan':
            raise UserError(
                'Recurring Scan permission is unavailable until a scope/item-bounded inventory adapter is verified; manual completed scans can supply new-arrival facts'
            )
        if action == 'local_ai':
            raise UserError(
                'Automatic local AI is unavailable until pinned model digest and local-only execution can be independently verified; use manual AI assist'
            )
        settings = {key: value for key, value in config.items() if value is not None}
        settings.update(values['options'])
        if action in PREPARATION:
            # This permission creates a proposal only, never a subprocess. The
            # later manual queue approval performs the normal tool/preset checks.
            return dict(settings=settings, config=digest(config), files=[], proposal_only=True)
        if action not in PROCESSING or os.name != 'posix' or not hasattr(signal, 'SIGXFSZ'):
            raise UserError('This platform cannot enforce the approved hard output-file bound')
        try:
            import resource

            if not hasattr(resource, 'RLIMIT_FSIZE'):
                raise ImportError()
        except ImportError:
            raise UserError('Hard output-file limits are unavailable; processing stays manual') from None
        if captured is not None:
            if captured.get('config') != digest(config):
                raise UserError('Processing tool configuration changed; review the rule again')
            for row in captured.get('files', []):
                if file_identity(row['path']) != row:
                    raise UserError('A pinned executable, model or preset changed; review the rule again')
            if captured.get('model_environment'):
                current = {key: os.environ.get(key) for key in ('TVAI_MODEL_DIR', 'TVAI_MODEL_DATA_DIR')}
                if current != captured['model_environment']:
                    raise UserError('Topaz model locations changed; review the rule again')
            return copy.deepcopy(captured)
        paths = [
            tools.executable(settings, key)
            for key in ('ffprobe', 'ffmpeg', 'handbrake' if action == 'process_encode' else 'topaz')
        ]
        snapshot = dict(config=digest(config), settings=settings, files=[])
        if action == 'process_encode':
            settings.update(
                tools.freeze_handbrake_preset(
                    settings, settings['handbrake_preset'], self.store.root / 'maintenance-presets'
                )
            )
            paths.append(settings['handbrake_preset_file'])
            if settings.get('handbrake_preset_import'):
                paths.append(settings['handbrake_preset_import'])
        else:
            # A name alone is not model-version evidence. Pin installed matching
            # model artifacts; do not grant an unknown future downloaded model.
            model = re.search(
                r'(?:^|:)model=([A-Za-z0-9_-]+)(?:[: ,]|$)', settings['topaz_filter'].removeprefix('tvai_up=')
            )
            if not model:
                raise UserError('The selected Topaz model cannot be uniquely identified; keep this action manual')
            environment = {key: os.environ.get(key) for key in ('TVAI_MODEL_DIR', 'TVAI_MODEL_DATA_DIR')}
            models = (
                Path(
                    environment['TVAI_MODEL_DIR']
                    or Path(tools.executable(settings, 'topaz')).parent.parent / 'Resources' / 'models'
                )
                .expanduser()
                .resolve()
            )
            data = (
                Path(environment['TVAI_MODEL_DATA_DIR'] or Path.home() / 'Library' / 'Caches' / 'Curator' / 'Topaz')
                .expanduser()
                .resolve()
            )
            candidates = []
            for folder in (models, data):
                if folder.is_dir():
                    candidates.extend(
                        path
                        for path in folder.iterdir()
                        if path.is_file()
                        and path.suffix.lower() in {'.onnx', '.bin', '.pt', '.safetensors'}
                        and re.search(r'(^|[-_.])' + re.escape(model[1]) + r'($|[-_.])', path.name)
                    )
            if not candidates or len(candidates) > 32:
                raise UserError(
                    'Installed selected-model version evidence is unavailable; Topaz maintenance stays manual'
                )
            paths.extend(candidates)
            snapshot['model_environment'] = environment
        snapshot['files'] = [file_identity(path) for path in sorted(set(map(str, paths)))]
        return snapshot

    def validate_maintenance_permission(self, rule):
        approval = rule.get('approval')
        if not rule.get('enabled') or not approval or approval.get('initiator') != 'operator':
            raise UserError('No current explicit maintenance permission covers this action')
        snapshot = approval['snapshot']
        current = self.maintenance_enable_snapshot(rule, captured=snapshot['tools'])
        # New scans advance the current watermark. They do not broaden the frozen
        # activation boundary; replacing its baseline generation is a scope change.
        current['watermark'] = snapshot['watermark']
        if current != snapshot or digest(snapshot) != approval.get('digest'):
            raise UserError('Maintenance permission is stale; review scope, standard, tools and limits again')
        return snapshot

    def maintenance_start_process(self, task, command, stream, environment):
        if not task.get('maintenance'):
            return subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, env=environment)
        with self.lock:
            with self.store.transaction(), acting('rule'):
                claim = self.maintenance_start_guard(task, starting=True)
                claim = self.maintenance_start_allowance(claim, self.maintenance_rule(claim['rule']))
                self.store.record(
                    'maintenance_start',
                    'Bounded separate-output subprocess start attempted',
                    library=task['library'],
                    details={
                        'rule': claim['rule'],
                        'claim': claim['id'],
                        'action': claim['action'],
                        'output_bytes': claim['output_bound'],
                    },
                )
                claim.update(phase='attempted', updated=now())
                self.store.put('settings', claim['id'], claim)
            # Audit is durable before exec; the service lock remains held through
            # Popen so disable cannot win and then race a new subprocess start.
            bounded = [
                sys.executable,
                str(Path(__file__).with_name('limited_exec.py')),
                str(claim['output_bound']),
                '--',
                *command,
            ]
            return subprocess.Popen(
                bounded, stdout=stream, stderr=subprocess.STDOUT, env=environment, start_new_session=True
            )

    def maintenance_stop_process(self, task, process, hard=False):
        if task.get('maintenance'):
            stop_group(process, hard)
        elif hard:
            process.kill()
        else:
            process.terminate()
