"""Bounded in-memory fingerprints for incremental browser refreshes.

No private state is duplicated or persisted here. An expired/unknown cursor gets
an ordinary full snapshot, including after a service restart.
"""

import hashlib
import json
import threading
from collections import OrderedDict


class StateUpdates:
    RECORDS = {'assets', 'tasks'}

    def __init__(self, capacity=8):
        self.capacity = capacity
        self.snapshots = OrderedDict()
        self.lock = threading.Lock()

    @staticmethod
    def digest(value):
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        ).hexdigest()

    def response(self, state, since=''):
        records = {key: {row['id']: self.digest(row) for row in state[key]} for key in self.RECORDS}
        fields = {key: self.digest(value) for key, value in state.items() if key not in self.RECORDS}
        manifest = dict(records=records, fields=fields, order={key: list(rows) for key, rows in records.items()})
        revision = self.digest(manifest)
        with self.lock:
            previous = self.snapshots.get(since)
            self.snapshots[revision] = manifest
            self.snapshots.move_to_end(revision)
            while len(self.snapshots) > self.capacity:
                self.snapshots.popitem(last=False)
        if previous is None:
            return dict(revision=revision, reset=True, state=state)
        changes = {}
        for key, current in records.items():
            old = previous['records'][key]
            upsert = [row for row in state[key] if current[row['id']] != old.get(row['id'])]
            removed = [identity for identity in old if identity not in current]
            if upsert or removed or list(current) != list(old):
                changes[key] = dict(upsert=upsert, removed=removed)
                if list(current) != list(old):
                    changes[key]['order'] = list(current)
        return dict(
            revision=revision,
            reset=False,
            changes=changes,
            fields={key: state[key] for key, digest in fields.items() if digest != previous['fields'].get(key)},
        )
