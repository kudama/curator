from pathlib import Path
import errno
import tempfile
import unittest
from unittest.mock import patch
from curator.store import Store
from curator.service import Service
from curator import tools


class BackupCleanup(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.media=self.root/'media';self.media.mkdir()
        self.source=self.media/'movie.mp4';self.backup=self.media/'movie-old.mp4'
        self.source.write_bytes(b'processed video');self.backup.write_bytes(b'original video')
        self.store=Store(self.root/'state');self.service=Service(self.store)
        self.task=dict(id='task',asset='asset',library='library',kind='upscale',status='applied',version=1,
                       published=True,plex_verified=True,original_renamed=True,archive=str(self.backup),
                       source_hash=tools.digest(self.backup),output_hash=tools.digest(self.source))
        with self.store.transaction():
            self.store.put('libraries','library',dict(id='library',mappings=[dict(plex_root='/media',local_root=str(self.media))]))
            self.store.put('assets','asset',dict(id='asset',library='library',local_path=str(self.source),plex_path='/media/movie.mp4',rating_key='one',title='Synthetic movie'))
            self.store.put('tasks','task',self.task)
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def preview(self):return self.service.cleanup_preview('library')
    def delete(self,preview):return self.service.delete_backups(preview['id'],['task'],1,'DELETE RETAINED ORIGINALS',background=False)
    def test_preview_is_read_only_and_exact_confirmation_is_required(self):
        preview=self.preview();self.assertEqual(len(preview['items']),1)
        self.assertTrue(self.backup.exists())
        with self.assertRaises(ValueError):self.service.delete_backups(preview['id'],['task'],1,'yes',background=False)
        self.assertTrue(self.backup.exists());self.assertEqual(self.source.read_bytes(),b'processed video')

    def test_cleanup_is_visible_without_claiming_the_video_queue(self):
        preview=self.preview();self.assertEqual(self.service.cleanup_jobs(),[])
        preview.update(phase='deleting',selected=['task'],current={'title':'Synthetic movie','phase':'Verifying'})
        with self.store.transaction():self.store.put('settings',preview['id'],preview)
        self.service.active.add(preview['id'])
        self.assertFalse(self.service.queue_running())
        with self.store.transaction():self.store.put('tasks','waiting',dict(id='waiting',library='library',kind='metadata',status='queued',version=1))
        with patch('curator.service.threading.Thread') as worker:
            self.service.start('library');worker.return_value.start.assert_called_once()
        self.assertTrue(self.service.queue_running())
        job=self.service.cleanup_jobs()[0]
        self.assertEqual((job['total'],job['completed'],job['current']['title']),(1,0,'Synthetic movie'))
        self.assertNotIn('items',job)

    def test_cleanup_reserves_same_source_but_allows_unrelated_source(self):
        task=dict(self.task,cleanup_in_progress=True)
        with self.store.transaction():self.store.put('tasks','task',task)
        with self.assertRaises(ValueError):self.service.check_busy_sources(dict(id='other',asset='asset'))
        with self.store.transaction():self.store.put('assets','unrelated',dict(id='unrelated',library='library',local_path=str(self.media/'other.mp4'),rating_key='two'))
        self.service.check_busy_sources(dict(id='other',asset='unrelated'))
    def test_deletes_only_receipt_backed_original_and_audits_outcome(self):
        unrelated=self.media/'other-old.mp4';unrelated.write_bytes(b'keep')
        result=self.delete(self.preview());self.assertEqual(result['items'][0]['status'],'deleted')
        self.assertFalse(self.backup.exists());self.assertTrue(unrelated.exists());self.assertEqual(self.source.read_bytes(),b'processed video')
        task=self.service.get_task('task');self.assertTrue(task['archive_deleted']);self.assertIsNone(task['cleanup_pending'])
        with self.assertRaises(ValueError):self.delete(result)

    def test_nas_without_exclusive_rename_uses_verified_recovery_copy(self):
        with patch('curator.backup_cleanup.exclusive_move',side_effect=OSError(errno.ENOTSUP,'Not supported')):
            result=self.delete(self.preview())
        self.assertEqual(result['items'][0]['status'],'deleted')
        self.assertFalse(self.backup.exists());self.assertEqual(self.source.read_bytes(),b'processed video')
        self.assertFalse(list(self.media.glob('.curator-cleanup-*')))

    def test_nas_recovery_copy_failure_keeps_original_and_staging(self):
        with patch('curator.backup_cleanup.exclusive_move',side_effect=OSError(errno.ENOTSUP,'Not supported')),patch('curator.backup_cleanup.shutil.copyfileobj',side_effect=OSError('Copy interrupted')):
            result=self.delete(self.preview())
        self.assertEqual(result['items'][0]['status'],'failed')
        self.assertEqual(self.backup.read_bytes(),b'original video')
        self.assertEqual(self.source.read_bytes(),b'processed video')
        self.assertTrue(self.service.get_task('task')['cleanup_pending'])
    def test_changed_source_or_backup_is_preserved(self):
        for which in ('source','backup'):
            with self.subTest(which=which):
                self.source.write_bytes(b'processed video');self.backup.write_bytes(b'original video')
                preview=self.preview();getattr(self,which).write_bytes(b'changed by another program')
                result=self.delete(preview);self.assertEqual(result['items'][0]['status'],'failed');self.assertTrue(self.backup.exists())
    def test_symlinks_unverified_publications_and_active_work_are_not_candidates(self):
        self.backup.unlink();self.backup.symlink_to(self.source);self.assertEqual(self.preview()['items'],[])
        self.backup.unlink();self.backup.write_bytes(b'original video')
        with self.store.transaction():
            self.store.put('tasks','running',dict(id='running',asset='asset',library='library',status='queued'))
        self.assertEqual(self.preview()['items'],[])
    def test_failed_verification_retains_staged_file_and_can_restore_without_overwrite(self):
        original_digest=tools.digest
        def digest(path):return 'f'*64 if Path(path).name.startswith('.curator-cleanup-') else original_digest(path)
        preview=self.preview()
        with patch('curator.backup_cleanup.tools.digest',side_effect=digest):result=self.delete(preview)
        self.assertEqual(result['items'][0]['status'],'failed');task=self.service.get_task('task')
        self.assertTrue(task['cleanup_in_progress']);self.assertTrue(Path(task['cleanup_pending']['staged']).exists())
        self.service.restore_cleanup_backup('task');self.assertEqual(self.backup.read_bytes(),b'original video')
        self.assertEqual(self.source.read_bytes(),b'processed video')
    def test_interrupted_cleanup_is_not_replayed(self):
        receipt=self.preview();receipt['phase']='deleting'
        with self.store.transaction():self.store.put('settings',receipt['id'],receipt)
        self.service.recover_backup_cleanups()
        self.assertEqual(self.service.cleanup_receipt(receipt['id'])['phase'],'interrupted');self.assertTrue(self.backup.exists())

    def test_restore_collision_preserves_both_originals_and_recovery_marker(self):
        stage=self.media/'.curator-cleanup-collision.mp4'
        self.backup.rename(stage)
        self.backup.write_bytes(b'new external file')
        task=self.service.get_task('task')
        pending=dict(original=str(self.backup),staged=str(stage),receipt='fixture')
        with self.store.transaction():
            self.store.put('tasks','task',dict(task,cleanup_pending=pending,cleanup_in_progress=True))
        with self.assertRaises(OSError):
            self.service.restore_cleanup_backup('task')
        self.assertEqual(self.backup.read_bytes(),b'new external file')
        self.assertEqual(stage.read_bytes(),b'original video')
        self.assertEqual(self.source.read_bytes(),b'processed video')
        self.assertEqual(self.service.get_task('task')['cleanup_pending'],pending)
