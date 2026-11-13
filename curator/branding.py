"""Versioned folder artwork preferences, bounded by mapped storage roots."""
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

NAME = '.curator-artwork.json'
STYLES = {'gritty', 'sunlit', 'editorial', 'vintage', 'monochrome', 'minimal'}


DEFAULT_PRESETS = [
    dict(id='gritty', name='Dark & gritty', details='Deep shadows, muted colors, strong contrast and subtle film grain.', background='solid black', typography='Heavy condensed off-white lettering with a subtly distressed texture.'),
    dict(id='sunlit', name='Warm & sunlit', details='Golden light, warm natural colors and soft contrast.', background='soft warm ivory', typography='Clean bold lettering with a warm editorial feel.'),
    dict(id='editorial', name='Cool editorial', details='Blue-gray tones, crisp contrast and a restrained editorial finish.', background='muted blue-gray', typography='Refined magazine-style typography.'),
    dict(id='vintage', name='Vintage film', details='Faded colors, warm highlights and analog film grain.', background='warm charcoal', typography='Bold retro title lettering.'),
    dict(id='minimal', name='Minimal & clean', details='Natural colors, a simple composition and generous negative space.', background='a complementary neutral tone', typography='Understated clean typography.')
]


def validate_presets(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
        raise ValueError('Define between one and fifty branding presets')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not {'id', 'name', 'details', 'background', 'typography'} <= set(row) or set(row) - {'id', 'name', 'details', 'background', 'typography', 'negative_prompt', 'model', 'ratio', 'resolution'}:
            raise ValueError('Invalid branding preset fields')
        if not isinstance(row['id'], str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', row['id']) or row['id'] in seen:
            raise ValueError('Branding preset IDs must be unique and stable')
        seen.add(row['id'])
        if any(not isinstance(row[k], str) or not row[k].strip() or len(row[k]) > 3000 for k in ('name', 'details', 'background', 'typography')):
            raise ValueError('Complete each branding preset name and prompt details')
        for field in ('negative_prompt', 'model', 'ratio', 'resolution'):
            if field in row and (not isinstance(row[field], str) or len(row[field]) > 3000):
                raise ValueError('Invalid optional preset field: ' + field)
        if row.get('ratio') and row['ratio'] not in {'21:9','16:9','3:2','5:4','1:1','4:5','2:3','9:16','9:21'}:
            raise ValueError('Unsupported preset ratio')
        if row.get('resolution') and row['resolution'] not in {'1K','2K','3K','4K'}:
            raise ValueError('Unsupported preset resolution')
    return rows


def validate(value):
    if not isinstance(value, dict) or set(value) - {'version', 'creator', 'colors', 'backdrop', 'style', 'logo', 'preset_id'} or value.get('version') not in {1, 2}:
        raise ValueError('Unsupported folder artwork settings')
    for field in ('creator', 'colors', 'backdrop', 'style', 'logo'):
        if not isinstance(value.get(field, ''), str) or len(value.get(field, '')) > 2000:
            raise ValueError('Invalid folder artwork field: ' + field)
    if value['version'] == 1 and value.get('style') not in STYLES:
        raise ValueError('Choose a supported artwork style')
    if value['version'] == 2 and (not isinstance(value.get('preset_id'), str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', value['preset_id'])):
        raise ValueError('Invalid branding preset reference')
    logo = value.get('logo', '')
    if logo and (Path(logo).name != logo or not logo.startswith('.curator-logo-') or Path(logo).suffix not in {'.png', '.jpg'}):
        raise ValueError('Invalid folder logo reference')
    return value


def read(folder):
    path = folder / NAME
    if path.is_symlink():
        raise ValueError('Folder artwork settings cannot be a symlink')
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError('Folder artwork settings must be a regular file')
    if path.stat().st_size > 16384:
        raise ValueError('Folder artwork settings are too large')
    try:
        return validate(json.loads(path.read_text()))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError('Cannot read folder artwork settings') from e


def revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def write(folder, value, expected):
    previous = read(folder)
    if (revision(previous) if previous else None) != expected:
        raise ValueError('Folder branding changed; reload before saving')
    value = validate(value)
    fd, temporary = tempfile.mkstemp(prefix='.curator-settings-', dir=folder)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, folder / NAME)
    finally:
        Path(temporary).unlink(missing_ok=True)
