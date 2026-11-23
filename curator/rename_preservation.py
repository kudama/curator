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

Portraits that live in Plex itself (pictures uploaded to the item, which a rematch can
lose) are retained as Plex serves them; agent-supplied pictures are kept as references.
The receipt view never writes. Artwork restores become ordinary artwork review tasks
and portrait restores use the reviewed cast save, both with destination checks (#154).
"""

import base64
import copy
import hashlib
import os
import re
import uuid
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from . import cast, tools
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


def _plex_local_picture(thumb):
    """A picture stored in Plex's own bundle (an upload), which a rematch can lose."""
    parts = urlsplit(thumb or '')
    return not parts.scheme and not parts.netloc and parts.path.startswith('/library/metadata/')


def _write_private(folder, name, data):
    with open(os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as handle:
        handle.write(data)


RESTORE_OPEN = {'recommendation', 'awaiting_review', 'queued', 'running', 'publishing'}
RECEIPT_ID = re.compile(r'[a-f0-9]{24}')


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
        source = Path(asset['local_path'])
        source_fingerprint = tools.fingerprint(source)
        if source.is_symlink() or source_fingerprint != asset.get('fingerprint'):
            raise UserError('Source changed; rename not started')
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
                _write_private(folder, name, data)
                artwork[kind] = dict(file=name, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
            portraits = self._capture_portraits(folder, item, client)
            if source.is_symlink() or tools.fingerprint(source) != source_fingerprint:
                raise UserError('Source changed during capture')
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
            source_fingerprint=source_fingerprint,
            destination_plex_path=str(PurePosixPath(asset['plex_path']).with_name(task['plan']['filename'])),
            metadata=metadata,
            artwork=artwork,
            portraits=portraits,
            status='captured',
        )
        with self.store.transaction():
            self.store.put('settings', receipt['id'], receipt)
            self.store.event(
                task['id'], dict(action='rename preservation captured', receipt=receipt_id, artwork=sorted(artwork))
            )
        return receipt

    def _capture_portraits(self, folder, item, client):
        """Keep the bytes of pictures uploaded into Plex; a missing picture never stops a rename."""
        portraits = []
        for index, row in enumerate(self.metadata_fields(item)['cast'][:100]):
            thumb = row.get('thumb') or ''
            entry = dict(name=row['name'], role=row.get('role', ''))
            if not thumb:
                entry['state'] = 'none'
            elif not _plex_local_picture(thumb):
                entry['state'] = 'reference'  # Supplied by the agent; Plex can fetch it again.
            else:
                try:
                    data = client.cast_image(thumb)
                except Exception:
                    entry.update(state='unavailable', reason='Plex could not load this picture during capture')
                else:
                    name = f'portrait-{index}.{_image_extension(data)}'
                    _write_private(folder, name, data)
                    entry.update(state='retained', file=name, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
            portraits.append(entry)
        return portraits

    def settle_rename_receipt(self, receipt, status, **values):
        """Record a later state of a receipt. The captured snapshot itself never changes."""
        with self.store.transaction():
            latest = self.store.get('settings', receipt['id'])
            if latest is None:
                return None
            latest.update(values, status=status, settled_at=now())
            self.store.put('settings', latest['id'], latest)
            return latest

    def _retained_bytes(self, receipt, entry, what):
        folder = Path(self.store.root) / RECEIPTS / receipt['receipt']
        path = folder / entry['file']
        if folder.is_symlink() or path.is_symlink() or not path.is_file():
            raise UserError(f'Retained {what} is missing from the receipt; it cannot be restored')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise UserError(f'Retained {what} changed on disk; it will not be used')
        return data

    def retained_rename_artwork(self, receipt, kind):
        entry = receipt.get('artwork', {}).get(kind)
        if not entry:
            raise UserError('No retained artwork of this kind')
        return self._retained_bytes(receipt, entry, 'artwork')

    def retained_rename_portrait(self, receipt, index):
        portraits = receipt.get('portraits', [])
        if type(index) is not int or not 0 <= index < len(portraits) or portraits[index].get('state') != 'retained':
            raise UserError('No retained picture for this person')
        return self._retained_bytes(receipt, portraits[index], 'picture')

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
        expected = receipt.get('source_fingerprint' if rolled_back else 'destination_fingerprint')
        if not receipt.get('source_fingerprint') or not expected:
            return self.settle_rename_receipt(
                receipt, 'blocked', reason='File identity was not verified; review the interrupted rename manually'
            )
        path = Path(asset['local_path'])
        if (
            asset.get('library') != receipt['library']
            or path.is_symlink()
            or asset.get('fingerprint') != expected
            or tools.fingerprint(path) != expected
        ):
            return self.settle_rename_receipt(receipt, 'blocked', reason='The file changed after the rename snapshot')
        if receipt.get('item_type') and item.get('type') != receipt['item_type']:
            return self.settle_rename_receipt(receipt, 'blocked', reason='Plex matched the file as a different type')
        current = self.metadata_fields(item)
        captured = receipt['metadata']
        retained, differs, superseded = [], [], []
        for field in METADATA_FIELDS:
            if _comparable(field, current.get(field)) == _comparable(field, captured.get(field)):
                retained.append(field)
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
        portraits = {}
        people = {row['name'].strip().casefold(): row for row in current['cast']}
        for entry in receipt.get('portraits', []):
            if entry.get('state') != 'retained':
                continue
            row = people.get(entry['name'].strip().casefold())
            if not row:
                portraits[entry['name']] = 'person_missing'
            elif not row.get('thumb'):
                portraits[entry['name']] = 'missing'
            else:
                try:
                    observed = hashlib.sha256(client.cast_image(row['thumb'])).hexdigest()
                except Exception:
                    portraits[entry['name']] = 'unreadable'
                    continue
                portraits[entry['name']] = 'retained' if observed == entry['sha256'] else 'changed'
        outcome = dict(
            rematched=str(item['ratingKey']) != receipt['rating_key'],
            rating_key_after=str(item['ratingKey']),
            rolled_back=rolled_back,
            retained=retained,
            differs=differs,
            superseded=superseded,
            artwork=artwork,
            portraits=portraits,
        )
        status = 'reconciled'
        if differs:
            restore = self._propose_metadata_restore(asset, receipt, differs)
            # Classifications are rechecked with the proposal under the same transaction.
            superseded.extend(restore.pop('superseded', []))
            retained.extend(restore.pop('retained', []))
            differs[:] = [field for field in differs if field not in superseded and field not in retained]
            if differs:
                outcome['restore'] = restore
                status = 'review'
        if any(state != 'retained' for state in (*artwork.values(), *portraits.values())):
            status = 'review'
        settled = self.settle_rename_receipt(receipt, status, outcome=outcome)
        lost = [f for f in differs] + [k for k, s in artwork.items() if s != 'retained']
        lost_people = sum(1 for s in portraits.values() if s != 'retained')
        if lost_people:
            lost.append(f'{lost_people} cast picture' + ('s' if lost_people != 1 else ''))
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
        with self.store.transaction():
            current = self.store.get('assets', asset['id'])
            if not current:
                return dict(state='not_proposed', reason='The item is no longer in the catalog')
            if (
                any(
                    current.get(key) != asset.get(key)
                    for key in ('library', 'plex_path', 'local_path', 'rating_key', 'fingerprint')
                )
                or Path(current['local_path']).is_symlink()
                or tools.fingerprint(current['local_path']) != current.get('fingerprint')
            ):
                return dict(state='conflict', reason='The item changed during reconciliation; review it manually')
            newer = self._newer_curator_edits(asset['id'], receipt['captured_at'])
            observed = self.metadata_fields(current['item'])
            superseded = [field for field in fields if field in newer]
            retained = [
                field
                for field in fields
                if field not in newer
                and _comparable(field, observed.get(field)) == _comparable(field, receipt['metadata'].get(field))
            ]
            excluded = dict(superseded=superseded, retained=retained)
            changes = {
                field: copy.deepcopy(receipt['metadata'][field])
                for field in fields
                if field not in superseded and field not in retained
            }
            if not changes:
                return dict(state='not_needed', **excluded)
            if 'cast' in changes:
                changes['cast'] = [
                    {k: v for k, v in row.items() if k in {'name', 'role', 'thumb'}} for row in changes['cast']
                ]
            try:
                Plex.validate_changes(changes)
            except Exception:
                return dict(
                    state='not_proposed', reason='Captured values cannot be written back as they are', **excluded
                )
            task = self.store.get('tasks', self.finding_task_key(current, {'kind': 'metadata'})) or self.task(
                current, dict(kind='metadata', reason='Restore metadata Plex lost after a rename')
            )
            existing = (task.get('plan') or {}).get('changes')
            if (
                task.get('deleted')
                or task['status'] in ACTIVE
                or task['status'] == 'awaiting_review'
                or (existing and task['status'] not in {'applied', 'resolved'})
            ):
                return dict(
                    state='conflict', task=task['id'], reason='Other metadata work for this item is open', **excluded
                )
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
        return dict(state='proposed', task=task['id'], fields=sorted(changes), **excluded)

    # ---- Receipt review and explicit restores (#154). Viewing never writes. ----

    def _receipt(self, receipt_id):
        if not isinstance(receipt_id, str) or not RECEIPT_ID.fullmatch(receipt_id):
            raise UserError('Unknown rename receipt')
        receipt = self.store.get('settings', 'rename-receipt:' + receipt_id)
        if not receipt or receipt.get('record_type') != 'rename_receipt':
            raise UserError('This rename receipt is missing; nothing can be restored from it')
        return receipt

    def rename_receipts(self, library=None, limit=200):
        rows = self.store.where('settings', record_type='rename_receipt')
        if library not in (None, '', 'all'):
            rows = [r for r in rows if r.get('library') == library]
        rows.sort(key=lambda r: r.get('captured_at', ''), reverse=True)
        result = []
        for receipt in rows[: max(1, min(int(limit), 500))]:
            asset = self.store.get('assets', receipt['asset']) or {}
            outcome = receipt.get('outcome') or {}
            open_items = (
                len(outcome.get('differs', []))
                + sum(1 for s in (outcome.get('artwork') or {}).values() if s != 'retained')
                + sum(1 for s in (outcome.get('portraits') or {}).values() if s != 'retained')
            )
            result.append(
                dict(
                    id=receipt['receipt'],
                    title=asset.get('title') or 'Item no longer in the catalog',
                    library=receipt['library'],
                    captured_at=receipt.get('captured_at'),
                    status=receipt.get('status'),
                    needs_review=open_items,
                )
            )
        return result

    def _restore_state(self, entry):
        """What happened to a restore Curator proposed or ran, read from its task now."""
        if not entry:
            return None
        task = self.store.get('tasks', entry['task']) if entry.get('task') else None
        if entry.get('kind') == 'portrait':
            return dict(state=entry.get('state'), error=entry.get('error'), at=entry.get('at'), task=entry.get('task'))
        if not task or task.get('deleted'):
            return dict(state='removed', task=entry.get('task'), at=entry.get('at'))
        state = {
            'awaiting_review': 'waiting_for_review',
            'queued': 'queued',
            'running': 'publishing',
            'publishing': 'publishing',
            'applied': 'restored',
            'rejected': 'rejected',
        }.get(task['status'], 'needs_attention' if task['status'] in {'failed', 'blocked'} else task['status'])
        return dict(state=state, task=task['id'], error=task.get('error'), at=entry.get('at'))

    def rename_receipt_view(self, receipt_id):
        receipt = self._receipt(receipt_id)
        asset = self.store.get('assets', receipt['asset'])
        outcome = receipt.get('outcome') or {}
        current = self.metadata_fields(asset['item']) if asset and asset.get('item') else None
        restores = receipt.get('restores') or {}
        reviewable = receipt.get('status') in {'review', 'reconciled'} and bool(asset) and asset.get('present', True)
        metadata = []
        for field in METADATA_FIELDS:
            state = next(
                (name for name in ('differs', 'superseded', 'retained') if field in outcome.get(name, [])), 'pending'
            )
            captured = receipt['metadata'].get(field)
            now_value = current.get(field) if current else None
            if field == 'cast':
                captured = [dict(name=r['name'], role=r.get('role', '')) for r in captured or []]
                now_value = [dict(name=r['name'], role=r.get('role', '')) for r in now_value or []]
            metadata.append(dict(field=field, captured=captured, current=now_value, state=state))
        artwork = []
        for kind, entry in sorted((receipt.get('artwork') or {}).items()):
            try:
                self.retained_rename_artwork(receipt, kind)
                verified, problem = True, None
            except UserError as error:
                verified, problem = False, str(error)
            state = (outcome.get('artwork') or {}).get(kind, 'pending')
            restore = self._restore_state(restores.get('artwork:' + kind))
            artwork.append(
                dict(
                    kind=kind,
                    bytes=entry['bytes'],
                    verified=verified,
                    problem=problem,
                    state=state,
                    restore=restore,
                    can_restore=reviewable
                    and verified
                    and state in {'changed', 'missing'}
                    and not (restore and restore['state'] in {'waiting_for_review', 'queued', 'publishing'}),
                )
            )
        portraits = []
        for index, entry in enumerate(receipt.get('portraits') or []):
            row = dict(index=index, name=entry['name'], role=entry.get('role', ''), retained=entry.get('state'))
            if entry.get('state') == 'retained':
                try:
                    self.retained_rename_portrait(receipt, index)
                    row['verified'] = True
                except UserError as error:
                    row.update(verified=False, problem=str(error))
                row['state'] = (outcome.get('portraits') or {}).get(entry['name'], 'pending')
                row['restore'] = self._restore_state(restores.get('portrait:' + entry['name']))
                row['can_restore'] = (
                    reviewable
                    and row['verified']
                    and row['state'] in {'changed', 'missing'}
                    and not (row['restore'] and row['restore']['state'] == 'restored')
                )
            elif entry.get('reason'):
                row['problem'] = entry['reason']
            portraits.append(row)
        metadata_restore = outcome.get('restore')
        if metadata_restore and metadata_restore.get('task'):
            task = self.store.get('tasks', metadata_restore['task'])
            metadata_restore = dict(metadata_restore, task_status=task and task['status'])
        return dict(
            id=receipt['receipt'],
            title=(asset or {}).get('title') or 'Item no longer in the catalog',
            asset=receipt['asset'],
            library=receipt['library'],
            status=receipt.get('status'),
            reason=receipt.get('reason'),
            captured_at=receipt.get('captured_at'),
            settled_at=receipt.get('settled_at'),
            version=receipt.get('settled_at') or receipt.get('captured_at'),
            renamed=dict(
                before=PurePosixPath(receipt['source_plex_path']).name,
                after=PurePosixPath(receipt['destination_plex_path']).name,
            ),
            rematched=outcome.get('rematched'),
            rolled_back=outcome.get('rolled_back'),
            present=bool(asset and asset.get('present', True)),
            current_as_of='last library scan',
            metadata=metadata,
            metadata_restore=metadata_restore,
            artwork=artwork,
            portraits=portraits,
            cast_digest=self._cast_digest(current['cast']) if current else None,
        )

    def rename_receipt_image(self, receipt_id, kind=None, person=None):
        receipt = self._receipt(receipt_id)
        if kind is not None:
            return self.retained_rename_artwork(receipt, kind)
        return self.retained_rename_portrait(receipt, person)

    @staticmethod
    def _cast_digest(rows):
        return cast.digest(rows)

    def _restore_target(self, receipt_id, version):
        """The verified destination for a restore. Raises without writing anything."""
        receipt = self._receipt(receipt_id)
        if (receipt.get('settled_at') or receipt.get('captured_at')) != version:
            raise UserError('This receipt changed since you opened it; reopen it before restoring')
        if receipt.get('status') not in {'review', 'reconciled'}:
            raise UserError('Only a checked rename can be restored; this one is ' + str(receipt.get('status')))
        asset = self.store.get('assets', receipt['asset'])
        if not asset or not asset.get('present', True) or asset.get('library') != receipt['library']:
            raise UserError('The renamed item is no longer in this library; nothing was restored')
        outcome = receipt.get('outcome') or {}
        expected_path = receipt['source_plex_path'] if outcome.get('rolled_back') else receipt['destination_plex_path']
        expected_print = receipt.get('source_fingerprint' if outcome.get('rolled_back') else 'destination_fingerprint')
        path = Path(asset['local_path'])
        if (
            asset['plex_path'] != expected_path
            or not expected_print
            or path.is_symlink()
            or asset.get('fingerprint') != expected_print
            or tools.fingerprint(path) != expected_print
        ):
            raise UserError('The file changed or moved after the rename; review it manually. Nothing was restored.')
        client = self.checked_client(self.library(asset['library']))
        try:
            item = client.item(asset['rating_key'])
        except Exception:
            raise UserError(
                "Plex has not associated this file with an item yet. Try again after Plex's next scan; "
                'Curator does not force a refresh. Nothing was restored.'
            ) from None
        paths = sorted(part.get('file', '') for media in item.get('Media', []) for part in media.get('Part', []))
        if str(item.get('ratingKey')) != asset['rating_key'] or expected_path not in paths:
            raise UserError('Plex now matches a different file to this item; rescan first. Nothing was restored.')
        if receipt.get('item_type') and item.get('type') != receipt['item_type']:
            raise UserError('Plex matched the file as a different type; nothing was restored')
        return receipt, asset, client, item, paths

    def restore_rename_artwork(self, receipt_id, version, kinds):
        """Turn selected retained images into ordinary artwork review tasks. Never publishes."""
        if not isinstance(kinds, list) or not kinds or len(set(kinds)) != len(kinds):
            raise UserError('Choose the artwork to restore')
        receipt, asset, client, item, paths = self._restore_target(receipt_id, version)
        planned, already = [], []
        for kind in kinds:
            if kind not in (receipt.get('artwork') or {}):
                raise UserError('This receipt has no retained artwork of that kind')
            data = self.retained_rename_artwork(receipt, kind)
            current = (
                hashlib.sha256(client.image(asset['rating_key'], kind)).hexdigest()
                if Plex.artwork_path(item, kind)
                else None
            )
            candidate = self._folder_photo(encoded=base64.b64encode(data).decode())
            if current == candidate:
                already.append(kind)
                continue
            planned.append(
                dict(
                    id=uuid.uuid4().hex,
                    asset=asset['id'],
                    library=asset['library'],
                    title=item.get('title', asset['title']),
                    kind='artwork',
                    status='awaiting_review',
                    version=1,
                    reason='Restore artwork kept before a rename',
                    plan=dict(
                        kind=kind,
                        assets=[asset['id']],
                        rating_key=asset['rating_key'],
                        candidate=candidate,
                        original=current,
                        source_image=candidate,
                        target=dict(guid=item.get('guid'), paths=paths),
                        rename_receipt=receipt['receipt'],
                    ),
                    evidence={
                        'destination': asset['rating_key'],
                        'rename_receipt': receipt['receipt'],
                        'outbound_files': [],
                        'paid_submission_enabled': False,
                    },
                    created=now(),
                    updated=now(),
                )
            )
        with self.store.transaction():
            latest = self.store.get('settings', receipt['id'])
            if (latest.get('settled_at') or latest.get('captured_at')) != version:
                raise UserError('This receipt changed while preparing the restore; nothing was created')
            restores = latest.setdefault('restores', {})
            for task in planned:
                key = 'artwork:' + task['plan']['kind']
                state = self._restore_state(restores.get(key))
                if state and state['state'] in {'waiting_for_review', 'queued', 'publishing'}:
                    raise UserError('A restore of this artwork is already open; review that one first')
            for task in planned:
                self.store.put('tasks', task['id'], task)
                self.store.event(
                    task['id'], dict(action='artwork restore proposed from rename receipt', receipt=receipt['receipt'])
                )
                restores['artwork:' + task['plan']['kind']] = dict(kind='artwork', task=task['id'], at=now())
            self.store.put('settings', latest['id'], latest)
        for task in planned:
            self.queue_artwork_archive(task)
        return dict(tasks=[t['id'] for t in planned], already=already, receipt=self.rename_receipt_view(receipt_id))

    def restore_rename_portraits(self, receipt_id, version, people, cast_digest):
        """Put retained pictures back for the selected people only, through the reviewed cast save."""
        if not isinstance(people, list) or not people or len(set(people)) != len(people):
            raise UserError('Choose the people whose pictures to restore')
        receipt, asset, client, item, _ = self._restore_target(receipt_id, version)
        cached = self.metadata_fields(asset['item'])['cast']
        if self._cast_digest(cached) != cast_digest:
            raise UserError('The cast changed since you opened this receipt; reopen it. Nothing was restored.')
        live = self.metadata_fields(item)['cast']
        if self._cast_digest(live) != cast_digest:
            raise UserError(
                'Plex has newer cast changes than the last scan; rescan, then review again. Nothing was restored.'
            )
        entries = receipt.get('portraits') or []
        chosen = {}
        for index in people:
            if type(index) is not int or not 0 <= index < len(entries):
                raise UserError('Unknown person in this receipt')
            data = self.retained_rename_portrait(receipt, index)
            matches = [
                row for row in live if row['name'].strip().casefold() == entries[index]['name'].strip().casefold()
            ]
            if len(matches) != 1:
                raise UserError(
                    f"{entries[index]['name']} is no longer credited on this item; restore the credit first. "
                    'Nothing was restored.'
                )
            chosen[matches[0]['name']] = data
        task = self.metadata_task(asset['id'])
        if task['status'] in ACTIVE or task['status'] == 'awaiting_review':
            raise UserError('Other metadata work for this item is open; finish it first. Nothing was restored.')
        rows = [
            dict(name=row['name'], role=row.get('role', ''), image=base64.b64encode(chosen[row['name']]).decode())
            if row['name'] in chosen
            else dict(name=row['name'], role=row.get('role', ''), thumb=row.get('thumb', ''))
            for row in live
        ]
        try:
            self.apply_cast(task['id'], task['version'], rows, expected_cast=cast_digest)
            outcome, error = 'restored', None
        except UserError as failure:
            outcome, error = 'failed', str(failure)
        with self.store.transaction():
            latest = self.store.get('settings', receipt['id'])
            restores = latest.setdefault('restores', {})
            for name in chosen:
                index = next(
                    i for i, e in enumerate(entries) if e['name'].strip().casefold() == name.strip().casefold()
                )
                restores['portrait:' + entries[index]['name']] = dict(
                    kind='portrait', task=task['id'], state=outcome, error=error, at=now()
                )
            self.store.put('settings', latest['id'], latest)
            self.store.event(
                task['id'],
                dict(action='cast pictures restored from rename receipt', receipt=receipt['receipt'], result=outcome),
            )
        if error:
            raise UserError(error + ' The retained pictures are still in the receipt.')
        return self.rename_receipt_view(receipt_id)
