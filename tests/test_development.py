"""DEV/TEST cannot accidentally reuse production state, providers or media roots."""

import http.cookiejar
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.request import build_opener, HTTPCookieProcessor

from curator import development
from curator.artwork_archive import archive_root
from curator.errors import UserError
from curator.mage import Mage
from curator.mage_mcp import MagePricing
from curator.paths import map_path
from curator.plex import Plex
from curator.service import Service
from curator.store import Store
from curator.web import App


class Development(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sandbox = Path(self.temp.name).resolve() / 'sandbox'
        self.state = self.sandbox / 'state'
        self.env = patch.dict(os.environ)
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop(development.VARIABLE, None)

    def enable(self):
        development.configure(self.sandbox, self.state)

    def test_refuses_production_broad_roots_and_unmarked_existing_state(self):
        for root, state in [(Path.home(), self.state), (self.sandbox, Path(self.temp.name) / 'outside')]:
            with self.subTest(root=root), self.assertRaises(UserError):
                development.configure(root, state)
        self.state.mkdir(parents=True)
        database = self.state / 'curator.sqlite3'
        database.write_bytes(b'keep existing data')
        with self.assertRaises(UserError):
            self.enable()
        self.assertEqual(database.read_bytes(), b'keep existing data')
        self.assertFalse((self.state / 'development-profile').exists())
        self.assertIsNone(development.root())

    def test_profile_reopens_but_rejects_changed_marker(self):
        self.enable()
        self.enable()
        (self.state / 'development-profile').write_text('wrong sandbox')
        with self.assertRaises(UserError):
            self.enable()

    def test_paths_and_symlink_escape_rejected_before_writing(self):
        self.enable()
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (outside / 'film.mp4').write_bytes(b'original')
        (self.sandbox / 'escape').symlink_to(outside, target_is_directory=True)
        for local in [outside, self.sandbox / 'escape']:
            with self.subTest(local=local), self.assertRaisesRegex(UserError, 'sandbox'):
                map_path('/media/film.mp4', [dict(plex_root='/media', local_root=str(local))])
        with self.assertRaises(UserError):
            archive_root(str(outside), check_write=True)
        self.assertEqual(list(outside.iterdir()), [outside / 'film.mp4'])
        self.assertEqual(development.check_path(self.state), self.state)

    def test_all_provider_entry_points_fail_before_transport_or_key_write(self):
        self.enable()
        transport = Mock(side_effect=AssertionError('network must not run'))
        mage = Mage(self.state, opener=transport)
        operations = [
            lambda: Plex('http://example.test', 'test', transport),
            lambda: mage.save_key('test'),
            lambda: mage.get('/account'),
            lambda: mage._job_request('POST', '/mango/generate', {}),
            lambda: mage.download('https://mage.space/image.png'),
            lambda: MagePricing('test', transport).rpc('initialize', {}),
        ]
        store = Store(self.state)
        self.addCleanup(store.close)
        service = Service(store)
        operations += [lambda: service._home({}, {}), lambda: service.save_config({'plex_token': 'test'})]
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaisesRegex(UserError, 'disabled'):
                operation()
        self.assertFalse(mage.key_path.exists())
        transport.assert_not_called()
        with self.assertRaises(UserError):
            service.save_config({'archive_root': str(Path(self.temp.name))})
        self.assertEqual(service.config(), {})

    def test_launcher_uses_distinct_label_and_root_without_creating_state(self):
        from test_foundry_deployment import foundry

        properties = foundry.make_properties(
            Path('/tmp/checkout'),
            self.state,
            8791,
            '/usr/bin/python3',
            label='com.curator.foundry.dev',
            development_root=self.sandbox,
        )
        self.assertEqual(properties['Label'], 'com.curator.foundry.dev')
        self.assertIn('--development-root', properties['ProgramArguments'])
        self.assertFalse(self.state.exists())
        self.assertIsNone(development.root())
        with self.assertRaises(ValueError):
            foundry.make_properties(Path('/tmp/checkout'), self.state, 8791, 'python', development_root=self.sandbox)
        with self.assertRaises(ValueError):
            foundry.make_properties(Path('/tmp/checkout'), self.state, 8791, 'python', label='../bad')

    def test_same_host_production_and_development_sessions_coexist(self):
        production_store = Store(Path(self.temp.name) / 'production-fixture')
        self.addCleanup(production_store.close)
        production = App(('127.0.0.1', 0), Service(production_store))
        self.addCleanup(production.server_close)
        self.enable()
        dev_store = Store(self.state)
        self.addCleanup(dev_store.close)
        dev = App(('127.0.0.1', 0), Service(dev_store))
        self.addCleanup(dev.server_close)
        for server in [production, dev]:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
        browser = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        prod_url = f'http://127.0.0.1:{production.server_port}'
        dev_url = f'http://127.0.0.1:{dev.server_port}'
        with browser.open(prod_url) as response:
            self.assertNotIn(b'development-banner', response.read())
        with browser.open(dev_url) as response:
            self.assertIn(b'DEV / TEST', response.read())
        for base, environment in [(prod_url, 'production'), (dev_url, 'development')]:
            with browser.open(base + '/api/service/status') as response:
                self.assertEqual(json.load(response)['environment'], environment)
        self.assertNotEqual(production.session_cookie, dev.session_cookie)
