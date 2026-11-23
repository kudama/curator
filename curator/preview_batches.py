"""Explicit selected preview manifests; each item uses the normal durable renderer."""

import copy
import re
import uuid
from pathlib import PurePosixPath
from .errors import UserError
from .store import now


class PreviewBatches:
    def create_preview_batch(self, data):
        if not isinstance(data, dict) or set(data) != {'items', 'values', 'defaults_revision'}:
            raise UserError('Invalid selected preview batch')
        items = data['items']
        if not isinstance(items, list) or not 1 <= len(items) <= 50:
            raise UserError('Select between 1 and 50 exact media files')
        if any(
            not isinstance(row, dict)
            or set(row) != {'asset', 'asset_version', 'start_ms', 'audio_stream'}
            or not isinstance(row['asset'], str)
            for row in items
        ):
            raise UserError('Invalid selected preview sources')
        if len({row['asset'] for row in items}) != len(items):
            raise UserError('Select each media file only once')
        self.validate_preview_values(data['values'])
        paths = set()
        for item in items:
            try:
                source = self.asset({'asset': item['asset']})
            except UserError:
                continue
            if source['local_path'] in paths:
                raise UserError('Select each physical media file only once')
            paths.add(source['local_path'])
        rows = []
        for item in items:
            row = dict(
                asset=item['asset'], start_ms=item['start_ms'], audio_stream=item['audio_stream'], status='unavailable'
            )
            try:
                asset = self.asset({'asset': item['asset']})
                row.update(
                    title=asset['title'],
                    filename=str(PurePosixPath(asset['plex_path'])),
                    edition=asset.get('item', {}).get('editionTitle'),
                    library=asset['library'],
                )
                plan = self.create_preview_plan(
                    {**item, 'values': data['values'], 'defaults_revision': data['defaults_revision']}
                )
                row.update(plan=plan['id'], status='planned')
            except UserError as error:
                row['error'] = str(error)
            rows.append(row)
        batch = dict(
            id=uuid.uuid4().hex,
            record_type='preview_batch',
            created=now(),
            status='review',
            rows=rows,
            values=copy.deepcopy(data['values']),
            defaults_revision=data['defaults_revision'],
        )
        with self.store.transaction():
            self.store.put('settings', 'preview-batch:' + batch['id'], batch)
        return self.public_preview_batch(batch)

    def preview_batch(self, identity):
        if not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{32}', identity):
            raise UserError('Preview batch not found')
        record = self.store.get('settings', 'preview-batch:' + identity)
        if not record or record.get('record_type') != 'preview_batch':
            raise UserError('Preview batch not found')
        return record

    def public_preview_batch(self, batch):
        rows = []
        for item in batch['rows']:
            row = copy.deepcopy(item)
            if row.get('plan'):
                row['settings'] = self.public_preview_plan(self.preview_plan(row['plan']))
            if row.get('job'):
                task = self.get_task(row['job'])
                row.update(
                    status=task['status'],
                    version=task['version'],
                    error=task.get('error'),
                    saved_in_curator=self.preview_selection(task['asset'])['job'] == task['id'],
                )
            rows.append(row)
        statuses = {row['status'] for row in rows}
        complete = statuses <= {'awaiting_review', 'applied', 'rejected'}
        failed = bool(statuses & {'failed', 'blocked', 'cancelled', 'unavailable'})
        return dict(
            id=batch['id'],
            status=batch['status'],
            created=batch['created'],
            count=len(rows),
            rows=rows,
            ready_count=sum(row['status'] == 'planned' for row in rows),
            outcome='ready_for_review'
            if complete
            else 'mixed'
            if failed
            else 'in_progress'
            if batch['status'] != 'review'
            else 'review',
            values=copy.deepcopy(batch['values']),
            defaults_revision=batch['defaults_revision'],
            request_id=batch.get('request_id'),
            paused=self.store.get('settings', self.pause_key(None, 'optimize'), False),
        )

    def submit_preview_batch(self, identity, request_id):
        if not isinstance(request_id, str) or not re.fullmatch('[a-f0-9-]{32,36}', request_id):
            raise UserError('Use a unique selected batch submission key')
        # Persist the exact selection and key before starting independently durable jobs.
        # A retry resumes only this manifest; per-item renderer keys prevent duplicate work.
        with self.lock, self.store.transaction():
            batch = self.preview_batch(identity)
            previous = self.store.get('settings', 'preview-batch-submit:' + request_id)
            if previous and previous['batch'] != identity:
                raise UserError('Submission key belongs to another batch')
            if batch.get('request_id') and batch['request_id'] != request_id:
                raise UserError('Batch already submitted; inspect the existing jobs')
            if batch['status'] == 'submitted':
                return self.public_preview_batch(batch)
            batch.update(status='submitting', request_id=request_id)
            self.store.put('settings', 'preview-batch-submit:' + request_id, dict(batch=identity))
            self.store.put('settings', 'preview-batch:' + identity, batch)
        for index in range(len(batch['rows'])):
            with self.lock:
                batch = self.preview_batch(identity)
                row = batch['rows'][index]
                if row['status'] != 'planned':
                    continue
                try:
                    asset = self.asset({'asset': row['asset']})
                    if asset.get('item', {}).get('editionTitle') != row.get('edition'):
                        raise UserError('Selected edition changed; review a fresh batch')
                    result = self.generate_preview(
                        row['plan'],
                        uuid.uuid5(uuid.NAMESPACE_URL, 'curator-preview-batch:' + identity + ':' + str(index)).hex,
                    )
                    row.update(job=result['id'], status='queued')
                    with self.store.transaction():
                        task = self.get_task(result['id'])
                        task['preview_batch'] = identity
                        self.store.put('tasks', task['id'], task)
                except UserError as error:
                    row.update(status='unavailable', error=str(error))
                with self.store.transaction():
                    self.store.put('settings', 'preview-batch:' + identity, batch)
        with self.store.transaction():
            batch = self.preview_batch(identity)
            batch.update(status='submitted', submitted_at=now())
            self.store.put('settings', 'preview-batch:' + identity, batch)
            self.store.event(
                None, dict(action='selected preview batch submitted', batch=identity, count=len(batch['rows']))
            )
        return self.public_preview_batch(batch)

    def preview_batches(self, library=None):
        rows = [
            row
            for row in self.store.all('settings')
            if isinstance(row, dict)
            and row.get('record_type') == 'preview_batch'
            and (not library or any(item.get('library') == library for item in row['rows']))
        ]
        return [
            self.public_preview_batch(row) for row in sorted(rows, key=lambda row: row['created'], reverse=True)[:20]
        ]
