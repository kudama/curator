"""Combined #107/#118 adapter acceptance: synthetic facts, no standing grant."""

import unittest

from curator.errors import UserError
from curator.maintenance_facts import evaluated, finding_for
import test_standard_evaluation as standards_fixtures


class CanonicalMaintenanceFacts(unittest.TestCase):
    setUp = standards_fixtures.ScanIntegration.setUp
    tearDown = standards_fixtures.ScanIntegration.tearDown

    def source(self):
        return standards_fixtures.asset(id=self.asset['id'], library=self.lib['id'], title='Synthetic adapter source')

    def test_current_global_threshold_and_library_override_drive_action_facts(self):
        source = self.source()
        self.assertIsNone(finding_for('prepare_encode', evaluated(self.service, source)))
        config = self.service.config()
        config['max_mbps_1080'] = 1
        with self.store.transaction():
            self.store.put('settings', 'config', config)
        facts = evaluated(self.service, source)
        finding = finding_for('prepare_encode', facts)
        self.assertEqual(finding['kind'], 'optimize')
        self.assertEqual(finding['evidence']['standard'], facts['standard'])
        self.assertEqual(facts['completion']['dimensions']['encoding']['state'], 'needs_attention')
        self.service.save_library_overrides(self.lib['id'], 0, {'encoding': {'enabled': False}})
        disabled = evaluated(self.service, source)
        self.assertNotEqual(disabled['standard'], facts['standard'])
        self.assertIsNone(finding_for('process_encode', disabled))
        self.assertFalse(self.plex.writes)
        self.assertFalse(self.service.queue_running())

    def test_unknown_canonical_facts_cannot_fall_back_to_existing_recommendations(self):
        source = self.source()
        source['technical'] = {}
        with self.store.transaction():
            self.service.task(self.asset, dict(kind='optimize', reason='Historical recommendation'))
        before = self.store.all('tasks')
        with self.assertRaisesRegex(UserError, 'unknown, stale or inconsistent'):
            evaluated(self.service, source)
        self.assertEqual(self.store.all('tasks'), before)
        self.assertFalse(self.plex.writes)
