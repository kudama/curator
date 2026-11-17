import tempfile
import threading
import unittest
from curator.bulk_review import BulkReviewWorkflows
from curator.store import Store


class Workflow(BulkReviewWorkflows):
    def __init__(self,store):
        self.store=store;self.lock=threading.RLock();self.active=set();self.compared=[];self.published=[]
        self.tasks={str(i):dict(id=str(i),library='library',version=1,kind='upscale',status='awaiting_review') for i in range(3)}
    def get_task(self,key):return dict(self.tasks[key])
    def comparison(self,key):self.compared.append(key);self.tasks[key]['comparison_loaded']=True
    def review(self,key,version,mode,background=False):
        assert not background
        if not self.tasks[key].get('comparison_loaded'):raise ValueError('Comparison required')
        self.published.append(key);self.tasks[key]['status']='applied';return self.tasks[key]


class ReviewBatches(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name);self.service=Workflow(self.store)
        self.refs=[{'id':str(i),'version':1} for i in range(3)]
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def test_preparation_never_publishes_and_confirmation_count_is_exact(self):
        batch=self.service.prepare_review_batch('library',self.refs,background=False)
        self.assertEqual(batch['phase'],'ready');self.assertEqual(self.service.published,[])
        with self.assertRaises(ValueError):self.service.publish_review_batch(batch['id'],2,background=False)
        batch=self.service.publish_review_batch(batch['id'],3,background=False)
        self.assertEqual(self.service.published,['0','1','2']);self.assertEqual(batch['phase'],'complete')
        with self.assertRaises(ValueError):self.service.publish_review_batch(batch['id'],3,background=False)
    def test_changed_and_wrong_library_tasks_fail_without_blocking_other_results(self):
        self.service.tasks['0']['version']=2;self.service.tasks['1']['library']='other'
        batch=self.service.prepare_review_batch('library',self.refs,background=False)
        self.assertEqual([i['status'] for i in batch['items']],['failed','failed','prepared'])
        self.assertEqual(self.service.compared,['2'])
    def test_stop_request_during_current_file_is_preserved(self):
        original=self.service.comparison
        def stop(key):
            original(key);identity=next(iter(self.service.active));self.service.stop_review_batch(identity)
        self.service.comparison=stop
        batch=self.service.prepare_review_batch('library',self.refs,background=False)
        self.assertEqual(batch['phase'],'stopped');self.assertEqual(self.service.compared,['0'])
        self.assertEqual(self.service.published,[])
    def test_interrupted_batches_are_not_replayed_and_non_dict_settings_survive(self):
        with self.store.transaction():
            self.store.put('settings','unrelated',True)
            self.store.put('settings','review-batch:test',{'id':'review-batch:test','record_type':'review_batch','phase':'publishing','items':[]})
        self.service.recover_review_batches()
        self.assertEqual(self.service.review_batch('review-batch:test')['phase'],'interrupted')
        self.assertEqual(self.service.published,[]);self.assertTrue(self.store.get('settings','unrelated'))
    def test_changed_result_is_revalidated_before_publication(self):
        batch=self.service.prepare_review_batch('library',self.refs,background=False)
        self.service.tasks['1']['version']=2
        batch=self.service.publish_review_batch(batch['id'],3,background=False)
        self.assertEqual(self.service.published,['0','2']);self.assertEqual(batch['items'][1]['status'],'failed')
