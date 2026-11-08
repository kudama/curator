"""Private local queue with transactional state transitions; no broker required."""
import json
import fcntl
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    TABLES = {'settings', 'libraries', 'assets', 'tasks'}

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
        # Unknown external outcomes are reviewed, never automatically replayed.
        with self.transaction():
            for task in self.all('tasks'):
                if task['status'] in {'running', 'publishing'}:
                    task.update(status='blocked', error='Interrupted operation: inspect outputs before explicit retry')
                    self.put('tasks', task['id'], task)

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
        self.db.execute(f'INSERT INTO {table}(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                        (str(key), json.dumps(value, allow_nan=False)))

    def event(self, task, data):
        self.db.execute('INSERT INTO events(at,task,data) VALUES(?,?,?)', (now(), task, json.dumps(data)))

    def publication_log(self, task):
        with self.lock:
            rows=self.db.execute('SELECT at,data FROM events WHERE task=? ORDER BY id DESC LIMIT 200',(str(task),)).fetchall()
        return [{'at':at,**data} for at,raw in reversed(rows) if (data:=json.loads(raw)).get('action','').startswith('publication ')]

    def _table(self, table):
        if table not in self.TABLES:
            raise ValueError('Invalid record type')

    def close(self):
        self.db.close()
        self.instance_lock.close()
