"""Read-only preview playback and explicit, atomic Curator-only selection."""

from pathlib import Path
import re
import subprocess
from . import tools
from .errors import UserError
from .store import now


def video_range(value, size):
    if size <= 0:
        raise UserError('Video is empty')
    if not value:
        return 0, size - 1, False
    if len(value) > 128:
        raise UserError('Unsupported video byte range')
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
    if not match or not any(match.groups()):
        raise UserError('Unsupported video byte range')
    left, right = match.groups()
    if not left:
        length = int(right)
        if length <= 0:
            raise UserError('Invalid video byte range')
        return max(0, size - length), size - 1, True
    start, end = int(left), min(int(right), size - 1) if right else size - 1
    if start > end or start >= size:
        raise UserError('Video byte range is unavailable')
    return start, end, True


class PreviewReview:
    def preview_selection(self, asset_id):
        return self.store.get('settings', 'preview-selection:' + asset_id, dict(revision=0, job=None))

    def preview_candidate(self, identity):
        task = self.get_task(identity)
        if (
            task['kind'] != 'preview_render'
            or task.get('deleted')
            or task['status'] not in {'awaiting_review', 'applied', 'rejected'}
        ):
            raise UserError('No completed preview candidate is available')
        output = self.store.get('settings', 'preview-output:' + identity)
        if not output or output['plan'] != task['plan']['preview'] or output['sha256'] != task.get('output_hash'):
            raise UserError('Preview candidate identity changed')
        path = Path(output['path'])
        root = self.store.root / 'preview-outputs'
        if (
            not path.is_relative_to(root)
            or any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(self.store.root))
            or not path.is_file()
        ):
            raise UserError('Retained preview file is unavailable')
        if tools.digest(path) != output['sha256']:
            raise UserError('Preview bytes changed; generate a new candidate')
        return output, path

    def preview_job(self, identity):
        task = self.get_task(identity)
        if task['kind'] != 'preview_render':
            raise UserError('Preview job not found')
        plan = self.preview_plan(task['plan']['preview'])
        candidate = None
        if task['status'] in {'awaiting_review', 'applied', 'rejected'} and not task.get('deleted'):
            output, _ = self.preview_candidate(identity)
            candidate = dict(
                url='/api/preview/video?job=' + identity,
                sha256=output['sha256'],
                duration_ms=round(output['result']['duration_seconds'] * 1000),
                width=output['result']['width'],
                height=output['result']['height'],
                has_audio=plan['audio_stream'] is not None,
            )
        return dict(
            id=task['id'],
            asset=task['asset'],
            library=task['library'],
            title=task['title'],
            version=task['version'],
            status=task['status'],
            error=task.get('error'),
            progress=task.get('progress'),
            candidate=candidate,
            plan=self.public_preview_plan(plan),
            selection=self.preview_selection(task['asset']),
            paused=self.store.get('settings', self.pause_key(None, 'optimize'), False),
            lane='optimize',
        )

    def select_preview(self, identity, version, selection_revision):
        task = self.get_task(identity)
        if type(version) is not int or task['version'] != version or type(selection_revision) is not int:
            raise UserError('Preview changed; reopen review before selecting it')
        if task['status'] not in {'awaiting_review', 'applied'}:
            raise UserError('Only a validated, completed preview can be selected')
        output, path = self.preview_candidate(identity)
        plan = self.preview_plan(task['plan']['preview'])
        asset, _ = self.check_preview_plan(plan)
        self.check_busy_sources(task)
        if tools.digest(asset['local_path']) != output['source_hash']:
            raise UserError('Source bytes changed since this preview; review a fresh candidate')
        with self.store.transaction():
            current = self.get_task(identity)
            if (
                current['version'] != version
                or current['status'] not in {'awaiting_review', 'applied'}
                or current.get('deleted')
            ):
                raise UserError('Preview changed during selection')
            self.check_preview_plan(plan)
            self.check_busy_sources(current)
            selected = self.preview_selection(task['asset'])
            if selected['revision'] != selection_revision:
                raise UserError('The selected preview changed; keep this candidate and reopen review')
            if selected['job'] == identity and selected.get('sha256') == output['sha256']:
                return selected
            # Recheck the retained candidate immediately before changing the pointer.
            if tools.digest(path) != output['sha256']:
                raise UserError('Preview changed during selection')
            updated = dict(
                revision=selected['revision'] + 1,
                job=identity,
                sha256=output['sha256'],
                plan=plan['id'],
                selected_at=now(),
            )
            self.store.put('settings', 'preview-selection:' + task['asset'], updated)
            current.update(
                status='applied', updated=now(), result={**current.get('result', {}), 'saved_in_curator': True}
            )
            current.pop('approval', None)
            self.store.put('tasks', identity, current)
            self.store.event(
                identity,
                dict(
                    action='preview selected in Curator',
                    previous_job=selected['job'],
                    revision=updated['revision'],
                    output_hash=output['sha256'],
                ),
            )
        return updated

    def discard_preview(self, identity, version):
        with self.store.transaction():
            task = self.get_task(identity)
            if (
                task['kind'] != 'preview_render'
                or task['version'] != version
                or type(version) is not int
                or task['status'] != 'awaiting_review'
            ):
                raise UserError('Preview changed; reopen review')
            if self.preview_selection(task['asset'])['job'] == identity:
                raise UserError('Select a replacement before discarding the saved preview')
            task.update(status='rejected', version=version + 1, updated=now())
            self.store.put('tasks', identity, task)
            self.store.event(identity, dict(action='preview discarded; bytes retained'))
        return dict(discarded=True)

    def preview_source_video(self, identity, version):
        info = self.preview_info(identity)
        if info['asset_version'] != version:
            raise UserError('Source changed; reopen the preview editor')
        asset = self.asset({'asset': identity})
        return Path(asset['local_path'])

    def preview_source_frame(self, identity, version, start_ms):
        info = self.preview_info(identity)
        if info['asset_version'] != version:
            raise UserError('Source changed; reopen the preview editor')
        source = Path(self.asset({'asset': identity})['local_path'])
        if type(start_ms) is not int or not 0 <= start_ms < info['duration_ms']:
            raise UserError('Choose a source frame inside the video')
        command = [
            tools.executable(self.config(), 'ffmpeg'),
            '-nostdin',
            '-v',
            'error',
            '-ss',
            str(start_ms / 1000),
            '-i',
            str(source),
            '-frames:v',
            '1',
            '-vf',
            'scale=640:360:force_original_aspect_ratio=decrease',
            '-f',
            'image2pipe',
            '-c:v',
            'mjpeg',
            '-',
        ]
        result = subprocess.run(command, capture_output=True, timeout=30, check=False)
        if result.returncode or len(result.stdout) > 4 * 1024 * 1024 or not result.stdout.startswith(b'\xff\xd8\xff'):
            raise UserError('Source frame is unavailable')
        return result.stdout
