"""Preserve curated Plex metadata and selected artwork across Curator renames (#70).

Before any file moves, a rename captures a fresh read of the Plex item and the bytes
of every selected artwork kind into a private, immutable recovery receipt. Plex may
later rematch the renamed file under a new rating key and lose edited metadata. The
next library scan reconciles the receipt, but only for an exact verified destination:
the same asset, library, item type, path and unchanged local fingerprint.

Fields Plex retained need nothing. Fields that now differ become a proposed restore on
the item's existing metadata task, reviewed and applied through the existing metadata
workflow; nothing is written to Plex automatically. Fields Curator itself changed after
the capture are never proposed. Retained artwork bytes stay in the receipt for an
explicit restore. No Plex refresh is forced and no paid generation is replayed.
"""

import copy
import hashlib
import os
from pathlib import PurePosixPath

from .errors import UserError
from .logs import log, redact
from .plex import Plex
from .rules import ACTIVE, stable_id
from .store import now

RECEIPTS = 'rename-receipts'
METADATA_FIELDS = ('title', 'summary', 'studio', 'tagline', 'genre', 'collection', 'label', 'cast')
TAG_FIELDS = ('genre', 'collection', 'label')


def _image_extension(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    return 'bin'


def _comparable(field, value):
    if field in TAG_FIELDS and isinstance(value, list):
        return sorted({tag.casefold() for tag in value})
    if field == 'cast' and isinstance(value, list):
        return [(row.get('name', ''), row.get('role', '')) for row in value]
    return value


class RenamePreservation:
    def _receipt_dir(self, receipt_id):
        root = self.store.root / RECEIPTS
        root.mkdir(mode=0o700, exist_ok=True)
        folder = root / receipt_id
        folder.mkdir(mode=0o700, exist_ok=False)
        return folder

    def capture_rename_receipt(self, task, asset, client):
        """Fresh pre-move snapshot. Raises before anything moves if it cannot be taken."""
        try:
            item = client.item(asset['rating_key'])
        except Exception as error:
            raise UserError('Could not read the current Plex metadata; rename not started') from error
        if asset['plex_path'] not in {
            part.get('file') for media in item.get('Media', []) for part in media.get('Part', [])
        }:
            raise UserError('Plex item no longer matches this file; rescan before renaming')
        receipt_id = stable_id('rename-receipt', task['id'], task['version'], now(), length=24)
        folder = self._receipt_dir(receipt_id)
        artwork = {}
        try:
            for kind in Plex.ARTWORK:
                if not Plex.artwork_path(item, kind):
                    continue
                data = client.image(item['ratingKey'], kind)
                if not data:
                    raise UserError('Selected artwork could not be read')
                name = f'{kind}.{_image_extension(data)}'
                path = folder / name
                with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as handle:
                    handle.write(data)
                artwork[kind] = dict(file=name, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
        except Exception as error:
            for child in folder.iterdir():
                child.unlink()
            folder.rmdir()
            if isinstance(error, UserError):
                raise UserError(f'{error}; rename not started') from None
            raise UserError('Could not preserve the selected artwork; rename not started') from error
        metadata = self.metadata_fields(item)
        # Portrait references are kept only as text, with any credential removed.
        metadata['cast'] = [dict(row, thumb=redact(row.get('thumb', ''))) for row in metadata['cast']]
        receipt = dict(
            id='rename-receipt:' + receipt_id,
            record_type='rename_receipt',
            receipt=receipt_id,
            task=task['id'],
            task_version=task['version'],
            asset=asset['id'],
            library=asset['library'],
            captured_at=now(),
            rating_key=str(item['ratingKey']),
            item_type=item.get('type'),
            source_plex_path=asset['plex_path'],
            destination_plex_path=str(PurePosixPath(asset['plex_path']).with_name(task['plan']['filename'])),
            metadata=metadata,
            artwork=artwork,
            status='captured',
        )
        with self.store.transaction():
            self.store.put('settings', receipt['id'], receipt)
            self.store.event(
                task['id'], dict(action='rename preservation captured', receipt=receipt_id, artwork=sorted(artwork))
            )
        return receipt

    def settle_rename_receipt(self, receipt, status, **values):
        """Record a later state of a receipt. The captured snapshot itself never changes."""
        with self.store.transaction():
            latest = self.store.get('settings', receipt['id'])
            if latest is None:
                return None
            latest.update(values, status=status, settled_at=now())
            self.store.put('settings', latest['id'], latest)
            return latest

    def retained_rename_artwork(self, receipt, kind):
        entry = receipt.get('artwork', {}).get(kind)
        if not entry:
            raise UserError('No retained artwork of this kind')
        from pathlib import Path

        data = (Path(self.store.root) / RECEIPTS / receipt['receipt'] / entry['file']).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise UserError('Retained artwork changed on disk; it will not be used')
        return data

    def pending_rename_receipts(self, library_id):
        return [
            r
            for r in self.store.where('settings', record_type='rename_receipt', library=library_id)
            # captured: interrupted before or during moving; moved: files are at the destination.
            if r.get('status') in {'captured', 'moved'}
        ]

    def _newer_curator_edits(self, asset_id, since):
        """Fields Curator itself wrote to this item after the receipt was captured."""
        fields = set()
        for task in self.store.where('tasks', asset=asset_id, kind=('metadata', 'home'), status='applied'):
            if (task.get('updated') or '') > since:
                fields.update((task.get('plan') or {}).get('changes', {}))
        return fields

    def reconcile_rename_receipts(self, library, scanned, client):
        """Compare moved receipts with what this scan found. scanned maps asset id -> Plex item."""
        results = []
        for receipt in self.pending_rename_receipts(library['id']):
            try:
                results.append(self._reconcile_one(library, receipt, scanned, client))
            except Exception:
                log.exception('Rename reconciliation failed for %s', receipt['id'])
        return results

    def _reconcile_one(self, library, receipt, scanned, client):
        asset = self.store.get('assets', receipt['asset'])
        item = scanned.get(receipt['asset'])
        if not asset or item is None:
            return None  # Not seen in this scan; try again next time.
        rolled_back = asset['plex_path'] == receipt['source_plex_path']
        if asset['plex_path'] not in {receipt['destination_plex_path'], receipt['source_plex_path']}:
            return self.settle_rename_receipt(receipt, 'blocked', reason='The file moved again; review it manually')
        if receipt.get('destination_fingerprint') and not rolled_back:
            if asset.get('fingerprint') != receipt['destination_fingerprint']:
                return self.settle_rename_receipt(
                    receipt, 'blocked', reason='The renamed file changed after the rename'
                )
        if receipt.get('item_type') and item.get('type') != receipt['item_type']:
            return self.settle_rename_receipt(receipt, 'blocked', reason='Plex matched the file as a different type')
        current = self.metadata_fields(item)
        captured = receipt['metadata']
        newer = self._newer_curator_edits(asset['id'], receipt['captured_at'])
        retained, differs, superseded = [], [], []
        for field in METADATA_FIELDS:
            if _comparable(field, current.get(field)) == _comparable(field, captured.get(field)):
                retained.append(field)
            elif field in newer:
                superseded.append(field)
            else:
                differs.append(field)
        artwork = {}
        for kind, entry in receipt.get('artwork', {}).items():
            if not Plex.artwork_path(item, kind):
                artwork[kind] = 'missing'
                continue
            try:
                observed = hashlib.sha256(client.image(item['ratingKey'], kind)).hexdigest()
            except Exception:
                artwork[kind] = 'unreadable'
                continue
            artwork[kind] = 'retained' if observed == entry['sha256'] else 'changed'
        outcome = dict(
            rematched=str(item['ratingKey']) != receipt['rating_key'],
            rating_key_after=str(item['ratingKey']),
            rolled_back=rolled_back,
            retained=retained,
            differs=differs,
            superseded=superseded,
            artwork=artwork,
        )
        status = 'reconciled'
        if differs:
            outcome['restore'] = self._propose_metadata_restore(asset, receipt, differs)
            status = 'review'
        if any(state != 'retained' for state in artwork.values()):
            status = 'review'
        settled = self.settle_rename_receipt(receipt, status, outcome=outcome)
        lost = [f for f in differs] + [k for k, s in artwork.items() if s != 'retained']
        self.store.record_soon(
            'rename preservation',
            (
                f'{asset["title"]}: renamed item checked; nothing lost'
                if not lost
                else f'{asset["title"]}: Plex no longer has {", ".join(lost)} after the rename; review the restore'
            ),
            library=library['id'],
            level='info' if not lost else 'warning',
            details={'receipt': receipt['receipt'], 'rematched': outcome['rematched']},
        )
        return settled

    def _propose_metadata_restore(self, asset, receipt, fields):
        """A reviewable proposal on the item's metadata task; never a Plex write."""
        changes = {field: copy.deepcopy(receipt['metadata'][field]) for field in fields}
        if 'cast' in changes:
            changes['cast'] = [
                {k: v for k, v in row.items() if k in {'name', 'role', 'thumb'}} for row in changes['cast']
            ]
        try:
            Plex.validate_changes(changes)
        except Exception:
            return dict(state='not_proposed', reason='Captured values cannot be written back as they are')
        with self.store.transaction():
            current = self.store.get('assets', asset['id'])
            if not current:
                return dict(state='not_proposed', reason='The item is no longer in the catalog')
            task = self.task(current, dict(kind='metadata', reason='Restore metadata Plex lost after a rename'))
            existing = (task.get('plan') or {}).get('changes')
            if (
                task.get('deleted')
                or task['status'] in ACTIVE
                or task['status'] == 'awaiting_review'
                or (existing and task['status'] not in {'applied', 'resolved'})
            ):
                return dict(state='conflict', task=task['id'], reason='Other metadata work for this item is open')
            task.update(
                status='recommendation',
                version=task['version'] + 1,
                reason='Restore metadata Plex lost after a rename',
                plan={'changes': changes},
                evidence={'rename_receipt': receipt['receipt'], 'fields': sorted(changes)},
                metadata_before=self.metadata_fields(current['item']),
                updated=now(),
                error=None,
            )
            task.pop('approval', None)
            self.store.put('tasks', task['id'], task)
            self.store.event(
                task['id'],
                dict(action='rename restore proposed', receipt=receipt['receipt'], fields=sorted(changes)),
            )
        return dict(state='proposed', task=task['id'], fields=sorted(changes))
