"""Shared task rules and identifiers: one definition each, so modules cannot drift apart."""
import hashlib
import json

# Task kinds that move, join or group files on disk.
FILE_KINDS = frozenset({'rename', 'join', 'group'})
# Work that is running or about to run and may hold its files.
ACTIVE = frozenset({'queued', 'running', 'publishing'})
# A file operation keeps its sources reserved until its result is reviewed.
RESERVING = ACTIVE | {'awaiting_review'}


def stable_id(*values, length=24):
    """Deterministic id for a tuple of JSON values (asset, task, folder and target ids)."""
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:length]


def reserves_source(pending, asset_id):
    """True when pending is a file operation that still holds asset_id."""
    return pending['kind'] in FILE_KINDS and pending['status'] in RESERVING and asset_id in pending['plan']['assets']
