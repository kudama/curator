import tempfile
import unittest
from curator.service import Service
from curator.store import Store


class ReviewPosition(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name);self.addCleanup(self.store.close);self.service=Service(self.store)
        with self.store.transaction():
            for key in ('one','two'):self.store.put('libraries',key,{'id':key})
            for i in range(3):self.store.put('tasks',str(i),dict(id=str(i),asset='asset',library='one' if i<2 else 'two',kind='upscale' if i<2 else 'optimize',status='awaiting_review',version=1,updated=str(i),plan={}))

    def test_accept_requires_actual_task_action_and_saved_cursor_survives_resume(self):
        session=self.service.open_review_session()
        with self.assertRaises(ValueError):self.service.step_review_session(session['id'],1,'0','accepted')
        with self.store.transaction():
            task=self.service.get_task('0');task['status']='publishing';self.store.put('tasks','0',task)
        session=self.service.step_review_session(session['id'],1,'0','accepted')
        self.assertEqual(session['cursor'],1);self.assertEqual(session['items'][0]['outcome'],'publishing')
        fresh=Service(self.store);resumed=fresh.open_review_session(session['id']);self.assertEqual(resumed['cursor'],1);self.assertFalse(fresh.queue_running())
        with self.assertRaises(ValueError):fresh.step_review_session(session['id'],1,'0','accepted')

    def test_reject_and_skip_have_distinct_decisions_and_skip_leaves_result_pending(self):
        session=self.service.open_review_session();self.service.action('0','reject',1)
        session=self.service.step_review_session(session['id'],1,'0','rejected')
        session=self.service.step_review_session(session['id'],session['version'],'1','skipped')
        self.assertEqual(session['cursor'],2);self.assertEqual([i['decision'] for i in session['items']],['rejected','skipped','pending'])
        self.assertEqual(self.service.get_task('1')['status'],'awaiting_review')
        self.assertIn('1',[i['id'] for i in self.service.open_review_session()['items']])

    def test_read_reconciles_changed_items_without_writing_or_replaying_actions(self):
        session=self.service.open_review_session()
        with self.store.transaction():
            task=self.service.get_task('0');task.update(version=2,status='recommendation');self.store.put('tasks','0',task)
            task=self.service.get_task('1');task.update(status='applied');self.store.put('tasks','1',task)
        observed=self.service.review_session(session['id'])
        self.assertEqual(observed['cursor'],2);self.assertEqual(self.store.get('settings',session['id'])['cursor'],0)
        stepped=self.service.step_review_session(session['id'],1,'2','skipped')
        self.assertTrue(stepped['complete']);self.assertEqual([i['decision'] for i in stepped['items']],['unavailable','accepted','skipped'])

    def test_session_respects_library_kind_and_exact_search_selection(self):
        session=self.service.open_review_session(library='one',kind='upscale',refs=[{'id':'1','version':1},{'id':'2','version':1}])
        self.assertEqual([i['id'] for i in session['items']],['1'])
        with self.assertRaises(ValueError):self.service.open_review_session(refs=[{'id':'0','version':1}]*2)
        with self.assertRaises(ValueError):self.service.open_review_session(kind='join')
