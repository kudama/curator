import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from curator.service import Service
from curator.store import Store


class UniversalQueue(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name));self.addCleanup(self.store.close)
        self.service=Service(self.store)
        with self.store.transaction():
            for key in ('one','two'):self.store.put('libraries',key,dict(id=key))
        self.gates={};self.seen=[];self.guard=threading.Lock()

    def add(self,key,library='one',kind='optimize',source=None):
        asset=dict(id=key,library=library,rating_key=key,local_path=source or '/synthetic/'+key,fingerprint={'size':1})
        task=dict(id=key,asset=key,library=library,kind=kind,status='queued',version=1,approval=1,source=asset['fingerprint'],plan={})
        with self.store.transaction():
            self.store.put('assets',key,asset);self.store.put('tasks',key,task)
        self.gates[key]=threading.Event()

    def wait(self,predicate):
        end=time.monotonic()+5
        while not predicate() and time.monotonic()<end:time.sleep(.01)
        self.assertTrue(predicate())

    def process(self,task,asset):
        with self.guard:self.seen.append(task['id'])
        self.gates[task['id']].wait(5)
        self.service._save(task,status='applied')

    def finish(self):
        self.service.pause_queues()
        for gate in self.gates.values():gate.set()
        self.wait(lambda:not self.service.queue_running())

    def running(self):return [t for t in self.store.all('tasks') if t['status']=='running']

    def test_global_two_encodes_and_one_upscale_and_pause_across_libraries(self):
        for key,lib,kind in [('a','one','optimize'),('b','two','optimize'),('c','two','optimize'),('u','two','upscale'),('v','one','upscale')]:self.add(key,lib,kind)
        self.service.set_queue_limits({'optimize':2,'upscale':1})
        with patch.object(self.service,'asset',side_effect=lambda task,**kw:self.store.get('assets',task['asset'])),patch.object(self.service,'_process',side_effect=self.process):
            try:
                self.service.start();self.wait(lambda:len(self.seen)==3)
                self.assertEqual(set(self.seen),{'a','b','u'})
                self.assertEqual(len(self.running()),3)
                self.service.pause_queues();self.gates['a'].set();self.gates['b'].set();self.gates['u'].set()
                self.wait(lambda:not self.service.queue_running())
                self.assertEqual(self.service.get_task('c')['status'],'queued');self.assertEqual(self.service.get_task('v')['status'],'queued')
                fresh=Service(self.store);self.assertFalse(fresh.queue_running());self.assertTrue(self.store.get('settings',fresh.pause_key(None,'optimize')))
            finally:self.finish()

    def test_lower_limit_does_not_replace_a_finished_slot_while_excess_job_runs(self):
        for key in ('a','b','c'):self.add(key)
        self.service.set_queue_limits({'optimize':2})
        with patch.object(self.service,'asset',side_effect=lambda task,**kw:self.store.get('assets',task['asset'])),patch.object(self.service,'_process',side_effect=self.process):
            try:
                self.service.start();self.wait(lambda:len(self.seen)==2);self.service.set_queue_limits({'optimize':1})
                self.gates['a'].set();self.wait(lambda:self.service.get_task('a')['status']=='applied')
                time.sleep(.3);self.assertEqual(self.service.get_task('c')['status'],'queued')
                self.gates['b'].set();self.wait(lambda:'c' in self.seen)
                self.assertEqual(len(self.running()),1)
            finally:self.finish()

    def test_same_source_head_waits_but_independent_job_can_start(self):
        self.add('u','one','upscale','/shared/video');self.add('blocked','two','optimize','/shared/video');self.add('free','two','optimize')
        with patch.object(self.service,'asset',side_effect=lambda task,**kw:self.store.get('assets',task['asset'])),patch.object(self.service,'_process',side_effect=self.process):
            try:
                self.service.start(None,'upscale');self.wait(lambda:'u' in self.seen)
                self.service.start(None,'optimize');self.wait(lambda:'free' in self.seen)
                self.assertNotIn('blocked',self.seen);self.assertEqual(self.service.get_task('blocked')['status'],'queued')
                self.gates['u'].set();self.gates['free'].set();self.wait(lambda:'blocked' in self.seen)
            finally:self.finish()

    def test_requeue_appends_after_existing_jobs_and_stale_global_snapshot_rejects(self):
        self.add('a');self.add('b','two');self.add('c')
        old=self.service.queue_snapshot(None);self.service.change_queue(None,old,order=['c','b','a'])
        with self.assertRaises(ValueError):self.service.change_queue(None,old,remove=['a'])
        self.service.change_queue(None,self.service.queue_snapshot(None),remove=['b'])
        task=self.service.get_task('b');task.update(status='queued')
        with self.store.transaction():self.store.put('tasks','b',task)
        self.assertEqual([t['id'] for t in self.service.waiting_tasks()],['c','a','b'])

    def test_limits_validate_without_boolean_or_unsupported_kind(self):
        for value in ({'optimize':True},{'optimize':0},{'optimize':9},{'arbitrary':1}):
            with self.assertRaises(ValueError):self.service.set_queue_limits(value)
        self.assertEqual(self.service.queue_limits(),{})

    def test_migration_preserves_saved_library_order_and_pause_without_replay(self):
        self.add('a');self.add('b','two');self.add('c')
        with self.store.transaction():
            for key,submitted in (('a','1'),('b','2'),('c','3')):
                task=self.service.get_task(key);task['queued_at']=submitted;self.store.put('tasks',key,task)
            self.store.db.execute("DELETE FROM settings WHERE id='queue-order:global'")
            self.store.put('settings','queue-order:one',{'ids':['c','a']})
            self.store.put('settings','queue-paused:two:optimize',True)
        fresh=Service(self.store)
        # The other library's head was submitted before the manually promoted c.
        self.assertEqual([t['id'] for t in fresh.waiting_tasks()],['b','c','a'])
        self.assertTrue(self.store.get('settings',fresh.pause_key(None,'optimize')));self.assertFalse(fresh.queue_running())
