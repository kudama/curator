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


def _structured_events(store):
    """Give events a category, library, initiator and level so history can be filtered.

    Every existing event is a job event; its library comes from its task, when the task
    still exists. Initiators of past events are unknown and stay empty.
    """
    db = store.db
    columns = {row[1] for row in db.execute('PRAGMA table_info(events)')}
    for column in ('category', 'library', 'initiator', 'level'):
        if column not in columns:
            db.execute(f'ALTER TABLE events ADD COLUMN {column} TEXT')
    db.execute("UPDATE events SET category = 'job' WHERE category IS NULL")
    libraries = {task['id']: task.get('library') for task in store.all('tasks')}
    rows = db.execute('SELECT DISTINCT task FROM events WHERE library IS NULL AND task IS NOT NULL').fetchall()
    for (task,) in rows:
        if libraries.get(task):
            db.execute('UPDATE events SET library = ? WHERE task = ? AND library IS NULL', (libraries[task], task))
    db.execute('CREATE INDEX IF NOT EXISTS events_task ON events(task, id)')
    db.execute('CREATE INDEX IF NOT EXISTS events_category ON events(category, id)')


def _portrait_posters(store):
    """Normalize future poster preferences, preserving artwork and immutable jobs."""
    from .standards import DEFAULTS

    for kind in DEFAULTS:
        record = store.get('settings', 'standard:' + kind)
        if not record or record.get('record_type') != 'library_standard':
            continue
        artwork = record.get('values', {}).get('artwork', {})
        if artwork.get('poster_ratio') not in (None, '2:3'):
            artwork['poster_ratio'] = '2:3'
            record['revision'] = record.get('revision', 0) + 1
            record['customized'] = record['values'] != DEFAULTS[record['kind']]
            store.put('settings', record['id'], record)
    for library in store.all('libraries'):
        artwork = library.get('standard_overrides', {}).get('artwork', {})
        if artwork.get('poster_ratio') not in (None, '2:3'):
            artwork['poster_ratio'] = '2:3'
            library['standard_revision'] = library.get('standard_revision', 0) + 1
            store.put('libraries', library['id'], library)


MIGRATIONS = (
    (1, _baseline),
    (2, _library_kinds),
    (3, _structured_events),
    (4, _portrait_posters),
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
    latest = MIGRATIONS[-1][0]
    if version > latest:
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
