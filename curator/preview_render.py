"""Frozen single-clip preview plans and local FFmpeg rendering; never publication."""

import copy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import time
import uuid
from . import tools
from .errors import UserError
from .history import current_initiator
from .preview_cards import milliseconds
from .progress import EncodingProgress
from .quality import display_geometry
from .rules import FILE_KINDS, RESERVING, reserves_source, stable_id
from .store import now

FPS = 30


def frames(ms):
    return int(math.floor(ms * FPS / 1000 + 0.5))


def ms(frame_count):
    return int(round(frame_count * 1000 / FPS))


def timing(start_ms, requested_ms, duration_ms, values):
    milliseconds(start_ms, 0, 10**12)
    milliseconds(requested_ms, 1, 120000)
    available = int(math.floor(duration_ms * FPS / 1000 + 1e-6))
    start = frames(start_ms)
    end = min(start + frames(requested_ms), available)
    clip = end - start
    intro = frames(values['intro_duration_ms']) if values['intro'] else 0
    outro = frames(values['outro_duration_ms']) if values['outro'] else 0
    cross = frames(values['crossfade_ms'])
    black = frames(values['black_fade_ms'])
    audio = frames(values['audio_fade_ms'])
    x1, x2 = (cross if intro else 0), (cross if outro else 0)
    if start >= available or clip <= 0 or frames(requested_ms) <= 0:
        raise UserError('Choose an interval with remaining source footage')
    if (
        (intro and black + x1 > intro)
        or (outro and x2 + black > outro)
        or (x1 if intro else black) + (x2 if outro else black) > clip
        or 2 * audio > clip
    ):
        raise UserError('The chosen clip and cards are too short for these fades')
    return dict(
        start=start,
        end=end,
        clip=clip,
        intro=intro,
        outro=outro,
        x1=x1,
        x2=x2,
        black=black,
        audio=audio,
        total=intro + clip + outro - x1 - x2,
        start_ms=ms(start),
        end_ms=ms(end),
        total_ms=ms(intro + clip + outro - x1 - x2),
        requested_duration_ms=requested_ms,
        shortened=start + frames(requested_ms) > available,
        fps=FPS,
    )


def output_profile(media):
    try:
        width, height = display_geometry(media)
        video = next(
            s
            for s in media['streams']
            if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')
        )
        fps = float(Fraction(video.get('avg_frame_rate') or video.get('r_frame_rate', '0/1')))
        duration = media['duration_seconds']
        if not all(math.isfinite(v) and v > 0 for v in (width, height, fps, duration)):
            raise ValueError()
        if media.get('color_transfer') in {'smpte2084', 'arib-std-b67'}:
            raise UserError('HDR preview conversion is not supported yet; choose an SDR source')
        scale = min(1, 1280 / width, 720 / height)
        return dict(
            width=max(2, int(width * scale) // 2 * 2),
            height=max(2, int(height * scale) // 2 * 2),
            fps=FPS,
            video_stream=video['index'],
        )
    except (KeyError, ValueError, StopIteration, ZeroDivisionError):
        raise UserError('Preview needs verified source duration, geometry and frame rate') from None


def render_command(plan, card_paths, output):
    """Only server-generated values/paths enter argv; no client filter strings."""
    t, profile = plan['timing'], plan['profile']
    seconds = lambda count: format(count / FPS, '.9f')
    length, total = seconds(t['clip']), seconds(t['total'])
    width, height = profile['width'], profile['height']
    command = [
        plan['tools']['ffmpeg'],
        '-nostdin',
        '-hide_banner',
        '-n',
        '-threads',
        '2',
        '-filter_complex_threads',
        '1',
        '-ss',
        seconds(t['start']),
        '-t',
        length,
        '-i',
        plan['source']['local_path'],
    ]
    filters = [
        f'[0:{profile["video_stream"]}]fps=fps={FPS}:start_time=0,trim=start=0:duration={length},setpts=PTS-STARTPTS,scale={width}:{height},setsar=1,settb=1/{FPS}[clip]'
    ]
    for index, role in enumerate(card_paths, 1):
        duration = seconds(t[role])
        command += ['-loop', '1', '-framerate', str(FPS), '-t', duration, '-i', str(card_paths[role])]
        filters += [
            f'color=c=black:s={width}x{height}:r={FPS}:d={duration}[{role}bg]',
            f'[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,format=rgba,setpts=PTS-STARTPTS[{role}fg]',
            f'[{role}bg][{role}fg]overlay=(W-w)/2:(H-h)/2:shortest=1,format=yuv420p,setsar=1,fps={FPS},settb=1/{FPS}[{role}]',
        ]
    current, duration = 'clip', t['clip']
    if t['intro']:
        if t['x1']:
            filters.append(
                f'[intro][{current}]xfade=transition=fade:duration={seconds(t["x1"])}:offset={seconds(t["intro"] - t["x1"])}[front]'
            )
        else:
            filters.append(f'[intro][{current}]concat=n=2:v=1:a=0,fps=30,settb=1/30[front]')
        current, duration = 'front', duration + t['intro'] - t['x1']
    if t['outro']:
        if t['x2']:
            filters.append(
                f'[{current}][outro]xfade=transition=fade:duration={seconds(t["x2"])}:offset={seconds(duration - t["x2"])}[back]'
            )
        else:
            filters.append(f'[{current}][outro]concat=n=2:v=1:a=0,fps=30,settb=1/30[back]')
        current = 'back'
    tail = f'format=yuv420p,trim=duration={total},setpts=PTS-STARTPTS'
    if t['black']:
        tail += f',fade=t=in:st=0:d={seconds(t["black"])},fade=t=out:st={seconds(t["total"] - t["black"])}:d={seconds(t["black"])}'
    filters.append(f'[{current}]{tail}[video]')
    if plan['audio_stream'] is not None:
        audio = f'[0:{plan["audio_stream"]}]atrim=start=0:duration={length},aresample=48000:async=1:first_pts=0,apad=whole_dur={length},atrim=duration={length},asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:channel_layouts=stereo'
        if t['audio']:
            audio += f',afade=t=in:st=0:d={seconds(t["audio"])},afade=t=out:st={seconds(t["clip"] - t["audio"])}:d={seconds(t["audio"])}'
        audio += f',alimiter=limit=0.95:level=0:latency=1,adelay={ms(t["intro"] - t["x1"])}:all=1,apad,atrim=duration={total}[audio]'
        filters.append(audio)
    command += ['-filter_complex', ';'.join(filters), '-map', '[video]']
    if plan['audio_stream'] is not None:
        command += ['-map', '[audio]', '-c:a', 'aac', '-b:a', '128k', '-ac', '2', '-ar', '48000']
    else:
        command += ['-an']
    command += ['-c:v', plan['tools']['encoder']]
    command += (
        ['-preset', 'fast', '-crf', '22']
        if plan['tools']['encoder'] == 'libx264'
        else ['-allow_sw', '1', '-b:v', '2500k']
    )
    return command + [
        '-pix_fmt',
        'yuv420p',
        '-r',
        str(FPS),
        '-t',
        total,
        '-map_metadata',
        '-1',
        '-movflags',
        '+faststart',
        str(output),
    ]


class PreviewRendering:
    def preview_tools(self):
        config = self.config()
        ffmpeg, ffprobe = tools.executable(config, 'ffmpeg'), tools.executable(config, 'ffprobe')
        result = subprocess.run([ffmpeg, '-hide_banner', '-encoders'], capture_output=True, timeout=15, check=False)
        encoders = result.stdout.decode(errors='replace')
        encoder = next(
            (name for name in ('libx264', 'h264_videotoolbox') if re.search(r'\s' + name + r'\s', encoders)), None
        )
        if result.returncode or not encoder or not re.search(r'\saac\s', encoders):
            raise UserError('FFmpeg needs H.264 and AAC encoders for previews')
        return dict(
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            encoder=encoder,
            ffmpeg_identity=tools.fingerprint(ffmpeg),
            ffprobe_identity=tools.fingerprint(ffprobe),
        )

    @staticmethod
    def preview_source(asset):
        return {
            key: copy.deepcopy(asset[key])
            for key in ('id', 'library', 'rating_key', 'plex_path', 'local_path', 'fingerprint')
        }

    def preview_info(self, identity):
        asset = self.asset({'asset': identity})
        media = tools.probe(asset['local_path'], self.config())
        output_profile(media)
        audios = [s for s in media['streams'] if s.get('codec_type') == 'audio']
        tracks = [
            dict(
                index=s['index'],
                language=s.get('tags', {}).get('language', 'Unknown'),
                channels=s.get('channels'),
                default=bool(s.get('disposition', {}).get('default')),
            )
            for s in audios
        ]
        return dict(
            asset=identity,
            title=asset['title'],
            filename=Path(asset['local_path']).name,
            asset_version=stable_id(self.preview_source(asset), media),
            duration_ms=int(media['duration_seconds'] * 1000),
            audio_tracks=tracks,
            default_audio=next((s['index'] for s in tracks if s['default']), tracks[0]['index'] if tracks else None),
            defaults=self.preview_defaults(),
            cards=self.preview_cards()['cards'],
        )

    def create_preview_plan(self, data):
        if not isinstance(data, dict) or set(data) != {
            'asset',
            'asset_version',
            'start_ms',
            'values',
            'audio_stream',
            'defaults_revision',
        }:
            raise UserError('Invalid preview plan request')
        info = self.preview_info(data['asset'])
        if (
            data['asset_version'] != info['asset_version']
            or type(data['defaults_revision']) is not int
            or data['defaults_revision'] != info['defaults']['revision']
        ):
            raise UserError('Source or defaults changed; keep your draft and review a fresh plan')
        values = self.validate_preview_values(data['values'])
        chosen = data['audio_stream']
        if (
            info['audio_tracks']
            and (type(chosen) is not int or chosen not in {s['index'] for s in info['audio_tracks']})
        ) or (not info['audio_tracks'] and chosen is not None):
            raise UserError('Choose a verified source audio track')
        asset = self.asset({'asset': data['asset']})
        source = self.preview_source(asset)
        media = tools.probe(source['local_path'], self.config())
        if stable_id(source, media) != info['asset_version']:
            raise UserError('Source changed while planning; reopen the preview')
        profile = output_profile(media)
        if chosen is not None:
            audio = next(s for s in media['streams'] if s.get('index') == chosen)
            if (
                type(audio.get('channels')) is not int
                or not 1 <= audio['channels'] <= 8
                or int(audio.get('sample_rate', 0)) <= 0
            ):
                raise UserError('Unsupported or unknown source audio profile')
        frozen_cards = {}
        for role in ('intro', 'outro'):
            if values[role]:
                ref = values[role]
                row = self.preview_card_record(ref['card'])
                frozen_cards[role] = dict(
                    **ref,
                    name=row['name'],
                    sha256=hashlib.sha256(self.preview_card_image(ref['card'], ref['version'])).hexdigest(),
                )
        plan = dict(
            id=uuid.uuid4().hex,
            source=source,
            asset_version=info['asset_version'],
            values=values,
            defaults_revision=data['defaults_revision'],
            audio_stream=chosen,
            profile=profile,
            timing=timing(data['start_ms'], values['requested_duration_ms'], info['duration_ms'], values),
            cards=frozen_cards,
            tools=self.preview_tools(),
            created=now(),
            record_type='preview_plan',
        )
        with self.store.transaction():
            self.check_busy_sources({'id': 'new-preview', 'asset': asset['id']})
            for pending in self.store.where('tasks', kind=FILE_KINDS, status=RESERVING):
                if reserves_source(pending, asset['id']):
                    raise UserError('A file operation reserves this source')
            self.store.put('settings', 'preview-plan:' + plan['id'], plan)
        return self.public_preview_plan(plan)

    @staticmethod
    def public_preview_plan(plan):
        return {
            key: copy.deepcopy(plan[key])
            for key in (
                'id',
                'asset_version',
                'values',
                'defaults_revision',
                'audio_stream',
                'profile',
                'timing',
                'cards',
            )
        }

    def preview_plan(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{32}', identity):
            raise UserError('Preview plan not found')
        plan = self.store.get('settings', 'preview-plan:' + identity)
        if not plan or plan.get('record_type') != 'preview_plan':
            raise UserError('Preview plan not found')
        return plan

    def check_preview_plan(self, plan):
        asset = self.asset({'asset': plan['source']['id']})
        if self.preview_source(asset) != plan['source']:
            raise UserError('Preview source or mapping changed; review a fresh plan')
        paths = {}
        for role, ref in plan['cards'].items():
            raw = self.preview_card_image(ref['card'], ref['version'])
            if hashlib.sha256(raw).hexdigest() != ref['sha256']:
                raise UserError('Preview card changed; review a fresh plan')
            paths[role] = self.preview_card_path(ref['card'], ref['version'])
        for name in ('ffmpeg', 'ffprobe'):
            if tools.fingerprint(plan['tools'][name]) != plan['tools'][name + '_identity']:
                raise UserError('Preview processing tool changed; review a fresh plan')
        return asset, paths

    def generate_preview(self, identity, request_id):
        if not isinstance(request_id, str) or not re.fullmatch(r'[a-f0-9-]{32,36}', request_id):
            raise UserError('Use a unique preview submission key')
        plan = self.preview_plan(identity)
        key = 'preview-submit:' + request_id
        with self.lock, self.store.transaction():
            old = self.store.get('settings', key)
            if old:
                if old['plan'] != identity:
                    raise UserError('Submission key already belongs to another preview plan')
                return dict(id=old['task'], lane='optimize', status=self.get_task(old['task'])['status'])
            if self.preview_defaults()['revision'] != plan['defaults_revision']:
                raise UserError('Preview defaults changed; review a fresh plan')
            if any(self.preview_card_record(ref['card'])['hidden'] for ref in plan['cards'].values()):
                raise UserError('A selected card was hidden; review a fresh plan')
            asset, _ = self.check_preview_plan(plan)
            self.check_busy_sources({'id': 'new-preview', 'asset': asset['id']})
            for pending in self.store.where('tasks', kind=FILE_KINDS, status=RESERVING):
                if reserves_source(pending, asset['id']):
                    raise UserError('A file operation reserves this source')
            task = dict(
                id=uuid.uuid4().hex,
                asset=asset['id'],
                library=asset['library'],
                title=asset['title'],
                kind='preview_render',
                version=1,
                approval=1,
                status='queued',
                plan={'preview': identity},
                source=asset['fingerprint'],
                created=now(),
                updated=now(),
                initiator=current_initiator(),
            )
            self.store.put('tasks', task['id'], task)
            self.store.put('settings', key, dict(plan=identity, task=task['id']))
            self.store.event(task['id'], dict(action='preview queued', plan=identity))
            for worker in self.queue_workers.get('optimize', {}).values():
                worker['wake'].set()
        return dict(
            id=task['id'],
            status='queued',
            lane='optimize',
            paused=self.store.get('settings', self.pause_key(None, 'optimize'), False),
        )

    def execute_preview(self, task):
        plan = self.preview_plan(task['plan']['preview'])
        asset, cards = self.check_preview_plan(plan)
        folder = self.store.root / 'preview-outputs' / task['id'] / uuid.uuid4().hex
        folder.mkdir(parents=True, mode=0o700)
        output, log_path = folder / 'candidate.mp4', folder / 'tool.log'
        self._save(task, progress={'phase': 'Checking preview source'})
        source_hash = tools.digest(asset['local_path'])
        if task['id'] in self.cancels:
            raise UserError('Preview cancelled; original preserved')
        telemetry = EncodingProgress('preview_render', plan['timing']['total'] / FPS)
        started = time.monotonic()
        with log_path.open('xb') as log:
            process = subprocess.Popen(
                render_command(plan, cards, output), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL
            )
            try:
                while process.poll() is None:
                    if task['id'] in self.cancels or time.monotonic() - started > 1800:
                        raise UserError('Preview cancelled or timed out; original and previous candidates preserved')
                    self._save(
                        task,
                        progress={'phase': 'Rendering preview', **telemetry.read(log_path, time.monotonic() - started)},
                    )
                    time.sleep(0.2)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                process.wait()
        if process.returncode:
            raise UserError('FFmpeg could not render the preview; inspect tools and input profiles')
        if task['id'] in self.cancels:
            raise UserError('Preview cancelled; original and prior candidates preserved')
        self._save(task, progress={'phase': 'Validating preview'})
        self.check_preview_plan(plan)
        if tools.digest(asset['local_path']) != source_hash:
            raise UserError('Source bytes changed during preview rendering')
        result = tools.probe(output, plan['tools'])
        audio = [s for s in result['streams'] if s.get('codec_type') == 'audio']
        expected_audio = plan['audio_stream'] is not None
        if (
            result['codec'] != 'h264'
            or result['width'] != plan['profile']['width']
            or result['height'] != plan['profile']['height']
            or abs(result['duration_seconds'] - plan['timing']['total'] / FPS) > 0.1
            or len(audio) != int(expected_audio)
            or (audio and (audio[0].get('codec_name') != 'aac' or audio[0].get('channels') != 2))
            or not tools.output_decodes(output, plan['tools'])
        ):
            raise UserError('Preview output failed validation; retained for inspection')
        output.chmod(0o600)
        digest = tools.digest(output)
        with self.store.transaction():
            if task['id'] in self.cancels or self.get_task(task['id'])['status'] != 'running':
                raise UserError('Preview cancelled; retained output is not a selected candidate')
            self.store.put(
                'settings',
                'preview-output:' + task['id'],
                dict(
                    path=str(output),
                    sha256=digest,
                    result=result,
                    plan=plan['id'],
                    source_hash=source_hash,
                    created=now(),
                ),
            )
            task.update(
                status='awaiting_review',
                result=result,
                output_hash=digest,
                source_hash=source_hash,
                updated=now(),
                progress={'phase': 'Preview ready', 'percent': 100},
            )
            self.store.put('tasks', task['id'], task)
            self.store.event(
                task['id'], dict(action='preview rendered and validated', plan=plan['id'], output_hash=digest)
            )
