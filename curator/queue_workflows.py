"""Persist waiting-job order with atomic stale-view checks."""
from .store import now


class QueueWorkflows:
    def recover_removed_queue_tasks(self):
        marker='queue-removal-suggestions-v1'
        with self.store.transaction():
            if self.store.get('settings',marker):return 0
            actions=self.store.latest_task_actions();count=0
            for task in self.store.all('tasks'):
                if task.get('deleted') or task['status']!='cancelled' or actions.get(task['id']) not in {'remove_queue','remove from waiting queue'}:continue
                task.update(status='recommendation',version=task['version']+1,updated=now(),error=None)
                task.pop('approval',None)
                self.store.put('tasks',task['id'],task)
                self.store.event(task['id'],dict(action='removed queue task returned to suggestions'))
                count+=1
            self.store.put('settings',marker,dict(recovered=count,updated=now()))
        return count

    def waiting_tasks(self, library, tasks=None):
        rows=[t for t in (self.store.all('tasks') if tasks is None else tasks)
              if t['library']==library and t['status']=='queued' and not t.get('deleted')]
        order=self.store.get('settings','queue-order:'+library,{}).get('ids',[])
        positions={key:index for index,key in enumerate(order)}
        return sorted(rows,key=lambda t:positions.get(t['id'],len(order)))

    def queue_snapshot(self, library, tasks=None):
        return [dict(id=t['id'],version=t['version']) for t in self.waiting_tasks(library,tasks)]

    def change_queue(self, library, expected, order=None, remove=None):
        self.library(library)
        if not isinstance(expected,list) or len(expected)>20000 or any(not isinstance(r,dict) or set(r)!={'id','version'} or not isinstance(r['id'],str) or type(r['version']) is not int for r in expected):
            raise ValueError('Refresh the waiting queue before changing it')
        values=order if order is not None else remove
        if (order is None)==(remove is None) or not isinstance(values,list) or any(not isinstance(k,str) for k in values) or len(values)!=len(set(values)):
            raise ValueError('Choose one valid waiting-queue action')
        with self.store.transaction():
            waiting=self.waiting_tasks(library)
            if expected!=[dict(id=t['id'],version=t['version']) for t in waiting]:
                raise ValueError('Waiting queue changed; refresh and try again')
            ids=[t['id'] for t in waiting]
            if order is not None:
                if set(order)!=set(ids):raise ValueError('Reorder only the current waiting jobs')
                result=order
            else:
                if not remove or not set(remove)<=set(ids):raise ValueError('Remove only current waiting jobs')
                removed=set(remove);result=[key for key in ids if key not in removed]
                for task in waiting:
                    if task['id'] not in removed:continue
                    task.update(status='recommendation',version=task['version']+1,updated=now(),error=None)
                    task.pop('approval',None)
                    self.store.put('tasks',task['id'],task)
                    self.store.event(task['id'],dict(action='remove from waiting queue'))
            self.store.put('settings','queue-order:'+library,dict(ids=result,updated=now()))
        return dict(waiting=len(result),removed=len(remove or []))
