"""Scan bookkeeping must not grow as assets x tasks (it was ~10 s at 1,400 assets)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from curator.service import Service, identifier
from curator.store import Store


class Catalog:
    def __init__(self, items, during=None):
        self.rows, self.during = items, during

    def items(self, library):
        for number, item in enumerate(self.rows):
            if self.during and number == len(self.rows) // 2:
                self.during()
            yield item


class ScanScale(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'state')
        self.library = dict(
            id='srv:1',
            server='srv',
            key='1',
            title='Movies',
            type='movie',
            profile='commercial',
            mappings=[dict(plex_root='/plex', local_root='/local')],
            themes=[],
        )
        with self.store.transaction():
            self.store.put('libraries', self.library['id'], self.library)
            self.store.put(
                'settings',
                'defaults',
                dict(
                    record='folder_defaults',
                    library='srv:1',
                    folder='/plex/d0',
                    recursive=False,
                    revision=1,
                    fields={},
                    artwork={},
                    mode='fill',
                    branding=None,
                ),
            )

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def items(self, count):
        return [
            dict(
                ratingKey=str(n),
                title=f'Film {n}',
                summary='' if n % 2 else 'Known',
                thumb='t',
                Media=[dict(Part=[dict(id=n, file=f'/plex/d{n % 3}/film{n}.mkv')])],
            )
            for n in range(count)
        ]

    def scan(self, service):
        service.scan_status[self.library['id']] = dict(running=True, count=0)
        with (
            patch('curator.service.media_presence', return_value={'state': 'present'}),
            patch('curator.service.map_path', side_effect=lambda file, mappings: Path(file)),
            patch('curator.service.tools.fingerprint', return_value={'size': 1}),
            patch('curator.service.tools.probe', return_value={}),
            patch('curator.service.assess', return_value=[dict(kind='upscale', reason='Low resolution', evidence={})]),
            patch.object(Service, '_folder_changes', lambda self, item, defaults: (None, {'summary': 'x'}, {})),
        ):
            service._scan(self.library)
        self.assertIsNone(service.scan_status[self.library['id']].get('error'))

    def full_reads(self, count):
        """Number of whole-table reads of tasks and settings made by one rescan of `count` files."""
        service = Service(self.store, lambda *args: Catalog(self.items(count)))
        self.scan(service)
        reads = []
        original = self.store.all

        def counting(table):
            reads.append(table)
            return original(table)

        with patch.object(self.store, 'all', counting):
            self.scan(service)
        return reads.count('tasks'), reads.count('settings')

    def test_full_table_reads_do_not_grow_with_the_library(self):
        small = self.full_reads(5)
        large = self.full_reads(60)
        self.assertEqual(small, large)
        self.assertLessEqual(large[0], 3)

    def test_rescan_produces_the_same_tasks_as_per_file_reads(self):
        service = Service(self.store, lambda *args: Catalog(self.items(12)))
        self.scan(service)
        tasks = {(t['asset'], t['kind'], t['status']) for t in self.store.all('tasks')}
        kinds = {kind for _, kind, _ in tasks}
        self.assertEqual(kinds, {'upscale', 'metadata', 'folder_metadata'})
        self.scan(service)
        self.assertEqual({(t['asset'], t['kind'], t['status']) for t in self.store.all('tasks')}, tasks)

    def test_change_made_during_a_scan_is_not_overwritten(self):
        items = self.items(10)
        service = Service(self.store, lambda *args: Catalog(items))
        self.scan(service)
        last = identifier(
            'srv',
            '1',
            items[-1]['ratingKey'],
            items[-1]['Media'][0]['Part'][0]['id'],
            items[-1]['Media'][0]['Part'][0]['file'],
        )
        target = self.store.get('tasks', identifier(last, 'upscale'))

        def approve_midway():
            with self.store.transaction():
                row = self.store.get('tasks', target['id'])
                row.update(reason='Changed by the reviewer', marker=True)
                self.store.put('tasks', row['id'], row)

        service.plex_factory = lambda *args: Catalog(items, during=approve_midway)
        self.scan(service)
        self.assertTrue(self.store.get('tasks', target['id']).get('marker'))

    def test_task_created_during_a_scan_is_reconciled(self):
        items = self.items(4)
        service = Service(self.store, lambda *args: Catalog(items))
        self.scan(service)
        asset = self.store.get('assets', identifier('srv', '1', '3', 3, '/plex/d0/film3.mkv'))

        def add_stale_finding():
            with self.store.transaction():
                service.task(asset, dict(kind='inspect', reason='Old probe failure'))

        # Created after the scan indexed tasks; the next scan still resolves it.
        service.plex_factory = lambda *args: Catalog(items, during=add_stale_finding)
        self.scan(service)
        service.plex_factory = lambda *args: Catalog(items)
        self.scan(service)
        self.assertEqual(self.store.get('tasks', identifier(asset['id'], 'inspect'))['status'], 'resolved')


if __name__ == '__main__':
    unittest.main()
