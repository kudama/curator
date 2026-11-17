"""Explicit, sequential review batches; publication uses the existing per-task gates."""
import threading
import uuid
from .store import now


class BulkReviewWorkflows:
    def recover_review_batches(self):
        with self.store.transaction():
            for batch in self.store.all('settings'):
                if isinstance(batch,dict) and batch.get('record_type')=='review_batch' and batch.get('phase') in {'preparing','publishing','rejecting'}:
                    batch.update(phase='interrupted',updated=now())
                    self.store.put('settings',batch['id'],batch)

    def review_batch(self,identity):
        batch=self.store.get('settings',identity)
        if not isinstance(batch,dict) or batch.get('record_type')!='review_batch':raise ValueError('Review batch unavailable')
        return batch

    def review_batches(self,library):
        batches=[batch for batch in self.store.all('settings') if isinstance(batch,dict) and batch.get('record_type')=='review_batch' and (library is None or batch.get('library')==library)]
        return [{'id':b['id'],'phase':b['phase'],'created':b['created'],'count':len(b['items'])} for b in sorted(batches,key=lambda b:b['created'],reverse=True)[:30]]

    def _save_review_batch(self,batch,preserve_stop=False):
        with self.store.transaction():
            if preserve_stop:
                latest=self.store.get('settings',batch['id'],{})
                batch['cancel_requested']=bool(batch.get('cancel_requested') or latest.get('cancel_requested'))
            batch['updated']=now();self.store.put('settings',batch['id'],batch)

    def _launch_review_batch(self,batch,publish=False,background=True,reject=False):
        with self.lock:
            if any(str(value).startswith('review-batch:') for value in self.active):
                raise ValueError('Another review batch is active; finish or stop it first')
            self.active.add(batch['id'])
            batch.update(phase='rejecting' if reject else 'publishing' if publish else 'preparing',cancel_requested=False)
            self._save_review_batch(batch)
        if background:
            threading.Thread(target=self._run_rejection_batch if reject else self._run_review_batch,args=(batch['id'],) if reject else (batch['id'],publish),daemon=True).start()
        elif reject:self._run_rejection_batch(batch['id'])
        else:self._run_review_batch(batch['id'],publish)
        return self.review_batch(batch['id'])

    def new_review_batch(self,library,refs):
        if not isinstance(refs,list) or not 1<=len(refs)<=5000:raise ValueError('Select between 1 and 5000 results')
        seen=set()
        for ref in refs:
            if not isinstance(ref,dict) or set(ref)!={'id','version'} or not isinstance(ref['id'],str) or len(ref['id'])>128 or type(ref['version']) is not int:
                raise ValueError('Invalid task selection')
            if ref['id'] in seen:raise ValueError('Duplicate task selection')
            seen.add(ref['id'])
        batch={'id':'review-batch:'+uuid.uuid4().hex,'record_type':'review_batch','library':library,
               'created':now(),'items':[{**ref,'status':'waiting'} for ref in refs]}
        return batch

    def prepare_review_batch(self,library,refs,background=True):
        return self._launch_review_batch(self.new_review_batch(library,refs),background=background)

    def accept_selected_results(self,library,refs,count,confirmation,background=True):
        if not isinstance(refs,list) or type(count) is not int or count!=len(refs) or confirmation!='PUBLISH SELECTED WITHOUT INDIVIDUAL REVIEW':
            raise ValueError('Confirm the exact selected result count and bulk-publication warning')
        batch=self.new_review_batch(library,refs)
        batch.update(automatic_publish=True,approved_count=count,approved_at=now())
        return self._launch_review_batch(batch,background=background)

    def reject_selected_results(self,library,refs,count,background=True):
        if not isinstance(refs,list) or type(count) is not int or count!=len(refs):raise ValueError('Confirm the current selected count')
        return self._launch_review_batch(self.new_review_batch(library,refs),background=background,reject=True)

    def publish_review_batch(self,identity,count,background=True):
        with self.lock:
            batch=self.review_batch(identity)
            prepared=sum(item['status']=='prepared' for item in batch['items'])
            if batch['phase']!='ready' or type(count) is not int or count!=prepared or not prepared:
                raise ValueError('Review the current prepared count before publishing')
            batch['approved_count']=count;batch['approved_at']=now()
            return self._launch_review_batch(batch,publish=True,background=background)

    def stop_review_batch(self,identity):
        with self.store.transaction():
            batch=self.review_batch(identity)
            if batch['phase'] not in {'preparing','publishing','rejecting'}:raise ValueError('This review batch is not running')
            batch['cancel_requested']=True;batch['updated']=now()
            self.store.put('settings',identity,batch)
        return batch

    def _run_review_batch(self,identity,publish):
        try:
            batch=self.review_batch(identity)
            for index,item in enumerate(batch['items']):
                latest=self.review_batch(identity)
                if latest.get('cancel_requested'):
                    batch.update(phase='stopped',cancel_requested=True);break
                if item['status']!=('prepared' if publish else 'waiting'):continue
                try:
                    task=self.get_task(item['id'])
                    if task.get('deleted') or (batch['library'] is not None and task['library']!=batch['library']) or task['kind'] not in {'upscale','optimize'} or task['status']!='awaiting_review' or task['version']!=item['version']:
                        raise ValueError('Task changed or is no longer an eligible video result')
                    if publish:
                        result=self.review(item['id'],item['version'],'batch comparison',background=False)
                        if result['status']!='applied':raise ValueError('Publication did not complete; inspect the task')
                        item.update(status='published')
                    else:
                        self.comparison(item['id'])
                        observed=self.get_task(item['id'])
                        if observed['version']!=item['version'] or observed['status']!='awaiting_review':
                            raise ValueError('Task changed while preparing its comparison')
                        item.update(status='prepared')
                except Exception as error:
                    item.update(status='failed',error=str(error)[:250] if isinstance(error,ValueError) else 'Operation failed; inspect this task')
                # Preserve a stop request made while this file was being processed.
                self._save_review_batch(batch,preserve_stop=True)
            else:batch['phase']='complete' if publish else 'ready'
            self._save_review_batch(batch,preserve_stop=True)
            if not publish and batch['phase']=='ready' and batch.get('automatic_publish') and not batch.get('cancel_requested'):
                batch.update(phase='publishing');self._save_review_batch(batch,preserve_stop=True)
                self._run_review_batch(identity,True)
        except Exception:
            with self.store.transaction():
                batch=self.review_batch(identity);batch.update(phase='interrupted',updated=now())
                self.store.put('settings',identity,batch)
        finally:
            with self.lock:self.active.discard(identity)

    def _run_rejection_batch(self,identity):
        batch=self.review_batch(identity)
        try:
            for item in batch['items']:
                if self.review_batch(identity).get('cancel_requested'):
                    batch.update(phase='stopped');break
                try:
                    task=self.get_task(item['id'])
                    if task.get('deleted') or task['kind'] not in {'upscale','optimize'} or (batch['library'] is not None and task['library']!=batch['library']):
                        raise ValueError('Task is not an eligible selected video result')
                    result=self.action(item['id'],'reject',item['version'])
                    if result['status']!='recommendation':raise ValueError('Result was not reset')
                    item.update(status='reset')
                except Exception as error:item.update(status='failed',error=str(error)[:250] if isinstance(error,ValueError) else 'Reset failed; inspect task')
                self._save_review_batch(batch,preserve_stop=True)
            else:batch['phase']='complete'
            self._save_review_batch(batch,preserve_stop=True)
        finally:
            with self.lock:self.active.discard(identity)
