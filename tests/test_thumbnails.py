import unittest
from unittest.mock import patch
import test_curator


class Thumbnails(unittest.TestCase):
    setUp=test_curator.Workflows.setUp
    tearDown=test_curator.Workflows.tearDown

    def test_browsing_artwork_does_not_create_tasks_or_probe_media(self):
        self.plex.image=lambda key,kind:b'\x89PNG\r\n\x1a\nfixture'
        before=self.store.all('tasks')
        with patch('curator.service.tools.probe') as probe:
            image=self.service.asset_thumbnail(self.asset['id'])
        self.assertTrue(image.startswith(b'\x89PNG'));probe.assert_not_called()
        self.assertEqual(self.store.all('tasks'),before);self.assertEqual(self.plex.writes,[])

    def test_repeated_polls_use_bounded_cache_and_new_art_invalidates_key(self):
        calls=[]
        self.plex.image=lambda key,kind:calls.append(key) or b'\x89PNG\r\n\x1a\nfixture'
        self.service.asset_thumbnail(self.asset['id']);self.service.asset_thumbnail(self.asset['id'])
        self.assertEqual(len(calls),1)
        with self.store.transaction():self.store.put('assets',self.asset['id'],{**self.asset,'item':{**self.asset['item'],'thumb':'/new-cover'}})
        self.service.asset_thumbnail(self.asset['id']);self.assertEqual(len(calls),2)

    def test_absent_asset_cannot_fetch_provider_art(self):
        with self.store.transaction():self.store.put('assets',self.asset['id'],{**self.asset,'present':False})
        with patch.object(self.service,'checked_client') as client:
            with self.assertRaises(ValueError):self.service.asset_thumbnail(self.asset['id'])
        client.assert_not_called()
