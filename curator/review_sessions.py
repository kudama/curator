"""Durable review position; task actions retain publication authority."""

import uuid
from .store import now
from .errors import UserError


class ReviewSessions:
    def review_session(self, identity):
        record = self.store.get('settings', identity)
        if not isinstance(record, dict) or record.get('record_type') != 'review_session':
            raise UserError('Review session unavailable')
        self._reconcile_review_session(record)
        return record

    def _reconcile_review_session(self, record):
        actions = None
        for item in record['items']:
            if item['decision'] != 'pending':
                continue
            try:
                task = self.get_task(item['id'])
            except ValueError:
                task = None
            if (
                task
                and not task.get('deleted')
                and task['version'] == item['version']
                and task['status'] == 'awaiting_review'
            ):
                continue
            if task and task['version'] == item['version'] and task['status'] in {'publishing', 'applied'}:
                item.update(decision='accepted', outcome=task['status'])
            elif task and task['version'] == item['version'] + 1 and task['status'] == 'recommendation':
                if actions is None:
                    actions = self.store.latest_task_actions()
                item.update(decision='rejected' if actions.get(task['id']) == 'reject' else 'unavailable')
            else:
                item.update(decision='unavailable')
        while record['cursor'] < len(record['items']) and record['items'][record['cursor']]['decision'] != 'pending':
            record['cursor'] += 1
        record['complete'] = record['cursor'] >= len(record['items'])

    def open_review_session(self, identity=None, library=None, kind=None, refs=None):
        with self.lock, self.store.transaction():
            if identity is not None:
                record = self.review_session(identity)
                record.update(version=record['version'] + 1, updated=now())
            else:
                if library is not None:
                    self.library(library)
                if kind not in {None, 'upscale', 'optimize'}:
                    raise UserError('Choose upscale or encoding results for continuous review')
                selected = None
                if refs is not None:
                    if (
                        not isinstance(refs, list)
                        or len(refs) > 5000
                        or any(
                            not isinstance(r, dict)
                            or set(r) != {'id', 'version'}
                            or not isinstance(r['id'], str)
                            or type(r['version']) is not int
                            for r in refs
                        )
                    ):
                        raise UserError('Invalid review selection')
                    selected = {r['id']: r['version'] for r in refs}
                    if len(selected) != len(refs):
                        raise UserError('Duplicate review selection')
                tasks = [
                    t
                    for t in self.store.all('tasks')
                    if not t.get('deleted')
                    and t['status'] == 'awaiting_review'
                    and t['kind'] in {'upscale', 'optimize'}
                    and (library is None or t['library'] == library)
                    and (kind is None or t['kind'] == kind)
                ]
                if selected is not None:
                    tasks = [t for t in tasks if selected.get(t['id']) == t['version']]
                tasks.sort(key=lambda t: (t.get('updated', t.get('created', '')), t['id']))
                record = dict(
                    id='review-session:' + uuid.uuid4().hex,
                    record_type='review_session',
                    version=1,
                    cursor=0,
                    library=library,
                    kind=kind,
                    created=now(),
                    updated=now(),
                    items=[dict(id=t['id'], version=t['version'], decision='pending') for t in tasks[:5000]],
                    remaining=max(0, len(tasks) - 5000),
                    complete=not tasks,
                )
            self.store.put('settings', record['id'], record)
        return record

    def step_review_session(self, identity, version, key, decision):
        if decision not in {'accepted', 'rejected', 'skipped'} or type(version) is not int:
            raise UserError('Invalid review decision')
        with self.lock, self.store.transaction():
            raw = self.store.get('settings', identity)
            if not isinstance(raw, dict) or raw.get('record_type') != 'review_session' or raw['version'] != version:
                raise UserError('Review position changed; resume the current session')
            if raw['cursor'] < len(raw['items']) and raw['items'][raw['cursor']]['id'] != key:
                self._reconcile_review_session(raw)
            if raw['cursor'] >= len(raw['items']) or raw['items'][raw['cursor']]['id'] != key:
                raise UserError('This is no longer the current review item')
            item = raw['items'][raw['cursor']]
            task = self.get_task(key)
            if decision == 'accepted' and (
                task['version'] != item['version'] or task['status'] not in {'publishing', 'applied'}
            ):
                raise UserError('The result has not been accepted for publication')
            if decision == 'rejected' and (
                task['version'] != item['version'] + 1
                or task['status'] != 'recommendation'
                or self.store.latest_task_actions().get(key) != 'reject'
            ):
                raise UserError('The result has not been reset')
            if decision == 'skipped' and (
                task['version'] != item['version'] or task['status'] != 'awaiting_review' or task.get('deleted')
            ):
                raise UserError('Task changed; resume review')
            item.update(decision=decision, outcome=task['status'])
            raw['cursor'] += 1
            self._reconcile_review_session(raw)
            raw.update(version=version + 1, updated=now())
            self.store.put('settings', identity, raw)
        return raw
