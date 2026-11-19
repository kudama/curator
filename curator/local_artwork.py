"""Bounded local image derivatives. No shell, network inputs, or Plex publication."""

import base64
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from .image_contract import editor_png
from .store import now
from .errors import UserError


def magick(config):
    configured = config.get('magick')
    candidates = (
        [configured] if configured else [shutil.which('magick'), '/opt/homebrew/bin/magick', '/usr/local/bin/magick']
    )
    path = next((str(Path(p).expanduser()) for p in candidates if p and Path(p).expanduser().is_file()), None)
    if not path:
        raise UserError('ImageMagick is unavailable. Set its executable in Settings → Processing tools.')
    return path


def execute(command):
    try:
        result = subprocess.run(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        raise UserError('Local artwork processing did not finish; original image is retained') from None
    if result.returncode:
        raise UserError('ImageMagick could not render this artwork; inspect the font, image and text')
    return result.stdout


class LocalArtwork:
    def local_font_paths(self):
        import hashlib

        fonts = {}
        for folder in (
            Path('/System/Library/Fonts'),
            Path('/Library/Fonts'),
            Path.home() / 'Library/Fonts',
            Path('/usr/share/fonts'),
            Path('/usr/local/share/fonts'),
        ):
            if not folder.is_dir():
                continue
            for path in sorted(folder.rglob('*')):
                if path.suffix.lower() not in {'.ttf', '.otf', '.ttc'} or not path.is_file() or path.is_symlink():
                    continue
                label = path.stem
                if label in fonts:
                    label += ' · ' + hashlib.sha256(str(path).encode()).hexdigest()[:6]
                fonts[label] = str(path)
        return fonts

    def artwork_fonts(self):
        try:
            magick(self.config())
            fonts = sorted(self.local_font_paths(), key=str.casefold)
            return dict(
                available=bool(fonts),
                fonts=fonts,
                reason='' if fonts else 'No usable installed fonts were found on this host',
            )
        except ValueError as error:
            return dict(available=False, fonts=[], reason=str(error))

    def local_artwork(self, data):
        if not isinstance(data, dict) or data.get('mode') not in {'logo_text', 'logo_cleanup', 'portrait'}:
            raise UserError('Choose a local artwork operation')
        if set(data) - {'mode', 'asset', 'profile', 'text', 'font', 'color', 'fuzz', 'image'}:
            raise UserError('Invalid local artwork fields')
        mode = data['mode']
        payload = {'mode': mode}
        if data.get('asset'):
            asset = self.asset({'asset': data['asset']}, check=False)
            payload.update(asset=asset['id'], library=asset['library'], title=asset['title'])
        elif data.get('profile'):
            profile = self.store.get('settings', 'cast_profiles', {}).get(data['profile'])
            if not profile:
                raise UserError('Person not found')
            payload.update(profile=data['profile'], title=profile['name'])
        else:
            raise UserError('Choose the exact artwork owner')
        magick(self.config())
        if mode == 'logo_text':
            text = data.get('text')
            font = data.get('font')
            if not isinstance(text, str) or not text.strip() or len(text) > 200 or any(ord(c) < 32 for c in text):
                raise UserError('Enter title text up to 200 characters on one line')
            if font not in self.artwork_fonts()['fonts']:
                raise UserError('Selected font is not available on this host')
            payload.update(text=text, font=font)
        else:
            payload['source'] = self._folder_photo(encoded=data.get('image'))
            if not payload['source']:
                raise UserError('Choose an image')
        if mode in {'logo_text', 'logo_cleanup'}:
            if not isinstance(data.get('color'), str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', data['color']):
                raise UserError('Choose a six-digit color')
            payload['color'] = data['color']
        if mode == 'logo_cleanup':
            fuzz = data.get('fuzz', 0)
            if type(fuzz) not in (int, float) or not 0 <= fuzz <= 20:
                raise UserError('Choose background tolerance from 0 to 20 percent')
            payload['fuzz'] = fuzz
        return self.queue_file_operation('local_artwork', payload, background=True)

    def render_local_artwork(self, payload):
        executable = magick(self.config())
        mode = payload['mode']
        with tempfile.TemporaryDirectory(prefix='local-artwork-', dir=self.store.root) as folder:
            folder = Path(folder)
            output = folder / 'candidate.png'
            command = [
                executable,
                '-limit',
                'thread',
                '1',
                '-limit',
                'memory',
                '128MiB',
                '-limit',
                'disk',
                '256MiB',
                '-limit',
                'time',
                '20',
            ]
            if mode == 'logo_text':
                if payload['font'] not in self.artwork_fonts()['fonts']:
                    raise UserError('Font changed before local rendering')
                text = folder / 'title.txt'
                text.write_text(payload['text'], encoding='utf-8')
                command += [
                    '-background',
                    'none',
                    '-fill',
                    payload['color'],
                    '-font',
                    self.local_font_paths()[payload['font']],
                    '-pointsize',
                    '96',
                    'label:@' + str(text),
                    '-resize',
                    '2304x672>',
                    '-trim',
                    '+repage',
                    '-bordercolor',
                    'none',
                    '-border',
                    '48',
                ]
            else:
                data = self.folder_image(payload['source'])
                source = folder / ('source.png' if data.startswith(b'\x89PNG') else 'source.jpg')
                source.write_bytes(data)
                command += [str(source) + '[0]', '-auto-orient']
                if mode == 'portrait':
                    command += [
                        '-resize',
                        '1024x1024',
                        '-background',
                        'none',
                        '-gravity',
                        'center',
                        '-extent',
                        '1024x1024',
                    ]
                elif mode == 'logo_cleanup':
                    command += [
                        '-alpha',
                        'set',
                        '-fuzz',
                        str(payload['fuzz']) + '%',
                        '-transparent',
                        payload['color'],
                        '-trim',
                        '+repage',
                        '-resize',
                        '2304x2304>',
                    ]
            command += ['-strip', 'PNG32:' + str(output)]
            execute(command)
            if output.stat().st_size > 10 * 1024 * 1024:
                raise UserError('Rendered artwork exceeds the supported size')
            encoded = base64.b64encode(output.read_bytes()).decode()
            dimensions = editor_png(encoded, '1:1' if mode == 'portrait' else None, logo=mode != 'portrait')
            photo = self._folder_photo(encoded=encoded)
        record = dict(
            record_type='local_artifact',
            photo=photo,
            original=payload.get('source'),
            mode=mode,
            font=payload.get('font'),
            text=payload.get('text'),
            color=payload.get('color'),
            fuzz=payload.get('fuzz'),
            created=now(),
            **dimensions,
        )
        with self.store.transaction():
            self.store.put('settings', 'local-artifact:' + photo, record)
        return record

    def file_operation(self, identity):
        row = self.store.get('settings', identity)
        if not row or row.get('record_type') != 'file_operation':
            raise UserError('File operation not found')
        return row
