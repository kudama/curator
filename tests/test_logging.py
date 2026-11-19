import logging
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from curator.logs import configure, log, redact, register_secret
from curator.service import Service
from curator.store import Store
from tests.test_curator import FakePlex


class PrivateLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = (list(log.handlers), log.level, log.propagate)

    def tearDown(self):
        for handler in list(log.handlers):
            if getattr(handler, 'curator_private', False):
                log.removeHandler(handler)
                handler.close()
        log.handlers[:], log.level, log.propagate = self.saved
        self.tmp.cleanup()

    def mode(self, path):
        return stat.S_IMODE(os.stat(path).st_mode)

    def test_log_is_private_and_records_tracebacks(self):
        path = configure(self.root)
        try:
            raise OSError(5, 'Input/output error')
        except OSError:
            log.exception('Library scan failed')
        text = path.read_text()
        self.assertIn('Library scan failed', text)
        self.assertIn('Traceback', text)
        self.assertIn('Input/output error', text)
        self.assertEqual(self.mode(path.parent), 0o700)
        self.assertEqual(self.mode(path), 0o600)
        self.assertFalse(log.propagate)

    def test_rotated_logs_stay_private(self):
        path = configure(self.root, max_bytes=200, backups=2)
        for number in range(40):
            log.info('line %s %s', number, 'x' * 40)
        rotated = sorted(path.parent.glob('curator.log*'))
        self.assertGreater(len(rotated), 1)
        self.assertTrue(all(self.mode(file) == 0o600 for file in rotated))

    def test_symlinked_log_is_refused(self):
        (self.root / 'logs').mkdir()
        (self.root / 'logs' / 'curator.log').symlink_to(self.root / 'elsewhere.log')
        with self.assertRaises(OSError):
            configure(self.root)
        self.assertFalse((self.root / 'elsewhere.log').exists())

    def test_reconfiguring_replaces_the_previous_file_handler(self):
        configure(self.root)
        configure(self.root)
        self.assertEqual(sum(getattr(h, 'curator_private', False) for h in log.handlers), 1)

    def test_secrets_are_redacted_including_in_tracebacks(self):
        register_secret('plex-secret-token-123')
        path = configure(self.root)
        try:
            raise ValueError('GET http://plex:32400/library?X-Plex-Token=abcdef123456 failed with plex-secret-token-123')
        except ValueError:
            log.exception('Request failed; Authorization: Bearer mage-key-987654 api_key=zzz999999')
        text = path.read_text()
        for secret in ('plex-secret-token-123', 'abcdef123456', 'mage-key-987654', 'zzz999999'):
            self.assertNotIn(secret, text)
        self.assertIn('[redacted]', text)

    def test_short_or_empty_values_are_not_registered(self):
        register_secret('')
        register_secret('abc')
        register_secret(None)
        self.assertEqual(redact('abc and a normal sentence'), 'abc and a normal sentence')

    def test_without_configuration_nothing_reaches_stderr(self):
        with patch.object(logging, 'lastResort') as last_resort:
            log.error('not configured')
        last_resort.handle.assert_not_called()


class ServiceLogging(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'state')

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_attributes_exist_before_startup_recoveries_run(self):
        seen = {}

        def recover(service):
            seen.update(cancels=service.cancels, scan=service.scan_status, presence=service.presence_status,
                        locks=service.task_locks, thumbnails=service.thumbnail_cache)
        with patch.object(Service, 'recover_file_jobs', recover):
            Service(self.store, lambda *args: FakePlex())
        self.assertEqual(seen, dict(cancels=set(), scan={}, presence={}, locks={}, thumbnails={}))

    def test_configured_plex_token_is_redacted(self):
        with self.store.transaction():
            self.store.put('settings', 'config', {'plex_token': 'stored-plex-token-42'})
        Service(self.store, lambda *args: FakePlex())
        self.assertNotIn('stored-plex-token-42', redact('token stored-plex-token-42 leaked'))

    def test_saved_mage_key_is_redacted(self):
        from curator.mage import Mage
        Mage(self.store.root).save_key('mage-saved-key-77')
        self.assertNotIn('mage-saved-key-77', redact('key mage-saved-key-77'))

    def test_scan_failure_keeps_generic_message_and_logs_the_cause(self):
        plex = FakePlex()

        def broken(library):
            raise RuntimeError('XML parse error at line 3')
        plex.items = broken
        service = Service(self.store, lambda *args: plex)
        library = dict(id='server:1', server='server', key='1', title='Movies', type='movie',
                       profile='commercial', mappings=[], themes=[])
        with self.store.transaction():
            self.store.put('libraries', library['id'], library)
        service.scan_status[library['id']] = {}
        with self.assertLogs('curator', 'ERROR') as captured:
            service._scan(library)
        self.assertEqual(service.scan_status[library['id']]['error'], 'Scan failed; check Plex configuration and permissions')
        self.assertIn('XML parse error', '\n'.join(captured.output))


if __name__ == '__main__':
    unittest.main()
