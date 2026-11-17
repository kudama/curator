"""Fixed run membership and durable completion summaries."""
import uuid
from .store import now


class RunSummaries:
    def create_run_receipt(self,library,kind):
        with self.store.transaction():
            records=[r for r in self.store.all('settings') if isinstance(r,dict) and r.get('record_type')=='processing_run' and r['phase']=='active']
            taken={(i['id'],i.get('attempt')) for r in records for i in r['items']};file_taken={key for r in records for key in r['file_items']}
            items=[dict(id=t['id'],version=t['version'],attempt=t.get('queue_attempt')) for t in self.waiting_tasks(library,kind=kind) if (t['id'],t.get('queue_attempt')) not in taken]
            file_items=[j['id'] for j in self.file_jobs() if kind in {None,'file_operations'} and j['phase'] in {'waiting','running'} and (library is None or j['library']==library) and j['id'] not in file_taken]
            if not items and not file_items:return None
            record=dict(id='processing-run:'+uuid.uuid4().hex,record_type='processing_run',phase='active',created=now(),library=library,kind=kind,items=items,file_items=file_items)
            self.store.put('settings',record['id'],record)
        return record['id']

    def _run_summary(self,record):
        if record['phase']!='active':return {k:v for k,v in record.items() if k not in {'items','file_items','record_type'}}
        counts=dict(total=len(record['items'])+len(record['file_items']),ready=0,failed=0,remaining=0,published=0,accepted=0,completed=0,changed=0,cancelled=0)
        pending=[];file_pending=[]
        for item in record['items']:
            task=self.store.get('tasks',item['id'])
            if not task or task.get('deleted') or task['version']!=item['version'] or task.get('queue_attempt')!=item.get('attempt'):counts['changed']+=1;continue
            status=task['status']
            if status in {'queued','running'}:counts['remaining']+=1;pending.append(task)
            elif status=='awaiting_review':counts['ready']+=1
            elif status=='publishing':counts['accepted']+=1
            elif status=='applied':counts['published' if task.get('published') else 'completed']+=1
            elif status in {'blocked','failed'}:counts['failed']+=1
            elif status=='cancelled':counts['cancelled']+=1
            else:counts['changed']+=1
        for identity in record['file_items']:
            job=self.store.get('settings',identity)
            if not job:counts['changed']+=1
            elif job['phase'] in {'waiting','running'}:counts['remaining']+=1;file_pending.append(job)
            elif job['phase']=='complete':counts['published' if job['operation']=='publish' else 'completed']+=1
            else:counts['failed']+=1
        phase='active' if counts['remaining'] else 'needs_attention' if counts['failed'] or counts['changed'] else 'complete'
        if counts['remaining'] and all(t['status']=='queued' and self.store.get('settings',self.pause_key(None,t['kind']),False) for t in pending) and all(j['phase']=='waiting' and self.file_queue_paused() for j in file_pending):phase='paused'
        return dict(id=record['id'],title='Processing run',created=record['created'],phase=phase,counts=counts)

    def refresh_run_receipts(self):
        """Called inside an existing task/job transaction; no lock-order inversion."""
        for record in self.store.all('settings'):
            if not isinstance(record,dict) or record.get('record_type')!='processing_run' or record['phase']!='active':continue
            summary=self._run_summary(record)
            if summary['phase'] in {'complete','needs_attention'}:
                record.update(phase=summary['phase'],counts=summary['counts'],title=summary['title'],finished_at=now())
                self.store.put('settings',record['id'],record)

    def recover_run_receipts(self):
        with self.store.transaction():
            for record in self.store.all('settings'):
                if isinstance(record,dict) and record.get('record_type')=='processing_run' and record['phase']=='active':
                    summary=self._run_summary(record);record.update(phase='interrupted',counts=summary['counts'],title='Interrupted run — resume explicitly',finished_at=now())
                    self.store.put('settings',record['id'],record)

    def run_summaries(self):
        result=[]
        for record in self.store.all('settings'):
            if not isinstance(record,dict):continue
            if record.get('record_type')=='processing_run':result.append(self._run_summary(record))
            elif record.get('record_type')=='review_batch' and record.get('phase') in {'complete','interrupted','stopped'}:
                items=record['items'];counts=dict(total=len(items),published=sum(i['status']=='published' for i in items),reset=sum(i['status']=='reset' for i in items),failed=sum(i['status']=='failed' for i in items),remaining=sum(i['status'] in {'waiting','prepared'} for i in items))
                result.append(dict(id=record['id'],title='Bulk review',created=record['created'],finished_at=record.get('updated',record['created']),phase='needs_attention' if counts['failed'] else record['phase'],counts=counts))
            elif record.get('record_type')=='backup_cleanup' and record.get('phase') in {'complete','interrupted'}:
                selected=[i for i in record['items'] if i['id'] in record.get('selected',[])];counts=dict(total=len(selected),deleted=sum(i['status']=='deleted' for i in selected),failed=sum(i['status']=='failed' for i in selected),remaining=sum(i['status']=='available' for i in selected))
                result.append(dict(id=record['id'],title='Original cleanup',created=record['created'],finished_at=record.get('updated',record['created']),phase='needs_attention' if counts['failed'] else record['phase'],counts=counts))
        active=[r for r in result if r['phase'] in {'active','paused'}]
        recent=sorted((r for r in result if r['phase'] not in {'active','paused'}),key=lambda r:r.get('finished_at',r['created']),reverse=True)[:10]
        return active+recent
