"""Private local queue with transactional state transitions; no broker required."""

import json
import fcntl
from collections import deque
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .errors import UserError
from .history import current_initiator
from .logs import redact
from .migrations import migrate


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    TABLES = {'settings', 'libraries', 'assets', 'tasks'}
    # Expression indexes on the JSON fields hot paths filter by. They are additive:
    # rows keep their format, nothing is migrated, and dropping them loses nothing.
    INDEXES = {
        'tasks': (('asset',), ('status',), ('kind',), ('library', 'status')),
        'assets': (('library', 'rating_key'),),
        'settings': (('record_type',),),
    }

    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.instance_lock = (self.root / 'instance.lock').open('a+b')
        try:
            fcntl.flock(self.instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.instance_lock.close()
            raise UserError('Curator already has this state directory open') from None
        self.lock = threading.RLock()
        self.deferred = deque(maxlen=200)
        self.db = sqlite3.connect(self.root / 'curator.sqlite3', check_same_thread=False)
        os.chmod(self.root / 'curator.sqlite3', 0o600)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=5000')
        for table in self.TABLES:
            self.db.execute(f'CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, at TEXT, task TEXT, data TEXT)')
        self.db.commit()
        self.json_queries = self._create_indexes()
        try:
            self.migration_backup = migrate(self)
        except Exception:
            self.db.close()
            self.instance_lock.close()
            raise
        # Unknown external outcomes are reviewed, never automatically replayed.
        with self.transaction():
            for task in self.all('tasks'):
                if task['status'] in {'running', 'publishing'}:
                    task.update(status='blocked', error='Interrupted operation: inspect outputs before explicit retry')
                    self.put('tasks', task['id'], task)

    def _create_indexes(self):
        """Index hot JSON fields; without SQLite JSON functions, where() filters in Python."""
        try:
            for table, indexes in self.INDEXES.items():
                for fields in indexes:
                    columns = ', '.join(f"json_extract(data, '$.{field}')" for field in fields)
                    self.db.execute(f'CREATE INDEX IF NOT EXISTS {table}_{"_".join(fields)} ON {table}({columns})')
            self.db.commit()
            return True
        except sqlite3.OperationalError:
            self.db.rollback()
            return False

    def where(self, table, **filters):
        """Rows whose top-level fields equal the given values, in insertion order.

        A set, frozenset, list or tuple value matches any of its members. Use this for
        string fields (ids, statuses, kinds); comparisons follow JSON values exactly.
        """
        self._table(table)
        clauses, params, checks = [], [], []
        for field, value in filters.items():
            if not re.fullmatch(r'[a-z_]+', field):
                raise ValueError('Invalid filter field')
            if value is None or isinstance(value, (bool, dict)):
                raise ValueError('Filter values must be strings or numbers')
            expression = f"json_extract(data, '$.{field}')"
            if isinstance(value, (set, frozenset, list, tuple)):
                values = sorted(set(value), key=str)
                if not values:
                    return []
                clauses.append(f"{expression} IN ({', '.join('?' * len(values))})")
                params.extend(values)
                checks.append((field, set(values)))
            else:
                clauses.append(f'{expression} = ?')
                params.append(value)
                checks.append((field, {value}))
        if not self.json_queries:
            return [
                row
                for row in self.all(table)
                if isinstance(row, dict) and all(row.get(field) in allowed for field, allowed in checks)
            ]
        sql = f'SELECT data FROM {table}' + (' WHERE ' + ' AND '.join(clauses) if clauses else '') + ' ORDER BY rowid'
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute(sql, params)]

    @contextmanager
    def transaction(self):
        with self.lock:
            try:
                self.db.execute('BEGIN IMMEDIATE')
                yield
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            finally:
                self._flush_deferred()

    def get(self, table, key, default=None):
        self._table(table)
        with self.lock:
            row = self.db.execute(f'SELECT data FROM {table} WHERE id=?', (str(key),)).fetchone()
        return json.loads(row[0]) if row else default

    def all(self, table):
        self._table(table)
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute(f'SELECT data FROM {table} ORDER BY rowid')]

    def put(self, table, key, value):
        self._table(table)
        if (
            table == 'tasks'
            and value.get('status') == 'queued'
            and self.get('tasks', key, {}).get('status') != 'queued'
        ):
            value['queue_attempt'] = uuid.uuid4().hex
            value['queued_at'] = now()
            value['queued_by'] = current_initiator()
            order = self.get('settings', 'queue-order:global')
            if order is not None:
                queued = {t['id'] for t in self.where('tasks', status='queued') if not t.get('deleted')}
                ids = [identity for identity in order['ids'] if identity in queued and identity != str(key)] + [
                    str(key)
                ]
                self.put('settings', 'queue-order:global', dict(ids=ids, updated=now()))
        self.db.execute(
            f'INSERT INTO {table}(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
            (str(key), json.dumps(value, allow_nan=False)),
        )

    CURATOR_HISTORY_LIMIT = 5000

    def event(self, task, data, library=None):
        """Job history: an event in a task's trail, recorded with the caller's transaction."""
        if library is None and task is not None:
            library = (self.get('tasks', task) or {}).get('library')
        self.db.execute(
            'INSERT INTO events(at,task,data,category,library,initiator) VALUES(?,?,?,?,?,?)',
            (now(), task, json.dumps(data), 'job', library, current_initiator()),
        )

    def _curator_row(self, action, message, library, level, details):
        if level not in {'info', 'warning', 'error'}:
            raise ValueError('Invalid history level')
        data = dict(action=action, message=message, details=details or {})
        return (now(), json.dumps(data, default=str), library, current_initiator(), level)

    def _insert_curator(self, row):
        cursor = self.db.execute(
            "INSERT INTO events(at,task,data,category,library,initiator,level) VALUES(?,NULL,?,'curator',?,?,?)", row
        )
        if cursor.lastrowid % 500 == 0:
            self.db.execute(
                "DELETE FROM events WHERE category='curator' AND id <= (SELECT id FROM events WHERE category='curator'"
                ' ORDER BY id DESC LIMIT 1 OFFSET ?)',
                (self.CURATOR_HISTORY_LIMIT,),
            )

    def record(self, action, message, library=None, level='info', details=None):
        """Curator history. Inside a transaction it commits or rolls back with it."""
        row = self._curator_row(action, message, library, level, details)
        with self.lock:
            if self.db.in_transaction:
                self._insert_curator(row)
            else:
                with self.transaction():
                    self._insert_curator(row)

    def record_soon(self, action, message, library=None, level='info', details=None):
        """Curator history that must survive a rollback and must never wait for the lock.

        Used for logged errors: the row is written now if the store is idle, otherwise
        after the transaction that is in progress ends, whether it commits or not.
        """
        self.deferred.append(self._curator_row(action, message, library, level, details))
        if self.lock.acquire(blocking=False):
            try:
                if not self.db.in_transaction:
                    self._flush_deferred()
            finally:
                self.lock.release()

    def _flush_deferred(self):
        if not self.deferred or self.db.in_transaction:
            return
        try:
            self.db.execute('BEGIN IMMEDIATE')
            while self.deferred:
                self._insert_curator(self.deferred.popleft())
            self.db.commit()
        except sqlite3.Error:
            self.db.rollback()

    @staticmethod
    def _public(data):
        """Scalar event fields with secrets redacted; nested records stay in the database."""
        return {
            key: redact(value) if isinstance(value, str) else value
            for key, value in data.items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }

    def curator_history(self, library=None, level=None, since=None, until=None, before=None, limit=100):
        clauses, params = ["category = 'curator'"], []
        for clause, value in (
            ('library = ?', library),
            ('level = ?', level),
            ('at >= ?', since),
            ('at < ?', until),
            ('id < ?', before),
        ):
            if value is not None:
                clauses.append(clause)
                params.append(value)
        with self.lock:
            self._flush_deferred()
            rows = self.db.execute(
                'SELECT id, at, data, library, initiator, level FROM events WHERE '
                + ' AND '.join(clauses)
                + ' ORDER BY id DESC LIMIT ?',
                (*params, limit),
            ).fetchall()
        result = []
        for identity, at, raw, library_id, initiator, level_name in rows:
            data = json.loads(raw)
            details = data.get('details') if isinstance(data.get('details'), dict) else {}
            result.append(
                dict(
                    id=identity,
                    at=at,
                    action=data.get('action'),
                    message=redact(str(data.get('message', ''))),
                    details=self._public(details),
                    library=library_id,
                    initiator=initiator,
                    level=level_name,
                )
            )
        return result

    def task_history(self, task, limit=200):
        """A task's event trail, oldest first."""
        with self.lock:
            rows = self.db.execute(
                'SELECT id, at, data, initiator FROM events WHERE task = ? ORDER BY id DESC LIMIT ?', (str(task), limit)
            ).fetchall()
        return [
            dict(id=identity, at=at, initiator=initiator, **self._public(json.loads(raw)))
            for identity, at, raw, initiator in reversed(rows)
        ]

    def latest_task_events(self):
        with self.lock:
            rows = self.db.execute(
                'SELECT task,data FROM events WHERE id IN (SELECT MAX(id) FROM events GROUP BY task)'
            ).fetchall()
        return {key: json.loads(data) for key, data in rows}

    def latest_task_actions(self):
        return {key: data.get('action') for key, data in self.latest_task_events().items()}

    def publication_log(self, task):
        with self.lock:
            rows = self.db.execute(
                'SELECT at,data FROM events WHERE task=? ORDER BY id DESC LIMIT 200', (str(task),)
            ).fetchall()
        return [
            {'at': at, **data}
            for at, raw in reversed(rows)
            if (data := json.loads(raw)).get('action', '').startswith('publication ')
        ]

    def _table(self, table):
        if table not in self.TABLES:
            raise UserError('Invalid record type')

    def close(self):
        with self.lock:
            self._flush_deferred()
            self.db.close()
            self.instance_lock.close()
