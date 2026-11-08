"""Private reusable cast profiles; pictures never require a public web host."""
import base64
import hashlib
import re


def validate_rows(rows):
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError('Cast must be a list of at most 100 people')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) - {'name', 'role', 'thumb', 'image', 'profile_id', 'revision', 'remember', 'clear_photo'}:
            raise ValueError('Invalid cast fields')
        name = row.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 500:
            raise ValueError('Each cast member needs a name (up to 500 characters)')
        if name.strip().casefold() in seen:
            raise ValueError('Each cast member can appear only once')
        seen.add(name.strip().casefold())
        for field in ('role', 'thumb'):
            if not isinstance(row.get(field, ''), str) or len(row.get(field, '')) > 4000:
                raise ValueError('Invalid cast ' + field)
        for field in ('remember', 'clear_photo'):
            if field in row and not isinstance(row[field], bool):
                raise ValueError('Invalid cast choice')
        if row.get('profile_id') and not re.fullmatch(r'[a-f0-9]{32}', str(row['profile_id'])):
            raise ValueError('Invalid saved cast profile')
        if row.get('revision') is not None and (type(row['revision']) is not int or row['revision'] < 1):
            raise ValueError('Invalid cast profile revision')
        if row.get('image'):
            photo_bytes(row['image'])


def photo_bytes(encoded):
    if not isinstance(encoded, str) or len(encoded) > 14 * 1024 * 1024:
        raise ValueError('Cast pictures must be JPEG/PNG under 10 MiB')
    try:
        data = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise ValueError('Invalid cast picture') from None
    if not data or len(data) > 10 * 1024 * 1024 or not (data.startswith(b'\xff\xd8\xff') or data.startswith(b'\x89PNG\r\n\x1a\n')):
        raise ValueError('Cast pictures must be JPEG/PNG under 10 MiB')
    return data


def photo_id(data):
    return hashlib.sha256(data).hexdigest()


def fields(item):
    return [dict(name=row.get('tag', ''), role=row.get('role') or '', thumb=row.get('thumb') or '')
            for row in item.get('Role', [])]
