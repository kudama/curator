import hashlib
import json
import random
import tempfile
import unittest
from pathlib import Path

from curator import folders, service
from curator.rules import ACTIVE, FILE_KINDS, RESERVING, reserves_source, stable_id
from curator.store import Store


class Rules(unittest.TestCase):
    def test_stable_id_matches_every_previous_formula(self):
        values = ('server', 'server:1', '42', 7, '/plex/a.mkv')
        old = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        self.assertEqual(stable_id(*values), old[:24])
        self.assertEqual(service.identifier(*values), old[:24])
        self.assertEqual(folders.key(*values), old[:24])
        # artwork_targets and artwork_archive hashed a list without sort_keys; same bytes.
        target = hashlib.sha256(json.dumps(['srv', 'srv:1', '42']).encode()).hexdigest()[:24]
        self.assertEqual(stable_id('srv', 'srv:1', '42'), target)
        archive = hashlib.sha256(json.dumps(['srv:1', '42']).encode()).hexdigest()[:12]
        self.assertEqual(stable_id('srv:1', '42', length=12), archive)
        nested = ({'b': 1, 'a': [2, {'d': 3, 'c': 4}]},)
        self.assertEqual(
            stable_id(*nested), hashlib.sha256(json.dumps(nested, sort_keys=True).encode()).hexdigest()[:24]
        )

    def test_status_sets(self):
        self.assertEqual(ACTIVE, {'queued', 'running', 'publishing'})
        self.assertEqual(RESERVING, ACTIVE | {'awaiting_review'})
        self.assertEqual(FILE_KINDS, {'rename', 'join', 'group'})

    def test_reserves_source(self):
        pending = dict(kind='join', status='awaiting_review', plan=dict(assets=['a', 'b']))
        self.assertTrue(reserves_source(pending, 'a'))
        self.assertFalse(reserves_source(pending, 'c'))
        self.assertFalse(reserves_source({**pending, 'status': 'applied'}, 'a'))
        self.assertFalse(reserves_source({**pending, 'kind': 'upscale'}, 'a'))


class Where(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'state'
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def fill(self, seed=1):
        rng = random.Random(seed)
        tasks = []
        with self.store.transaction():
            for number in range(300):
                task = dict(
                    id=f't{number}',
                    asset=f'a{rng.randint(0, 40)}',
                    library=rng.choice(['l1', 'l2']),
                    kind=rng.choice(['rename', 'join', 'upscale', 'metadata']),
                    status=rng.choice(
                        ['recommendation', 'queued', 'running', 'publishing', 'awaiting_review', 'applied']
                    ),
                    plan=dict(assets=[f'a{rng.randint(0, 40)}']),
                )
                tasks.append(task)
                self.store.put('tasks', task['id'], task)
            self.store.put('settings', 'paused', False)
            self.store.put('settings', 'order', [1, 2, 3])
            self.store.put('settings', 'note', 'text')
            self.store.put('settings', 'target', dict(id='target', record_type='artwork_target'))
            self.store.put('settings', 'other', dict(id='other', record_type='processing_run'))
        return tasks

    def check(self, tasks):
        cases = [
            dict(asset='a3'),
            dict(status='queued'),
            dict(kind=FILE_KINDS, status=RESERVING),
            dict(library='l2', status=ACTIVE),
            dict(kind=['upscale'], library=('l1',)),
            dict(),
        ]
        for filters in cases:
            expected = [
                t
                for t in tasks
                if all(t[f] in (v if isinstance(v, (set, frozenset, list, tuple)) else {v}) for f, v in filters.items())
            ]
            with self.subTest(filters=filters):
                self.assertEqual(self.store.where('tasks', **filters), expected)
        self.assertEqual(self.store.where('tasks', status=set()), [])
        self.assertEqual([row['id'] for row in self.store.where('settings', record_type='artwork_target')], ['target'])

    def test_matches_python_filtering_in_insertion_order(self):
        self.assertTrue(self.store.json_queries)
        self.check(self.fill())

    def test_fallback_without_json_functions_gives_the_same_rows(self):
        tasks = self.fill(2)
        self.store.json_queries = False
        self.check(tasks)

    def test_rejects_unsafe_fields_and_untyped_values(self):
        for filters in (
            dict(**{'status) OR 1=1 --': 'x'}),
            dict(status=None),
            dict(status=True),
            dict(status={'a': 1}),
        ):
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                self.store.where('tasks', **filters)
        with self.assertRaises(ValueError):
            self.store.where('not_a_table', status='queued')

    def test_hot_filters_use_indexes(self):
        self.fill()
        for sql, index in [
            ("SELECT data FROM tasks WHERE json_extract(data, '$.asset') = ?", 'tasks_asset'),
            (
                "SELECT data FROM assets WHERE json_extract(data, '$.library') = ? AND json_extract(data, '$.rating_key') = ?",
                'assets_library_rating_key',
            ),
            ("SELECT data FROM settings WHERE json_extract(data, '$.record_type') = ?", 'settings_record_type'),
        ]:
            plan = ' '.join(
                str(row) for row in self.store.db.execute('EXPLAIN QUERY PLAN ' + sql, ['x'] * sql.count('?'))
            )
            with self.subTest(index=index):
                self.assertIn(index, plan)

    def test_existing_state_gains_indexes_on_open(self):
        self.store.db.execute('DROP INDEX tasks_asset')
        self.store.db.commit()
        self.store.close()
        self.store = Store(self.path)
        names = {row[0] for row in self.store.db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertIn('tasks_asset', names)


if __name__ == '__main__':
    unittest.main()
