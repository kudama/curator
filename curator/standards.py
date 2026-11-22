"""Library standards: what "done" means for each Plex library type.

A standard belongs to a Plex library type (Movies, TV Shows, Other Videos), not to an
individual library. A library may override parts of its type's standard where it needs
to differ. Standards describe the desired result; they never authorize Curator to change
media on their own.
"""

import copy
import hashlib
import json

from .errors import UserError
from .rules import LIBRARY_KINDS, library_kind
from .store import now

DIMENSIONS = ('metadata', 'cast', 'artwork', 'upscaling', 'encoding')
METADATA_FIELDS = ('summary', 'year', 'originally_available_at', 'genres', 'studio', 'content_rating', 'collections')
ARTWORK_KINDS = ('poster', 'background', 'logo')
CAST_MODES = ('credits', 'known_people')
POSTER_RATIOS = ('2:3',)
UPSCALE_TARGETS = ('1080', '2160')

_CATALOG = {
    'metadata': dict(enabled=True, required=['summary', 'year', 'genres'], local_ai_suggestions=False),
    # Plex's online agents supply cast photos and artwork, and Plex shows dynamic
    # backgrounds, so neither is part of done unless a library opts in.
    'cast': dict(enabled=False, mode='credits'),
    'artwork': dict(enabled=False, required=['poster'], poster_ratio='2:3'),
    'upscaling': dict(enabled=True, target='1080', suggest_when_met=True),
    # None thresholds follow the global encoding thresholds in Configuration.
    'encoding': dict(enabled=True, max_mbps_1080=None, max_mbps_4k=None, preserve_originals=False),
}
DEFAULTS = {
    'movie': _CATALOG,
    'show': _CATALOG,
    'other_videos': {
        'metadata': dict(enabled=True, required=['summary', 'originally_available_at'], local_ai_suggestions=True),
        'cast': dict(enabled=True, mode='known_people'),
        'artwork': dict(enabled=True, required=['poster'], poster_ratio='2:3'),
        'upscaling': dict(enabled=True, target='1080', suggest_when_met=True),
        'encoding': dict(enabled=True, max_mbps_1080=None, max_mbps_4k=None, preserve_originals=True),
    },
}


def _choice(value, allowed, label):
    if value not in allowed:
        raise UserError(f'Choose a valid {label}')
    return value


def _flag(value, label):
    if not isinstance(value, bool):
        raise UserError(f'{label} must be on or off')
    return value


def _subset(value, allowed, label):
    if not isinstance(value, list) or any(item not in allowed for item in value):
        raise UserError(f'Choose valid {label}')
    return [item for item in allowed if item in value]


def _mbps(value, label):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= value <= 400:
        raise UserError(f'{label} must be between 1 and 400 Mbps, or empty to use the global threshold')
    return value


_FIELDS = {
    'metadata': {
        'enabled': lambda v: _flag(v, 'Metadata'),
        'required': lambda v: _subset(v, METADATA_FIELDS, 'required metadata fields'),
        'local_ai_suggestions': lambda v: _flag(v, 'Local AI suggestions'),
    },
    'cast': {
        'enabled': lambda v: _flag(v, 'Cast'),
        'mode': lambda v: _choice(v, CAST_MODES, 'cast standard'),
    },
    'artwork': {
        'enabled': lambda v: _flag(v, 'Artwork'),
        'required': lambda v: _subset(v, ARTWORK_KINDS, 'required artwork'),
        'poster_ratio': lambda v: _choice(v, POSTER_RATIOS, 'poster shape'),
    },
    'upscaling': {
        'enabled': lambda v: _flag(v, 'Upscaling'),
        'target': lambda v: _choice(v, UPSCALE_TARGETS, 'upscaling target'),
        'suggest_when_met': lambda v: _flag(v, 'Optional upscale suggestions'),
    },
    'encoding': {
        'enabled': lambda v: _flag(v, 'Re-encoding'),
        'max_mbps_1080': lambda v: _mbps(v, 'The 1080p bitrate threshold'),
        'max_mbps_4k': lambda v: _mbps(v, 'The 4K bitrate threshold'),
        'preserve_originals': lambda v: _flag(v, 'Preserve originals'),
    },
}


def validate(values, partial=False):
    """A cleaned copy of a standard; with partial=True, any subset of dimensions and fields."""
    if not isinstance(values, dict) or set(values) - set(DIMENSIONS):
        raise UserError('Invalid library standard')
    if not partial and set(values) != set(DIMENSIONS):
        raise UserError('A library standard must cover every dimension')
    cleaned = {}
    for dimension, fields in values.items():
        rules = _FIELDS[dimension]
        if not isinstance(fields, dict) or set(fields) - set(rules) or (not partial and set(fields) != set(rules)):
            raise UserError(f'Invalid {dimension} standard')
        cleaned[dimension] = {field: rules[field](value) for field, value in fields.items()}
    return {dimension: cleaned[dimension] for dimension in DIMENSIONS if dimension in cleaned}


def _revision(value):
    if type(value) is not int:
        raise UserError('Reload before saving this standard')


def merged(base, overrides):
    result = copy.deepcopy(base)
    for dimension, fields in (overrides or {}).items():
        result[dimension].update(copy.deepcopy(fields))
    return result


def type_digest(values):
    """Identity of the reviewed parent, including unsaved built-in defaults."""
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


class LibraryStandards:
    def type_standard(self, kind):
        _choice(kind, LIBRARY_KINDS, 'library type')
        record = self.store.get('settings', 'standard:' + kind)
        if record:
            return record
        return dict(
            id='standard:' + kind,
            record_type='library_standard',
            kind=kind,
            revision=0,
            values=copy.deepcopy(DEFAULTS[kind]),
            customized=False,
        )

    def library_standard(self, library):
        """The standard a library is held to: its type's standard plus its own overrides."""
        if isinstance(library, str):
            library = self.library(library)
        kind = library.get('standard_kind') or library.get('kind') or library_kind(library)
        overrides = library.get('standard_overrides') or {}
        parent = self.type_standard(kind)
        return dict(
            kind=kind,
            type_revision=parent['revision'],
            type_digest=type_digest(parent['values']),
            overrides=overrides,
            revision=library.get('standard_revision', 0),
            values=merged(parent['values'], overrides),
            observed_kind=library.get('observed_kind') or library_kind(library),
        )

    def standards(self):
        # Return parent values and every effective library from one coherent
        # application snapshot, not individually locked reads that can interleave.
        with self.store.transaction():
            return self._standards_snapshot()

    def save_library_standard_kind(self, data):
        required = {
            'library',
            'revision',
            'before_kind',
            'before_type_revision',
            'before_type_digest',
            'kind',
            'type_revision',
            'type_digest',
        }
        if not isinstance(data, dict) or set(data) != required:
            raise UserError('Reload both standard types before changing this library')
        for field in ('revision', 'before_type_revision', 'type_revision'):
            _revision(data[field])
        _choice(data['kind'], LIBRARY_KINDS, 'library type')
        _choice(data['before_kind'], LIBRARY_KINDS, 'library type')
        with self.store.transaction():
            library = self.library(data['library'])
            before = self.library_standard(library)
            parent = self.type_standard(data['kind'])
            if (before['revision'], before['kind'], before['type_revision'], before['type_digest']) != (
                data['revision'],
                data['before_kind'],
                data['before_type_revision'],
                data['before_type_digest'],
            ) or (parent['revision'], type_digest(parent['values'])) != (data['type_revision'], data['type_digest']):
                raise UserError('A reviewed standard changed; reload and review both types again')
            if before['kind'] == data['kind']:
                return before
            library.update(standard_kind=data['kind'], standard_revision=before['revision'] + 1)
            self.store.put('libraries', library['id'], library)
            self.store.record(
                'standard',
                'Library standard type changed',
                library=library['id'],
                details={'before': before['kind'], 'after': data['kind'], 'revision': library['standard_revision']},
            )
            return self.library_standard(library)

    def _standards_snapshot(self):
        types = {}
        for kind, label in LIBRARY_KINDS.items():
            record = self.type_standard(kind)
            types[kind] = dict(
                label=label,
                revision=record['revision'],
                type_digest=type_digest(record['values']),
                customized=record.get('customized', True),
                values=record['values'],
                defaults=copy.deepcopy(DEFAULTS[kind]),
            )
        return dict(
            types=types, libraries={row['id']: self.library_standard(row) for row in self.store.all('libraries')}
        )

    def save_type_standard(self, kind, revision, values):
        _revision(revision)
        values = validate(values)
        with self.store.transaction():
            current = self.type_standard(kind)
            if revision != current['revision']:
                raise UserError('This standard changed in another window; reload before saving')
            if current['values'] == values:
                return self._standards_snapshot()['types'][kind]
            record = dict(
                id=current['id'],
                record_type='library_standard',
                kind=kind,
                revision=current['revision'] + 1,
                values=values,
                customized=values != DEFAULTS[kind],
                updated=now(),
            )
            self.store.put('settings', record['id'], record)
            self.store.record(
                'standard', f'{LIBRARY_KINDS[kind]} standard changed', details={'revision': record['revision']}
            )
            return self._standards_snapshot()['types'][kind]

    def save_library_overrides(self, key, revision, overrides, kind=None, type_revision=None, type_digest=None):
        _revision(revision)
        reviewed = (kind, type_revision, type_digest)
        guarded = any(value is not None for value in reviewed)
        if guarded:
            if any(value is None for value in reviewed):
                raise UserError('Reload and review the inherited standard before saving')
            _choice(kind, LIBRARY_KINDS, 'library type')
            _revision(type_revision)
            if not isinstance(type_digest, str):
                raise UserError('Reload and review the inherited standard before saving')
        overrides = validate(overrides or {}, partial=True)
        with self.store.transaction():
            library = self.library(key)
            if revision != library.get('standard_revision', 0):
                raise UserError('This library changed in another window; reload before saving')
            effective = self.library_standard(library)
            if guarded and reviewed != (effective['kind'], effective['type_revision'], effective['type_digest']):
                raise UserError('The inherited standard changed while you were reviewing; reload and review again')
            base = self.type_standard(effective['kind'])['values']
            # Keep only real differences, so later changes to the type standard still apply.
            kept = {}
            for dimension, fields in overrides.items():
                changed = {f: v for f, v in fields.items() if base[dimension][f] != v}
                if changed:
                    kept[dimension] = changed
            if kept == (library.get('standard_overrides') or {}):
                return effective
            library.update(standard_overrides=kept, standard_revision=library.get('standard_revision', 0) + 1)
            self.store.put('libraries', key, library)
            self.store.record(
                'standard',
                f'{library.get("title", key)} standard overrides changed',
                library=key,
                details={'revision': library['standard_revision']},
            )
            return self.library_standard(library)
