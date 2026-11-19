"""Private local queue with transactional state transitions; no broker required."""
import json
import fcntl
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


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
            raise ValueError('Curator already has this state directory open') from None
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / 'curator.sqlite3', check_same_thread=False)
        os.chmod(self.root / 'curator.sqlite3', 0o600)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=5000')
        for table in self.TABLES:
            self.db.execute(f'CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, at TEXT, task TEXT, data TEXT)')
        self.db.commit()
        self.json_queries = self._create_indexes()
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
            return [row for row in self.all(table) if isinstance(row, dict)
                    and all(row.get(field) in allowed for field, allowed in checks)]
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
        if table=='tasks' and value.get('status')=='queued' and self.get('tasks',key,{}).get('status')!='queued':
            value['queue_attempt']=uuid.uuid4().hex;value['queued_at']=now()
            order=self.get('settings','queue-order:global')
            if order is not None:
                queued={t['id'] for t in self.where('tasks', status='queued') if not t.get('deleted')}
                ids=[identity for identity in order['ids'] if identity in queued and identity!=str(key)]+[str(key)]
                self.put('settings','queue-order:global',dict(ids=ids,updated=now()))
        self.db.execute(f'INSERT INTO {table}(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                        (str(key), json.dumps(value, allow_nan=False)))

    def event(self, task, data):
        self.db.execute('INSERT INTO events(at,task,data) VALUES(?,?,?)', (now(), task, json.dumps(data)))

    def latest_task_events(self):
        with self.lock:
            rows=self.db.execute('SELECT task,data FROM events WHERE id IN (SELECT MAX(id) FROM events GROUP BY task)').fetchall()
        return {key:json.loads(data) for key,data in rows}

    def latest_task_actions(self):
        return {key:data.get('action') for key,data in self.latest_task_events().items()}

    def publication_log(self, task):
        with self.lock:
            rows=self.db.execute('SELECT at,data FROM events WHERE task=? ORDER BY id DESC LIMIT 200',(str(task),)).fetchall()
        return [{'at':at,**data} for at,raw in reversed(rows) if (data:=json.loads(raw)).get('action','').startswith('publication ')]

    def _table(self, table):
        if table not in self.TABLES:
            raise ValueError('Invalid record type')

    def close(self):
        with self.lock:
            self.db.close()
            self.instance_lock.close()
