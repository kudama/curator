"""Retry only transient reads before any processing or external write starts."""
import errno
import time
from .store import now
from .errors import UserError


class RecoveryWorkflows:
    def schedule_preflight_retry(self,task,error,side_effects_started):
        transient=isinstance(error,TimeoutError) or isinstance(error,OSError) and error.errno in {errno.EAGAIN,errno.ETIMEDOUT,errno.ECONNRESET,errno.ENETUNREACH,errno.EHOSTUNREACH,errno.EBUSY}
        attempts=task.get('preflight_retry_count',0)
        if side_effects_started or not transient or attempts>=2 or task['kind']=='mage_generation' or task['id'] in self.cancels:return False
        delay=5*(3**attempts)
        self._save(task,status='queued',preflight_retry_count=attempts+1,retry_at=time.time()+delay,error='Temporary source access problem; retry '+str(attempts+1)+' of 2 in '+str(delay)+' seconds')
        with self.store.transaction():self.store.event(task['id'],dict(action='preflight retry scheduled',attempt=attempts+1,delay_seconds=delay))
        return True

    @staticmethod
    def safe_failed_retry(task):
        return task['status'] in {'blocked','failed'} and task['kind'] in {'upscale','optimize','home','metadata'} and not task.get('deleted') and not any(task.get(k) for k in ('output','published','publication_error','rename_started','file_move_pending','cleanup_pending','provider'))

    @staticmethod
    def recovery_hint(task):
        if task.get('cleanup_pending'):return 'Inspect retained-original cleanup and use Restore retained original where offered.'
        if task.get('published'):return 'Inspect publication and Plex verification; do not re-encode an uncertain installation.'
        if task.get('rename_started'):return 'Inspect the rename receipt and restore original filenames where offered.'
        if task.get('output') and not task.get('validation') and task.get('source_hash') and task.get('output_hash'):return 'A validated output is retained. Return it to review without re-encoding.'
        if task.get('output'):return 'An output is retained. Inspect validation and choose whether to reprocess.'
        return 'Inspect the cause, then explicitly retry with a fresh source/settings check.'

    def retry_failed_results(self,refs):
        if not isinstance(refs,list) or not 1<=len(refs)<=5000 or any(not isinstance(r,dict) or set(r)!={'id','version'} or not isinstance(r['id'],str) or type(r['version']) is not int for r in refs) or len({r['id'] for r in refs})!=len(refs):raise UserError('Select unique failed jobs with current versions')
        results=[]
        for ref in refs:
            try:
                task=self.get_task(ref['id'])
                if not self.safe_failed_retry(task):raise UserError('Inspect the retained output or uncertain operation before retrying')
                self.action(ref['id'],'queue',ref['version']);results.append(dict(id=ref['id'],status='queued'))
            except (ValueError,OSError):results.append(dict(id=ref['id'],status='failed',error='Task changed, source/settings unavailable, or manual recovery required'))
        return dict(items=results,queued=sum(r['status']=='queued' for r in results),started=False,updated=now())
