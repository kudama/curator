"""folder_nodes groups files by directory; it must return exactly what the per-file walk did."""

import random
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from curator.folders import key
from curator.service import Service
from curator.store import Store


def per_file_folder_nodes(libraries, assets):
    """The previous implementation, kept verbatim as the oracle."""
    nodes = {}
    libraries = {row['id']: row for row in libraries}
    roots = {}
    for library in libraries.values():
        declared = [
            PurePosixPath(row['path'])
            for row in library.get('locations', [])
            if isinstance(row, dict)
            and isinstance(row.get('path'), str)
            and row['path'].startswith('/')
            and '..' not in PurePosixPath(row['path']).parts
        ]
        roots[library['id']] = declared or [PurePosixPath(m['plex_root']) for m in library['mappings']]
        for root in roots[library['id']]:
            fid = key(library['id'], str(root))
            mapped = any(root.is_relative_to(m['plex_root']) for m in library['mappings'])
            nodes.setdefault(
                fid,
                dict(
                    id=fid,
                    library=library['id'],
                    path=str(root),
                    name=root.name or str(root),
                    parent=None,
                    count=0,
                    direct_count=0,
                    mapped=mapped,
                ),
            )
    for asset in assets:
        if asset.get('present') is False:
            continue
        library = libraries.get(asset['library'])
        if not library:
            continue
        path = PurePosixPath(asset['plex_path']).parent
        matches = [root for root in roots[library['id']] if path.is_relative_to(root)]
        root = max(matches, key=lambda p: len(p.parts)) if matches else path
        for folder in [path, *path.parents]:
            if not folder.is_relative_to(root):
                break
            fid = key(library['id'], str(folder))
            mapped = any(folder.is_relative_to(m['plex_root']) for m in library['mappings'])
            row = nodes.setdefault(
                fid,
                dict(
                    id=fid,
                    library=library['id'],
                    path=str(folder),
                    name=folder.name or str(folder),
                    parent=key(library['id'], str(folder.parent)) if folder != root else None,
                    count=0,
                    direct_count=0,
                    mapped=mapped,
                ),
            )
            row['count'] += 1
            if folder == path:
                row['direct_count'] += 1
    return sorted(nodes.values(), key=lambda row: (row['library'], row['path']))


class FolderNodes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'state')
        self.service = Service(self.store, lambda *args: None)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def catalog(self, seed):
        rng = random.Random(seed)
        libraries = [
            dict(id='lib:a', mappings=[dict(plex_root='/media/movies', local_root='/x')]),
            dict(
                id='lib:b',
                mappings=[
                    dict(plex_root='/media/tv', local_root='/y'),
                    dict(plex_root='/media/tv/kids', local_root='/z'),
                ],
                locations=[dict(path='/media/tv'), dict(path='/media/tv/kids'), dict(path='/other/../bad'), 'junk'],
            ),
            dict(
                id='lib:c',
                mappings=[dict(plex_root='/srv/home', local_root='/w')],
                locations=[dict(path='/srv/home/video')],
            ),
        ]
        prefixes = ['/media/movies', '/media/tv', '/media/tv/kids', '/srv/home/video', '/srv/home', '/elsewhere', '/']
        assets = []
        for number in range(rng.randint(0, 250)):
            depth = rng.randint(0, 3)
            folder = rng.choice(prefixes).rstrip('/') + ''.join('/' + rng.choice('abcde') for _ in range(depth))
            assets.append(
                dict(
                    id=f'asset{number}',
                    library=rng.choice(['lib:a', 'lib:b', 'lib:c', 'lib:gone']),
                    plex_path=folder + f'/file{number}.mkv',
                    present=rng.choice([True, True, True, False, None]),
                )
            )
        return libraries, assets

    def test_matches_the_per_file_walk_on_random_catalogs(self):
        for seed in range(60):
            libraries, assets = self.catalog(seed)
            with self.subTest(seed=seed):
                self.assertEqual(self.service.folder_nodes(assets, libraries), per_file_folder_nodes(libraries, assets))

    def test_reads_the_store_when_rows_are_not_passed(self):
        libraries, assets = self.catalog(7)
        with self.store.transaction():
            for row in libraries:
                self.store.put('libraries', row['id'], row)
            for row in assets:
                self.store.put('assets', row['id'], row)
        self.assertEqual(self.service.folder_nodes(), per_file_folder_nodes(libraries, assets))

    def test_state_decodes_assets_and_libraries_once(self):
        libraries, assets = self.catalog(3)
        with self.store.transaction():
            for row in libraries:
                self.store.put('libraries', row['id'], row)
            for row in assets:
                self.store.put('assets', row['id'], row)
        reads = []
        original = self.store.all

        def counting(table):
            reads.append(table)
            return original(table)

        with patch.object(self.store, 'all', counting):
            state = self.service.state()
        self.assertEqual(reads.count('assets'), 1)
        self.assertEqual(reads.count('libraries'), 1)
        self.assertEqual(state['folders'], per_file_folder_nodes(libraries, assets))


if __name__ == '__main__':
    unittest.main()
