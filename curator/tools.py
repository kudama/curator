"""Bounded media tools. Commands are argv arrays, never shell text."""
import base64
import hashlib
import json
import os
import subprocess
import shutil
import uuid
from pathlib import Path

from .quality import display_geometry


TOPAZ = '/Applications/Topaz Video.app/Contents/MacOS/'


def fingerprint(path):
    stat = Path(path).stat()
    return dict(size=stat.st_size, modified=stat.st_mtime_ns, inode=stat.st_ino, device=stat.st_dev)


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def executable(config, name):
    fallback = {'ffprobe': TOPAZ + 'ffprobe', 'ffmpeg': TOPAZ + 'ffmpeg',
                'topaz': TOPAZ + 'ffmpeg', 'handbrake': '/opt/homebrew/bin/HandBrakeCLI'}
    if name in {'ffmpeg', 'ffprobe'} and not config.get(name):
        candidates = [fallback[name], shutil.which(name), '/opt/homebrew/bin/' + name,
                      '/usr/local/bin/' + name]
        found = next((p for p in candidates if p and Path(p).is_absolute()
                      and Path(p).is_file() and os.access(p, os.X_OK)), None)
        if not found:
            raise ValueError(f'{name} was not found. Install FFmpeg or set its absolute path in Settings.')
        return found
    if name == 'handbrake' and not config.get(name):
        candidates = ['/Applications/HandBrakeCLI', shutil.which('HandBrakeCLI'),
                      '/opt/homebrew/bin/HandBrakeCLI', '/usr/local/bin/HandBrakeCLI']
        found = next((p for p in candidates if p and Path(p).is_file() and os.access(p, os.X_OK)), None)
        if not found:
            raise ValueError('HandBrakeCLI was not found. Install the CLI or set its path in Settings; the GUI app cannot run these jobs.')
        return found
    path = Path(config.get(name) or fallback[name])
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f'{name} executable unavailable; configure its installed path')
    return str(path)


def parse_handbrake_presets(text):
    """Read CLI folder/name indentation; descriptions are one level deeper."""
    folders, presets, last = {}, [], None
    for line in text.splitlines():
        value = line.strip()
        if not value or value.startswith('[') or value.startswith('HandBrake has exited'):
            continue
        indent = len(line) - len(line.lstrip(' '))
        if indent % 4:
            continue
        depth = indent // 4
        if value.endswith('/'):
            folders = {k: v for k, v in folders.items() if k < depth}
            folders[depth] = value[:-1]
            last = None
        elif depth == 0 or depth - 1 in folders:
            group = '/'.join(folders[k] for k in sorted(folders) if k < depth)
            entry = dict(name=value, group=group, path=(group + '/' if group else '') + value, description='')
            if not any(p['path'] == entry['path'] for p in presets):
                presets.append(entry)
            last = (depth, entry)
        elif last and depth > last[0]:
            last[1]['description'] += (' ' if last[1]['description'] else '') + value
    return presets


def _preset_import_args(settings):
    configured = settings.get('handbrake_preset_import')
    if not configured:
        return ['--preset-import-gui']
    path = Path(configured)
    if not path.is_absolute() or not path.is_file() or path.suffix.lower() != '.json':
        raise ValueError('Custom preset import must be an existing absolute JSON file path')
    return ['--preset-import-file', str(path)]


def handbrake_presets(settings):
    exe = executable(settings, 'handbrake')
    try:
        result = subprocess.run([exe, *_preset_import_args(settings), '--preset-list'], capture_output=True,
                                text=True, timeout=15)
        text = result.stdout + '\n' + result.stderr
        if result.returncode or len(text) > 2 * 1024 * 1024:
            raise ValueError('HandBrake preset discovery failed')
        presets = parse_handbrake_presets(text)
        if not presets:
            raise ValueError('HandBrake returned no recognizable presets')
        warning = ('HandBrake could not load GUI custom presets; the list contains the presets it could read.'
                   if 'Failed to load GUI presets' in text or 'Preset import failed' in text else None)
        return dict(available=True, executable=exe, presets=presets, warning=warning)
    except (OSError, subprocess.SubprocessError):
        raise ValueError('HandBrake preset query failed or timed out') from None


def freeze_handbrake_preset(settings, preset, folder, source=None):
    if not isinstance(preset, str) or not preset.strip() or len(preset) > 500:
        raise ValueError('Choose an installed HandBrake preset on this task')
    available = handbrake_presets(settings)
    if preset not in {p['path'] for p in available['presets']}:
        raise ValueError('The selected HandBrake preset is no longer available; refresh the task preset list')
    name = 'Curator approved preset'
    try:
        result = subprocess.run([available['executable'], *_preset_import_args(settings), '--preset', preset,
                                 '--preset-export', name], capture_output=True, text=True, timeout=15)
        if result.returncode or len(result.stdout) > 2 * 1024 * 1024:
            raise ValueError('Could not capture the selected HandBrake preset')
        payload = json.loads(result.stdout)
        rows = payload.get('PresetList', [])
        if len(rows) != 1 or rows[0].get('PresetName') != name or rows[0].get('Folder'):
            raise ValueError('Unexpected HandBrake preset export')
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        raise ValueError('Could not export the selected HandBrake preset') from None
    adjustment = None
    if source:
        width, height = display_geometry(source)
        row = rows[0]
        limit_width, limit_height = row.get('PictureWidth', 0), row.get('PictureHeight', 0)
        if height > width and limit_width > limit_height > 0:
            row['PictureWidth'], row['PictureHeight'] = limit_height, limit_width
            row.update(PicturePAR='off', PictureKeepRatio=True, PictureAllowUpscaling=False)
            adjustment = dict(orientation='portrait', max_width=limit_height, max_height=limit_width,
                              note='Landscape preset limits swapped for portrait; square pixels, no upscaling')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / (uuid.uuid4().hex + '.json')
    with path.open('x') as stream:
        os.chmod(path, 0o600)
        json.dump(payload, stream)
    return dict(handbrake=available['executable'], handbrake_preset=name,
                handbrake_preset_source=preset, handbrake_preset_file=str(path),
                handbrake_preset_hash=digest(path), handbrake_geometry=adjustment)


def probe(path, config):
    result = subprocess.run([executable(config, 'ffprobe'), '-v', 'error', '-show_format', '-show_streams', '-show_chapters', '-show_data_hash', 'sha256',
                             '-of', 'json', str(path)], capture_output=True, timeout=60)
    if result.returncode or len(result.stdout) > 4 * 1024 * 1024:
        raise ValueError('Video probe failed')
    try:
        info = json.loads(result.stdout)
        video = next(x for x in info['streams'] if x['codec_type'] == 'video'
                     and not x.get('disposition', {}).get('attached_pic'))
        fmt = info.get('format', {})
        return dict(width=int(video['width']), height=int(video['height']), codec=video['codec_name'],
                    duration_seconds=float(fmt.get('duration', video.get('duration', 0))),
                    size_bytes=int(fmt.get('size', Path(path).stat().st_size)),
                    bitrate=int(fmt.get('bit_rate', 0)), chapters=info.get('chapters', []), container=fmt.get('format_name', ''), streams=info['streams'],
                    color_transfer=video.get('color_transfer'), pix_fmt=video.get('pix_fmt'))
    except (KeyError, ValueError, StopIteration):
        raise ValueError('No usable video stream') from None


def validate(source, output):
    issues = []
    duration = source['duration_seconds']
    if not duration or abs(output['duration_seconds'] - duration) > max(1, duration * 0.005):
        issues.append('Duration changed')
    source_width, source_height = display_geometry(source)
    output_width, output_height = display_geometry(output)
    if abs(source_width / source_height - output_width / output_height) > .025:
        issues.append('Aspect ratio changed')
    if max(output_width, output_height) < 1920 or min(output_width, output_height) < 720:
        issues.append('Output is below 1080-class target')
    if max(output_width, output_height) > 4096 or min(output_width, output_height) > 2160:
        issues.append('Output exceeds the 4K target ceiling')
    formats = set(output.get('container', '').split(','))
    if formats & {'mov', 'mp4', 'm4v'}:
        if any(s.get('codec_type') == 'video' and s.get('codec_name') == 'hevc'
               and s.get('codec_tag_string') != 'hvc1' for s in output['streams']):
            issues.append('HEVC output requires hvc1 tagging for QuickTime compatibility')
    for kind in ('audio', 'subtitle'):
        old = sorted(x.get('tags', {}).get('language', 'und') for x in source['streams'] if x['codec_type'] == kind)
        new = sorted(x.get('tags', {}).get('language', 'und') for x in output['streams'] if x['codec_type'] == kind)
        if old != new:
            issues.append(f'{kind.title()} track/language preservation differs')
    if source.get('color_transfer') and source['color_transfer'] != output.get('color_transfer'):
        issues.append('Transfer characteristics changed')
    if '10' in (source.get('pix_fmt') or '') and '10' not in (output.get('pix_fmt') or ''):
        issues.append('10-bit source became lower bit depth')
    return issues


def processing_failure(log):
    try:
        with Path(log).open('rb') as stream:
            stream.seek(max(0, stream.seek(0, 2) - 32768))
            tail = stream.read().decode('utf-8', errors='replace').lower()
        if 'mlmodel error' in tail and 'model is not found' in tail:
            return 'Topaz Core ML model cache is unavailable; preview the same enhancement in Topaz, then retry'
        if 'model not found:' in tail:
            return 'Topaz model was not found; verify installed models and the Topaz app path'
    except OSError:
        pass
    return 'Processing tool failed; inspect the private tool log'


def processing_environment(kind, settings):
    if kind != 'upscale':
        return None
    # Topaz GUI supplies these variables; a standalone local web app does not inherit them.
    env = os.environ.copy()
    bundled = Path(executable(settings, 'topaz')).parent.parent / 'Resources' / 'models'
    models = Path(env.get('TVAI_MODEL_DIR') or bundled)
    if not models.is_dir():
        raise ValueError('Topaz model folder unavailable; verify the Topaz FFmpeg app path and installed models')
    env.setdefault('TVAI_MODEL_DIR', str(models))
    env.setdefault('TVAI_MODEL_DATA_DIR', str(models))
    return env


def command(kind, source, output, settings):
    if kind == 'optimize':
        preset = settings.get('handbrake_preset')
        if not isinstance(preset, str) or not preset.strip():
            raise ValueError('Select a HandBrake preset before processing')
        snapshot = settings.get('handbrake_preset_file')
        if not snapshot or not Path(snapshot).is_file() or digest(snapshot) != settings.get('handbrake_preset_hash'):
            raise ValueError('Approved preset snapshot is missing or changed; select and approve the preset again')
        container = {'.mkv':'av_mkv', '.mov':'av_mov'}.get(Path(output).suffix.lower(), 'av_mp4')
        return [executable(settings, 'handbrake'), '-i', str(source), '-o', str(output),
                '--preset-import-file', snapshot, '--preset', preset, '--format', container,
                '--all-audio', '--all-subtitles', '--crop', '0:0:0:0']
    if kind == 'upscale':
        # Settings contain exported filter/encoder choices, never executable shell commands.
        vf = settings.get('topaz_filter', '')
        if not isinstance(vf, str) or not vf.startswith('tvai_up=') or any(x in vf for x in ';[]\n'):
            raise ValueError('Configure a reviewed tvai_up filter from Topaz Export Command')
        if len(vf) > 2000 or not all(x.replace('.', '').replace('-', '').replace('_', '').isalnum()
                                      for x in vf.replace('=', ':').replace(',', ':').split(':') if x):
            raise ValueError('Invalid Topaz filter')
        apple = ['-tag:v', 'hvc1', '-movflags', '+faststart'] if Path(output).suffix.lower() in {'.mov', '.mp4', '.m4v'} else []
        return [executable(settings, 'topaz'), '-nostdin', '-n', '-i', str(source), '-map', '0:v:0',
                '-map', '0:a?', '-map', '0:s?', '-vf', vf, '-c:v', 'hevc_videotoolbox',
                '-allow_sw', '1', '-q:v', '65', '-c:a', 'copy', '-c:s', 'copy', *apple, str(output)]
    raise ValueError('This task does not use a video processing tool')


def quicktime_remux(source, output, settings):
    if Path(output).suffix.lower() not in {'.mov', '.mp4', '.m4v'}:
        raise ValueError('QuickTime repair requires a MOV or MP4 container')
    return [executable(settings, 'ffmpeg'), '-nostdin', '-n', '-i', str(source), '-map', '0',
            '-c', 'copy', '-tag:v', 'hvc1', '-movflags', '+faststart', str(output)]


def frames(path, folder, media, settings):
    folder.mkdir(parents=True, exist_ok=True)
    result = []
    for index, fraction in enumerate((.15, .4, .65, .85)):
        target = folder / f'{index}.jpg'
        if not target.exists():
            cmd = [executable(settings, 'ffmpeg'), '-nostdin', '-n', '-ss', str(media['duration_seconds'] * fraction),
                   '-i', str(path), '-frames:v', '1', '-vf', 'scale=640:-2', str(target)]
            run = subprocess.run(cmd, capture_output=True, timeout=60)
            if run.returncode or not target.is_file() or not target.stat().st_size:
                continue
        result.append(dict(file=target.name, seconds=round(media['duration_seconds'] * fraction, 1)))
    if not result:
        raise ValueError('Could not extract candidate frames')
    return result


def image_bytes(path):
    data = Path(path).read_bytes()
    if len(data) > 10 * 1024 * 1024 or not (data.startswith(b'\xff\xd8\xff') or data.startswith(b'\x89PNG\r\n\x1a\n')):
        raise ValueError('Select a JPEG or PNG image under 10 MiB')
    return data


def encoded_image(path):
    return base64.b64encode(image_bytes(path)).decode()
