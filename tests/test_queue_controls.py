import unittest
from unittest.mock import patch
import test_curator


class QueueControls(unittest.TestCase):
    setUp=test_curator.Workflows.setUp
    tearDown=test_curator.Workflows.tearDown

    def queued(self):
        task=dict(self.task,status='queued',approval=1,source=self.asset['fingerprint'],plan={'changes':{'summary':'New'}})
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        return task

    def test_remove_waiting_job_preserves_plan_and_prevents_execution(self):
        task=self.queued();result=self.service.action(task['id'],'remove_queue',1)
        self.assertEqual(result['status'],'cancelled');self.assertNotIn('approval',result)
        self.assertEqual(result['plan'],task['plan']);self.service._execute(task['id']);self.assertEqual(self.plex.writes,[])
        self.assertTrue(self.file.exists())

    def test_delete_waiting_job_hides_task_and_preserves_output_and_receipts(self):
        task=self.queued();task.update(output=str(self.file),result={'verified':True})
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        result=self.service.action(task['id'],'delete',1)
        self.assertEqual(self.service.state()['tasks'],[]);self.assertTrue(self.file.exists())
        self.assertEqual(result['output'],str(self.file));self.assertTrue(result['result']['verified'])
        self.service._execute(task['id']);self.assertEqual(self.plex.writes,[])
        self.assertTrue(self.store.db.execute('SELECT COUNT(*) FROM events WHERE task=?',(task['id'],)).fetchone()[0])

    def test_undo_deleted_queued_task_does_not_restart_it(self):
        task=self.queued();deleted=self.service.action(task['id'],'delete',1)
        restored=self.service.action(task['id'],'restore_task',deleted['version'])
        self.assertEqual(restored['status'],'cancelled');self.assertNotIn('approval',restored)
        self.assertEqual(len(self.service.state()['tasks']),1)

    def test_stale_delete_or_remove_refused_after_worker_starts(self):
        task=self.queued();task['status']='running'
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        for action in ['delete','remove_queue']:
            with self.assertRaises(ValueError):self.service.action(task['id'],action,1)
        self.assertEqual(self.service.get_task(task['id'])['status'],'running')

    def test_running_encode_cancel_is_requested_without_pretending_it_stopped(self):
        task=dict(self.task,kind='optimize',status='running')
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        result=self.service.action(task['id'],'cancel',1)
        self.assertEqual(result['status'],'running');self.assertIn(task['id'],self.service.cancels)
        self.assertTrue(self.service.state()['tasks'][0]['cancel_requested'])

    def test_publication_cannot_be_deleted_or_interrupted(self):
        task=dict(self.task,status='publishing')
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        for action in ['delete','cancel','remove_queue']:
            with self.assertRaises(ValueError):self.service.action(task['id'],action,1)
        self.assertNotIn(task['id'],self.service.cancels)

    def test_deleted_recommendation_stays_dismissed_on_rescan(self):
        self.service.action(self.task['id'],'delete',1)
        with self.store.transaction():self.service.reconcile_findings(self.asset,[dict(kind='metadata',reason='Missing description')])
        self.assertEqual(self.service.state()['tasks'],[])
        reopened=self.service.metadata_task(self.asset['id'])
        self.assertFalse(reopened['deleted']);self.assertEqual(reopened['status'],'recommendation')

    def test_unavailable_media_does_not_prevent_deleting_its_task(self):
        self.file.unlink();self.service.action(self.task['id'],'delete',1)
        self.assertEqual(self.service.state()['tasks'],[])
        with self.assertRaises(ValueError):self.service.action(self.task['id'],'restore_task',1)

    def test_finished_job_cannot_be_marked_cancelled_by_late_click(self):
        task=dict(self.task,status='applied')
        with self.store.transaction():self.store.put('tasks',task['id'],task)
        with self.assertRaises(ValueError):self.service.action(task['id'],'cancel',1)
        self.assertEqual(self.service.get_task(task['id'])['status'],'applied')
