"""Versioned, one-way state migrations.

Each migration runs once, in order, inside its own transaction together with the
version bump, so a crash leaves the state at the previous version and the migration
runs again on the next start. Before any pending migration touches existing state,
the database is copied to <root>/backups/ so an upgrade can be undone by hand.

Migrations must be idempotent and must only reshape Curator's own records. They never
contact Plex, touch media or replay external work.
"""

import sqlite3
from datetime import datetime, timezone

from .errors import UserError
from .rules import library_kind

SCHEMA_TABLE = 'schema_version'


def _baseline(store):
    """Version 1 records the pre-v2 layout; nothing changes."""


def _library_kinds(store):
    """Record each library's Plex library type (movie, show or other_videos)."""
    for library in store.all('libraries'):
        kind = library_kind(library)
        if library.get('kind') != kind:
            library['kind'] = kind
            store.put('libraries', library['id'], library)


MIGRATIONS = (
    (1, _baseline),
    (2, _library_kinds),
)
LATEST = MIGRATIONS[-1][0]


def current_version(db):
    row = db.execute(f'SELECT MAX(version) FROM {SCHEMA_TABLE}').fetchone()
    return row[0] or 0


def _has_state(db, tables):
    return any(db.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone() for table in tables)


def _backup(store, version):
    folder = store.root / 'backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = folder / f'curator-schema-v{version}-{stamp}.sqlite3'
    copy = sqlite3.connect(target)
    try:
        store.db.backup(copy)
    finally:
        copy.close()
    target.chmod(0o600)
    return target


def migrate(store):
    """Bring the state to LATEST. Returns the backup path, or None if none was needed."""
    db = store.db
    db.execute(f'CREATE TABLE IF NOT EXISTS {SCHEMA_TABLE} (version INTEGER PRIMARY KEY, applied TEXT NOT NULL)')
    db.commit()
    version = current_version(db)
    if version > LATEST:
        raise UserError(
            f'This state was written by a newer Curator (schema {version}); update Curator before opening it'
        )
    pending = [(number, step) for number, step in MIGRATIONS if number > version]
    if not pending:
        return None
    backup = _backup(store, version) if _has_state(db, store.TABLES) else None
    for number, step in pending:
        with store.transaction():
            step(store)
            db.execute(
                f'INSERT INTO {SCHEMA_TABLE}(version, applied) VALUES(?, ?)',
                (number, datetime.now(timezone.utc).isoformat()),
            )
    return backup
