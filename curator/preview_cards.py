"""Private, immutable trailer cards and explicitly saved preview defaults."""

import base64
import copy
import hashlib
import os
import re
import uuid
from .errors import UserError
from .image_contract import editor_png
from .store import now

DEFAULTS = dict(
    intro=None,
    outro=None,
    intro_duration_ms=3000,
    outro_duration_ms=3000,
    crossfade_ms=500,
    black_fade_ms=350,
    audio_fade_ms=500,
    requested_duration_ms=30000,
    output_profile='preview-h264-720',
)


def milliseconds(value, minimum=0, maximum=2000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise UserError(f'Choose an integer duration between {minimum} and {maximum} milliseconds')
    return value


class PreviewCards:
    def preview_card_record(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{32}', identity):
            raise UserError('Trailer card not found')
        row = self.store.get('settings', 'preview-card:' + identity)
        if not row or row.get('record_type') != 'preview_card':
            raise UserError('Trailer card not found')
        return row

    def preview_card_path(self, identity, version):
        if not re.fullmatch(r'[a-f0-9]{32}', str(identity)) or type(version) is not int or version < 1:
            raise UserError('Invalid trailer card version')
        root = self.store.root / 'preview-cards'
        folder = root / identity
        path = folder / f'{version}.png'
        if any(p.is_symlink() for p in (root, folder, path)):
            raise UserError('Trailer card storage is unavailable')
        return path

    @staticmethod
    def preview_card_public(row):
        version = row['revision']
        return dict(
            id=row['id'],
            revision=version,
            role=row['role'],
            name=row['name'],
            hidden=row['hidden'],
            image=row['versions'][str(version)],
            thumbnail_url=f'/api/preview/cards/image?id={row["id"]}&version={version}',
        )

    def preview_cards(self):
        return dict(
            cards=[
                self.preview_card_public(row)
                for row in self.store.where('settings', record_type='preview_card')
                if not row['hidden']
            ],
            limits=dict(format='PNG', max_bytes=10 * 1024 * 1024, max_dimension=4096, max_pixels=8000000),
        )

    def preview_card_image(self, identity, version):
        row = self.preview_card_record(identity)
        info = row['versions'].get(str(version))
        if not info:
            raise UserError('Trailer card version is unavailable')
        path = self.preview_card_path(identity, version)
        if not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
            raise UserError('Trailer card image is unavailable; choose another card')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != info['sha256']:
            raise UserError('Trailer card bytes changed; import a new version')
        return data

    def import_preview_card(self, data):
        if not isinstance(data, dict) or set(data) - {'id', 'revision', 'name', 'role', 'image'}:
            raise UserError('Invalid trailer card import')
        name, role = data.get('name'), data.get('role')
        if not isinstance(name, str) or not name.strip() or len(name) > 100 or any(ord(c) < 32 for c in name):
            raise UserError('Name the trailer card using up to 100 characters')
        if role not in {'intro', 'outro'}:
            raise UserError('Choose intro or outro')
        image = data.get('image')
        if not isinstance(image, str) or len(image) > 14 * 1024 * 1024:
            raise UserError('Choose a normalized PNG under 10 MiB')
        dimensions = editor_png(image)
        raw = base64.b64decode(image, validate=True)
        with self.store.transaction():
            if data.get('id'):
                row = self.preview_card_record(data['id'])
                if type(data.get('revision')) is not int or data['revision'] != row['revision'] or row['hidden']:
                    raise UserError('Trailer card changed; reload before replacing it')
                if role != row['role']:
                    raise UserError('A replacement must keep the card role')
            else:
                if data.get('revision') is not None:
                    raise UserError('A new card has no previous revision')
                row = dict(
                    id=uuid.uuid4().hex,
                    revision=0,
                    name=name.strip(),
                    role=role,
                    hidden=False,
                    record_type='preview_card',
                    versions={},
                    created=now(),
                )
            version = row['revision'] + 1
            path = self.preview_card_path(row['id'], version)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(path.parent.parent, 0o700)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            info = dict(version=version, sha256=hashlib.sha256(raw).hexdigest(), format='png', **dimensions)
            row['versions'][str(version)] = info
            row.update(revision=version, name=name.strip(), updated=now())
            self.store.put('settings', 'preview-card:' + row['id'], row)
            self.store.record(
                'trailer card', 'Imported a new trailer card version', details=dict(card=row['id'], version=version)
            )
        return self.preview_card_public(row)

    def hide_preview_card(self, identity, revision):
        with self.store.transaction():
            row = self.preview_card_record(identity)
            if type(revision) is not int or row['revision'] != revision:
                raise UserError('Trailer card changed; reload first')
            if not row['hidden']:
                row.update(hidden=True, updated=now())
                self.store.put('settings', 'preview-card:' + identity, row)
                self.store.record(
                    'trailer card', 'Hid a trailer card; retained image versions', details=dict(card=identity)
                )
        return dict(hidden=True)

    def preview_defaults(self):
        return self.store.get('settings', 'preview-defaults', dict(revision=1, values=copy.deepcopy(DEFAULTS)))

    def validate_preview_values(self, values):
        if not isinstance(values, dict) or set(values) != set(DEFAULTS):
            raise UserError('Invalid trailer settings')
        for key in ('intro_duration_ms', 'outro_duration_ms'):
            milliseconds(values[key], 1, 10000)
        for key in ('crossfade_ms', 'black_fade_ms', 'audio_fade_ms'):
            milliseconds(values[key])
        milliseconds(values['requested_duration_ms'], 1, 120000)
        if values['output_profile'] != 'preview-h264-720':
            raise UserError('Unsupported trailer output profile')
        for role in ('intro', 'outro'):
            ref = values[role]
            if ref is None:
                continue
            if not isinstance(ref, dict) or set(ref) != {'card', 'version'} or type(ref['version']) is not int:
                raise UserError('Choose a saved trailer card version')
            row = self.preview_card_record(ref['card'])
            if row['role'] != role or row['hidden']:
                raise UserError('Selected trailer card is hidden or has a different role')
            self.preview_card_image(ref['card'], ref['version'])
            if values['black_fade_ms'] + values['crossfade_ms'] > values[role + '_duration_ms']:
                raise UserError('Card duration must fit the black fade and crossfade')
        return copy.deepcopy(values)

    def save_preview_defaults(self, revision, changes):
        if not isinstance(changes, dict) or set(changes) - set(DEFAULTS):
            raise UserError('Invalid trailer defaults')
        with self.store.transaction():
            row = self.preview_defaults()
            if type(revision) is not int or revision != row['revision']:
                raise UserError('Trailer defaults changed; keep your edits and reload')
            values = self.validate_preview_values({**row['values'], **changes})
            if values != row['values']:
                row = dict(revision=revision + 1, values=values, updated=now())
                self.store.put('settings', 'preview-defaults', row)
                self.store.record(
                    'trailer defaults', 'Updated preview defaults', details=dict(revision=row['revision'])
                )
        return row
