import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from curator.service import Service
from curator.store import Store


class QueueOrder(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name));self.addCleanup(lambda:self.store.close())
        self.service=Service(self.store)
        with self.store.transaction():
            self.store.put('libraries','one',dict(id='one'))
            for key in ('a','b','c'):
                self.store.put('tasks',key,dict(id=key,library='one',status='queued',version=1,approval=1,kind='upscale'))
            self.store.put('tasks','running',dict(id='running',library='one',status='running',version=1,kind='upscale'))
            self.store.put('tasks','other',dict(id='other',library='two',status='queued',version=1,kind='upscale'))

    def snapshot(self):return self.service.queue_snapshot('one')

    def test_order_is_saved_and_reloaded(self):
        self.service.change_queue('one',self.snapshot(),order=['c','a','b'])
        self.assertEqual([r['id'] for r in self.snapshot()],['c','a','b'])
        fresh=Service(self.store)
        self.assertEqual([r['id'] for r in fresh.queue_snapshot('one')],['c','a','b'])

    def test_stale_snapshot_and_nonwaiting_or_cross_library_ids_are_rejected(self):
        old=self.snapshot();self.service.change_queue('one',old,order=['b','a','c'])
        with self.assertRaises(ValueError):self.service.change_queue('one',old,remove=['a'])
        for ids in (['running'],['other']):
            with self.assertRaises(ValueError):self.service.change_queue('one',self.snapshot(),remove=ids)
        with self.assertRaises(ValueError):self.service.change_queue('one',self.snapshot(),order=['a','a','b'])

    def test_empty_waiting_queue_retains_tasks_media_and_running_work(self):
        sentinel=Path(self.temp.name)/'video.mp4';sentinel.write_bytes(b'keep')
        self.service.change_queue('one',self.snapshot(),remove=['a','b','c'])
        self.assertEqual(self.snapshot(),[])
        for key in ('a','b','c'):
            task=self.service.get_task(key);self.assertEqual(task['status'],'cancelled');self.assertEqual(task['version'],2);self.assertNotIn('approval',task)
        self.assertEqual(self.service.get_task('running')['status'],'running')
        self.assertEqual(self.service.get_task('other')['status'],'queued')
        self.assertEqual(sentinel.read_bytes(),b'keep')

    def test_runner_reads_new_order_between_jobs(self):
        seen=[]
        def execute(key,queue_head=False):
            self.assertTrue(queue_head);seen.append(key)
            with self.store.transaction():
                task=self.service.get_task(key);task['status']='applied';self.store.put('tasks',key,task)
            if key=='a':self.service.change_queue('one',self.snapshot(),order=['c','b'])
        with patch.object(self.service,'_execute',side_effect=execute):self.service._run('one')
        self.assertEqual(seen,['a','c','b'])

    def test_reorder_before_claim_prevents_old_head_from_starting(self):
        self.service.change_queue('one',self.snapshot(),order=['b','a','c'])
        with patch.object(self.service,'asset',side_effect=AssertionError('Must not execute old head')):
            self.service._execute('a',queue_head=True)
        self.assertEqual(self.service.get_task('a')['status'],'queued')
