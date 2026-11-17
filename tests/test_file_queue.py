import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from curator.service import Service
from curator.store import Store


class FileOperations(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name));self.addCleanup(self.store.close);self.service=Service(self.store)
        with self.store.transaction():
            for i in range(8):self.store.put('tasks',str(i),dict(id=str(i),library='one' if i%2 else 'two',title='Synthetic file',status='applied',version=1))
        self.release=threading.Event();self.seen=[];self.lock=threading.Lock()
        self.addCleanup(self.finish)

    def wait(self,predicate):
        end=time.monotonic()+5
        while not predicate() and time.monotonic()<end:time.sleep(.01)
        self.assertTrue(predicate())

    def finish(self):
        self.release.set();self.wait(lambda:not self.service.file_workers)

    def operation(self,job):
        with self.lock:self.seen.append(job['payload']['task'])
        self.release.wait(5)

    def test_all_entry_points_share_at_most_four_running_operations_and_pause_drains(self):
        with patch.object(self.service,'_execute_file_operation',side_effect=self.operation):
            try:
                for i,operation in enumerate(['publish','repair','restore_cleanup','file_task','restore_rename','repair']):
                    self.service.queue_file_operation(operation,{'task':str(i)},background=True)
                self.wait(lambda:len(self.seen)==4)
                self.assertEqual(set(self.seen),{'0','1','2','3'})
                self.assertEqual(sum(j['phase']=='running' for j in self.service.file_jobs()),4)
                self.service.pause_queues();self.release.set();self.wait(lambda:not self.service.file_workers)
                self.assertEqual([j['payload']['task'] for j in self.service.file_jobs() if j['phase']=='waiting'],['4','5'])
                self.service.start();self.wait(lambda:len(self.seen)==6);self.wait(lambda:not self.service.file_workers)
            finally:self.finish()

    def test_queued_and_uncertain_operations_are_held_after_restart(self):
        with self.store.transaction():
            self.store.put('settings','waiting',dict(id='waiting',record_type='file_operation',operation='repair',payload={'task':'0'},phase='waiting',created='one'))
            self.store.put('settings','running',dict(id='running',record_type='file_operation',operation='repair',payload={'task':'1'},phase='running',created='two'))
        fresh=Service(self.store)
        self.assertFalse(fresh.file_workers)
        self.assertEqual({j['phase'] for j in fresh.file_jobs()},{'interrupted'})

    def test_file_limit_cannot_exceed_four_and_sync_operation_finishes_before_store_close(self):
        for value in (0,5,True):
            with self.assertRaises(ValueError):self.service.set_queue_limits({'file_operations':value})
        self.service.set_queue_limits({'file_operations':1})
        with patch.object(self.service,'_execute_file_operation'):
            result=self.service.queue_file_operation('repair',{'task':'0'})
        self.assertEqual(result['id'],'0');self.assertEqual(self.service.file_workers,{})

    def test_last_worker_cleanup_does_not_remove_a_new_worker(self):
        old=threading.Event();new=threading.Event();self.service.file_workers[new]=True;self.service.active.add('file-queue')
        self.service._release_file_worker(old);self.assertIn(new,self.service.file_workers)
        self.service._release_file_worker(new)
