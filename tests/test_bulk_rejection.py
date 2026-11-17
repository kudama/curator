import tempfile
import unittest
from pathlib import Path
from curator.service import Service
from curator.store import Store


class ResetResults(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name);self.addCleanup(self.store.close);self.service=Service(self.store)
        self.original=Path(self.temp.name)/'source.mp4';self.output=Path(self.temp.name)/'output.mp4'
        self.original.write_bytes(b'original');self.output.write_bytes(b'processed')
        with self.store.transaction():
            for i in range(4):self.store.put('tasks',str(i),dict(id=str(i),library='one' if i%2 else 'two',asset='asset',kind='optimize',version=1,status='awaiting_review',approval=1,comparison_loaded=True,output=str(self.output),output_hash='a'*64,source_hash='b'*64,plan={'handbrake_preset':'Saved preset'}))

    def test_single_reset_preserves_files_plan_and_audit_but_invalidates_result(self):
        result=self.service.action('0','reject',1)
        self.assertEqual(result['status'],'recommendation');self.assertEqual(result['version'],2)
        self.assertEqual(result['plan']['handbrake_preset'],'Saved preset')
        for key in ('approval','comparison_loaded','output_hash','source_hash','output'):self.assertNotIn(key,result)
        self.assertEqual(self.original.read_bytes(),b'original');self.assertEqual(self.output.read_bytes(),b'processed')
        self.assertTrue(any('result rejected and retained' in row[0] for row in self.store.db.execute('SELECT data FROM events')))
        with self.assertRaises(ValueError):self.service.action('0','reject',1)

    def test_bulk_reset_handles_stale_and_published_items_without_touching_them(self):
        with self.store.transaction():
            task=self.service.get_task('1');task['version']=2;self.store.put('tasks','1',task)
            task=self.service.get_task('2');task['published']=True;self.store.put('tasks','2',task)
        refs=[{'id':str(i),'version':1} for i in range(4)]
        batch=self.service.reject_selected_results(None,refs,4,background=False)
        self.assertEqual([item['status'] for item in batch['items']],['reset','failed','failed','reset'])
        for key in ('1','2'):self.assertEqual(self.service.get_task(key)['status'],'awaiting_review')
        for key in ('0','3'):self.assertEqual(self.service.get_task(key)['status'],'recommendation')
        self.assertEqual(self.output.read_bytes(),b'processed')

    def test_empty_duplicate_or_wrong_count_is_not_a_reset(self):
        for refs,count in (([],0),([{'id':'0','version':1}]*2,2),([{'id':'0','version':1}],2)):
            with self.assertRaises(ValueError):self.service.reject_selected_results(None,refs,count,background=False)
        self.assertEqual(self.service.get_task('0')['status'],'awaiting_review')
