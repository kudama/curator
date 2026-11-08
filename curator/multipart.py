"""Multipart planning and FFmpeg argv construction; no shell execution."""
import math
import re
import subprocess
from pathlib import Path
from .quality import display_geometry
from . import tools

PART = re.compile(r'(?i)^(.*?)[\s._-]+(?:part|pt|disc|cd)[\s._-]*(\d+)(?:\b|_)(.*)$')


def basename(value, suffix=None):
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value.encode()) > 240 or value in {'.', '..'} or value.startswith('.')
            or any(ord(c) < 32 or c in '/\\:' for c in value)):
        raise ValueError('Enter a filename only, without folders or control characters')
    if suffix and Path(value).suffix != suffix:
        raise ValueError('Keep the original file extension, including its case')
    return value


def part_info(asset):
    path = Path(asset.get('plex_path', ''))
    match = PART.match(path.stem)
    if not match:
        return None
    return dict(group=str(path.parent).casefold() + '/' + match[1].strip(' ._-').casefold(),
                title=match[1].strip(' ._-'), number=int(match[2]))


def suggestions(assets, anchor):
    info = part_info(anchor)
    matches = [a for a in assets if a['library'] == anchor['library'] and a.get('present', True)
               and (part_info(a) or {}).get('group') == (info or {}).get('group')] if info else [anchor]
    matches.sort(key=lambda a: ((part_info(a) or {}).get('number', 0), a['id']))
    numbers = [(part_info(a) or {}).get('number') for a in matches]
    warnings = []
    if info:
        if len(numbers) != len(set(numbers)):
            warnings.append('Duplicate part numbers; confirm which files belong in this set.')
        if sorted(set(numbers)) != list(range(1, max(numbers) + 1)):
            warnings.append('Missing part numbers; confirm the set is complete.')
    else:
        warnings.append('No part number found; add files and confirm their order manually.')
    return dict(title=(info or {}).get('title', anchor['title']), assets=[a['id'] for a in matches], warnings=warnings)


def playback_streams(media):
    """Timecode is editing metadata, not a playable track. Unknown data needs review."""
    streams=[]
    for stream in media['streams']:
        if stream.get('codec_type')=='data' and stream.get('codec_tag_string')=='tmcd':
            continue
        if stream.get('codec_type') not in {'video','audio','subtitle','attachment'}:
            raise ValueError('Unsupported ancillary/data track; inspect it before joining')
        streams.append(stream)
    return streams


def stream_maps(media=None):
    if media is None:
        return ['-map','0:v?','-map','0:a?','-map','0:s?','-map','0:t?']
    return [arg for index,stream in enumerate(media['streams']) if stream in playback_streams(media)
            for arg in ('-map','0:'+str(stream.get('index',index)))]


def stream_signature(media):
    # Concat copy needs identical codec setup and track ordering, not just extensions.
    fields = ('codec_type', 'codec_name', 'profile', 'level', 'width', 'height', 'pix_fmt',
              'sample_aspect_ratio', 'r_frame_rate', 'time_base', 'sample_rate', 'channels',
              'channel_layout', 'sample_fmt', 'extradata_hash', 'color_transfer', 'color_primaries', 'color_space')
    return [{**{k: s.get(k) for k in fields}, 'language':s.get('tags', {}).get('language', 'und'),
             'rotation':s.get('side_data_list', []), 'disposition':s.get('disposition', {})}
            for s in playback_streams(media)]


def compatibility(media):
    first = stream_signature(media[0])
    return all(stream_signature(m) == first for m in media[1:])


def normalization(media):
    first = media[0]
    w, h = display_geometry(first)
    # Keep the first part's display orientation/canvas. Letterbox other proportions.
    scale = min(1, 3840 / max(w, h), 2160 / min(w, h))
    width, height = max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2)
    tracks = lambda m: [(s['codec_type'], s.get('tags', {}).get('language', 'und')) for s in playback_streams(m)]
    for m in media:
        if tracks(m) != tracks(first) or any(s['codec_type'] not in {'video', 'audio', 'subtitle'} or s.get('disposition',{}).get('attached_pic') for s in playback_streams(m)):
            raise ValueError('Normalization needs the same track types, order and languages in every part')
        if sum(s['codec_type'] == 'video' for s in m['streams']) != 1:
            raise ValueError('Each part needs exactly one video stream')
        if m.get('color_transfer') in {'smpte2084', 'arib-std-b67'} or '10' in (m.get('pix_fmt') or ''):
            raise ValueError('HDR/10-bit normalization needs a dedicated reviewed preset; use compatible parts')
        old_subs = [s.get('codec_name') for s in first['streams'] if s['codec_type']=='subtitle']
        if [s.get('codec_name') for s in m['streams'] if s['codec_type']=='subtitle'] != old_subs:
            raise ValueError('Subtitle formats differ; normalize the subtitles before joining')
    return dict(width=width, height=height, description=f'{width} × {height}, H.264 8-bit SDR, 30 fps; AAC stereo 48 kHz; preserve subtitle tracks; letterbox without stretching')


def chapters(media, titles):
    rows, offset = [], 0
    for m, title in zip(media, titles):
        duration = m['duration_seconds']
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('Every part needs a valid positive duration')
        rows.append(dict(start=offset, end=offset+duration, title=title))
        for chapter in m.get('chapters', []):
            start, end = float(chapter['start_time']), float(chapter['end_time'])
            if 0 < start < end <= duration:
                rows.append(dict(start=offset+start, end=offset+end, title=chapter.get('tags',{}).get('title','Chapter')))
        offset += duration
    rows.sort(key=lambda c:c['start'])
    # Part markers and retained internal chapters form one nonoverlapping timeline.
    for i, row in enumerate(rows[:-1]):
        row['end'] = rows[i+1]['start']
    return rows


def metadata_file(path, rows):
    def escape(value):
        return ''.join('\\'+c if c in '\\=;#\n\r' else c for c in value)
    text = ';FFMETADATA1\n'
    for row in rows:
        text += f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={round(row['start']*1000)}\nEND={round(row['end']*1000)}\ntitle={escape(row['title'])}\n"
    Path(path).write_text(text)


def concat_command(inputs, manifest, metadata, output, settings, media=None):
    def quote(path):
        value = str(path)
        if '\n' in value or '\r' in value:
            raise ValueError('Source paths with newlines cannot be joined')
        return "'" + value.replace("'", "'\\''") + "'"
    Path(manifest).write_text('ffconcat version 1.0\n'+''.join('file '+quote(p)+'\n' for p in inputs))
    # hvc1 only applies to HEVC, added by the caller after probing the first video.
    return [tools.executable(settings,'ffmpeg'),'-nostdin','-n','-f','concat','-safe','0',
            '-protocol_whitelist','file,pipe','-i',str(manifest),'-i',str(metadata),*stream_maps(media),
            '-map_metadata','0','-map_chapters','1','-c','copy',*(['-write_tmcd','0'] if Path(output).suffix.lower() in {'.mov','.mp4','.m4v'} else []),str(output)]


def normalization_encoder(settings):
    result=subprocess.run([tools.executable(settings,'ffmpeg'),'-hide_banner','-encoders'],capture_output=True,text=True,timeout=15)
    if result.returncode or len(result.stdout)>4*1024*1024:
        raise ValueError('Could not query FFmpeg encoders')
    names={line.split()[1] for line in result.stdout.splitlines() if len(line.split())>1}
    if 'libx264' in names:return 'libx264'
    if 'h264_videotoolbox' in names:return 'h264_videotoolbox'
    raise ValueError('The selected FFmpeg needs libx264 or macOS h264_videotoolbox for normalization')


def normalize_command(source, output, canvas, settings, media=None):
    w,h=canvas['width'],canvas['height']
    vf=f'scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p'
    return [tools.executable(settings,'ffmpeg'),'-nostdin','-n','-i',str(source),*stream_maps(media),
            '-c:v',canvas['encoder'],*(['-crf','18','-preset','medium'] if canvas['encoder']=='libx264' else ['-b:v','12M','-allow_sw','1','-profile:v','high','-level:v','5.1','-bf','0']),'-vf',vf,'-c:a','aac','-b:a','192k',
            '-ar','48000','-ac','2','-c:s','copy',str(output)]
