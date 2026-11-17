import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from curator.service import Service,SourceBusy
from curator.store import Store


class TaskTypeQueues(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name));self.addCleanup(self.store.close);self.service=Service(self.store)
        with self.store.transaction():
            for lib in ('one','two'):self.store.put('libraries',lib,dict(id=lib))
            for key,kind,lib in [('u1','upscale','one'),('u2','upscale','one'),('o1','optimize','one'),('o2','optimize','one'),('other','upscale','two')]:
                self.store.put('tasks',key,dict(id=key,asset=key,kind=kind,library=lib,status='queued',version=1,approval=1))

    def wait(self,predicate):
        end=time.monotonic()+5
        while not predicate() and time.monotonic()<end:time.sleep(.01)
        self.assertTrue(predicate())

    def test_one_each_concurrent_pause_drains_current_and_resume_is_separate(self):
        gate=threading.Event();started={kind:threading.Event() for kind in ('upscale','optimize')};seen=[];guard=threading.Lock()
        def execute(key,**kwargs):
            with self.store.transaction():
                task=self.service.get_task(key);task['status']='running';self.store.put('tasks',key,task)
            self.assertEqual(kwargs.get('queue_kind'),task['kind'])
            self.assertTrue(kwargs.get('queue_head'))
            with guard:seen.append(key)
            started[task['kind']].set();gate.wait(5)
            with self.store.transaction():task['status']='applied';self.store.put('tasks',key,task)
        with patch.object(self.service,'_execute',side_effect=execute):
            try:
                self.service.start('one')
                self.assertTrue(started['upscale'].wait(3));self.assertTrue(started['optimize'].wait(3))
                self.assertEqual(set(seen),{'u1','o1'})
                self.assertEqual(self.service.start('two','upscale')['busy'],['upscale'])
                self.service.pause_queues('one');self.assertEqual(self.service.cancels,set())
                gate.set();self.wait(lambda:not self.service.queue_running())
                self.assertEqual(self.service.get_task('u2')['status'],'queued');self.assertEqual(self.service.get_task('o2')['status'],'queued')
                fresh=Service(self.store);self.assertFalse(fresh.queue_running())
                self.assertTrue(self.store.get('settings',fresh.pause_key('one','upscale')))
                self.service.start('one','upscale');self.wait(lambda:self.service.get_task('u2')['status']=='applied')
                self.assertEqual(self.service.get_task('o2')['status'],'queued')
            finally:
                gate.set();self.wait(lambda:not self.service.queue_running())

    def test_pause_committed_before_claim_leaves_job_waiting(self):
        self.service.pause_queues('one','upscale')
        with patch.object(self.service,'asset',side_effect=AssertionError('Must not claim')):
            self.service._execute('u1',queue_head=True,queue_kind='upscale')
        self.assertEqual(self.service.get_task('u1')['status'],'queued')

    def test_same_source_conflict_waits_without_failing_or_cancelling(self):
        with patch.object(self.service,'check_busy_sources',side_effect=SourceBusy('Reserved')):
            result=self.service._execute('u1',queue_head=True,queue_kind='upscale')
        self.assertEqual(result,'source_busy');self.assertEqual(self.service.get_task('u1')['status'],'queued')

    def test_old_worker_cleanup_cannot_remove_its_resumed_replacement(self):
        old=threading.Event();new=threading.Event()
        self.service.queue_workers['upscale']={new:dict(library='one',wake=new)};self.service.active.add('queue:upscale')
        self.service._release_queue_worker('one','upscale',old)
        self.assertIn(new,self.service.queue_workers['upscale'])
        self.assertTrue(self.service.queue_running())

    def test_repeated_cleanup_does_not_reopen_the_store_after_worker_is_released(self):
        wake=threading.Event();self.service.queue_workers['upscale']={wake:dict(library=None,wake=wake)}
        self.service.active.add('queue:upscale');self.service._release_queue_worker(None,'upscale',wake)
        with patch.object(self.store,'transaction',side_effect=AssertionError('Released worker must not use a closing store')):
            self.service._release_queue_worker(None,'upscale',wake)
