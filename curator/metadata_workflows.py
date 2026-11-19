"""Exact, durable metadata previews. Preview/approval never writes to Plex."""
import copy
import uuid
from .plex import Plex
from .store import now
from .errors import UserError
from .rules import ACTIVE


class MetadataWorkflows:
    def metadata_preview(self, refs, fields):
        if (not isinstance(refs, list) or not 1 <= len(refs) <= 5000
                or any(not isinstance(r, dict) or set(r) != {'id', 'version'} for r in refs)
                or len({r['id'] for r in refs}) != len(refs)):
            raise UserError('Choose exact metadata tasks and versions')
        if not isinstance(fields, dict) or not fields or set(fields) - {'title', 'summary', 'studio', 'tagline', 'genre', 'collection', 'cast'}:
            raise UserError('Choose the metadata fields to change')
        for key, value in fields.items():
            if key in {'genre', 'collection'}:
                if not isinstance(value, dict) or set(value) != {'mode', 'values'} or value['mode'] not in {'add', 'replace', 'clear'}:
                    raise UserError('Choose Add, Replace or Clear for list fields')
                Plex.validate_changes({key: value['values']})
                if value['mode'] == 'clear' and value['values']:
                    raise UserError('Clear must not contain values')
            else:
                Plex.validate_changes({key: value})
        rows, seen = [], set()
        for ref in refs:
            task = self.get_task(ref['id'])
            if task['version'] != ref['version'] or task['kind'] not in {'metadata', 'home'} or task['status'] not in {'recommendation', 'resolved', 'applied', 'blocked', 'failed', 'cancelled', 'awaiting_review'} or task.get('deleted'):
                raise UserError('Metadata task changed or is already queued; reopen the editor')
            asset = self.asset(task, check=False)
            identity = (asset['library'], asset['rating_key'])
            if identity in seen:
                raise UserError('Select each Plex item once')
            seen.add(identity)
            item = self.checked_client(self.library(asset['library'])).item(asset['rating_key'])
            if str(item.get('ratingKey')) != asset['rating_key']:
                raise UserError('Metadata destination identity changed')
            before = self.metadata_fields(item)
            changes = {}
            for key, value in fields.items():
                if key in {'genre', 'collection'}:
                    values = [] if value['mode'] == 'clear' else value['values']
                    values = before[key] + values if value['mode'] == 'add' else values
                    unique = {}
                    for name in values:
                        unique.setdefault(name.strip().casefold(), name.strip())
                    value = list(unique.values())
                if key == 'cast':
                    previous = {p['name'].strip().casefold(): p for p in before['cast']}
                    value = [dict(name=p['name'].strip(), role=p.get('role',''), thumb=previous.get(p['name'].strip().casefold(),{}).get('thumb','')) for p in value]
                if not self._same_metadata(before, {key: value}):
                    changes[key] = copy.deepcopy(value)
            from .service import identifier
            destination = self.store.get('tasks', identifier(asset['id'], 'metadata'))
            rows.append(dict(destination_version=destination['version'] if destination else None, task=task['id'], version=task['version'], asset=asset['id'],
                             library=asset['library'], rating_key=asset['rating_key'],
                             guid=item.get('guid'), title=asset['title'], before=before,
                             changes=changes, source=asset.get('fingerprint')))
        receipt = dict(id='metadata-preview:'+uuid.uuid4().hex, record_type='metadata_preview',
                       phase='preview', rows=rows, fields=copy.deepcopy(fields), created=now())
        with self.store.transaction():
            # Task changes during provider reads invalidate the entire preview.
            for row in rows:
                task = self.get_task(row['task'])
                if task['version'] != row['version'] or task['status'] in ACTIVE:
                    raise UserError('A selected task changed during preview')
            self.store.put('settings', receipt['id'], receipt)
        return receipt

    def approve_metadata_preview(self, key):
        receipt = self.store.get('settings', key)
        if not receipt or receipt.get('record_type') != 'metadata_preview':
            raise UserError('Metadata preview not found')
        if receipt['phase'] == 'queued':
            return receipt  # Idempotent approval; never duplicate queue entries.
        # Read current Plex metadata without a database transaction held across I/O.
        for row in receipt['rows']:
            if not row['changes']:
                continue
            item = self.checked_client(self.library(row['library'])).item(row['rating_key'])
            if str(item.get('ratingKey')) != row['rating_key'] or item.get('guid') != row['guid'] or not self._same_metadata(self.metadata_fields(item), row['before']):
                raise UserError('Plex metadata changed after preview; preview again')
        with self.store.transaction():
            current = self.store.get('settings', key)
            if current['phase'] == 'queued':
                return current
            # Validate every row before committing any queue change.
            for row in receipt['rows']:
                task = self.get_task(row['task'])
                asset = self.store.get('assets', row['asset'])
                if task['version'] != row['version'] or task.get('deleted') or task['status'] in ACTIVE or not asset or asset.get('fingerprint') != row['source'] or asset.get('rating_key') != row['rating_key'] or asset.get('library') != row['library']:
                    raise UserError('A selected task or source changed; preview again')
                from .service import identifier
                destination = self.store.get('tasks', identifier(row['asset'], 'metadata'))
                if row['changes'] and (destination['version'] if destination else None) != row['destination_version']:
                    raise UserError('Metadata destination task changed; preview again')
                if row['changes'] and destination and destination['id'] != task['id'] and destination['status'] in ACTIVE:
                    raise UserError('An item already has queued metadata work')
            queued = []
            for row in receipt['rows']:
                if not row['changes']:
                    continue
                asset = self.store.get('assets', row['asset'])
                task = self.task(asset, dict(kind='metadata', reason='Apply reviewed metadata changes'))
                version = task['version'] + 1
                task.update(status='queued', version=version, approval=version,
                            plan={'changes': row['changes']}, metadata_before=row['before'],
                            source=row['source'], updated=now(), error=None)
                self.store.put('tasks', task['id'], task)
                self.store.event(task['id'], dict(action='approved metadata preview', preview=key, version=version))
                self.cancels.discard(task['id'])
                queued.append(task['id'])
            receipt.update(phase='queued', tasks=queued, approved_at=now())
            self.store.put('settings', key, receipt)
        return receipt

    def split_metadata_findings(self):
        """One local migration, using cached observations; never replay approvals."""
        if self.store.get('settings', 'metadata-artwork-split-v1'):
            return
        from .service import identifier
        with self.store.transaction():
            for asset in self.store.all('assets'):
                if asset.get('present') is False or asset.get('artwork_target'):
                    continue
                item = asset.get('item', {})
                old = self.store.get('tasks', identifier(asset['id'], 'metadata'))
                if old and old['status'] == 'recommendation' and not old.get('plan') and not old.get('deleted'):
                    old.update(reason='Description is missing' if not item.get('summary') else 'Metadata finding separated from artwork',
                               status='recommendation' if not item.get('summary') else 'resolved', updated=now())
                    self.store.put('tasks', old['id'], old)
                if not item.get('thumb'):
                    self.task(asset, dict(kind='artwork', reason='Cover artwork is missing', evidence={'discovery': True}))
            self.store.put('settings', 'metadata-artwork-split-v1', {'completed': now()})
