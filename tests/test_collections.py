import unittest
from unittest.mock import Mock

import test_curator
from curator.plex import Plex, PlexError


class Catalog(unittest.TestCase):
    def client(self, *pages):
        client = Plex('http://plex.test:32400', 'fixture-token')
        client.request = Mock(side_effect=list(pages))
        return client

    def test_collection_catalog_includes_smart_and_preserves_names(self):
        client = self.client({'Metadata': [
            {'ratingKey': '2', 'title': 'Summer, 2024', 'smart': 0},
            {'ratingKey': '1', 'title': 'Favorites', 'smart': '1'}]})
        rows = client.metadata_choices({'key': '15'}, 'collection')
        self.assertEqual([r['title'] for r in rows], ['Favorites', 'Summer, 2024'])
        self.assertTrue(rows[0]['smart'])
        self.assertFalse(rows[1]['smart'])
        self.assertEqual(client.request.call_args.args, ('/library/sections/15/collections',))

    def test_category_catalog_is_scoped_and_preserves_punctuation(self):
        for field in ('genre', 'label'):
            with self.subTest(field=field):
                client = self.client({'Directory': [{'key': '8', 'title': 'Travel, outdoors'},
                                                    {'key': '9', 'title': 'Family'}]})
                rows = client.metadata_choices({'key': '3'}, field)
                self.assertEqual([r['title'] for r in rows], ['Family', 'Travel, outdoors'])
                self.assertEqual(client.request.call_args.args, ('/library/sections/3/' + field,))

    def test_pagination_for_both_catalog_shapes(self):
        for field, shape, identity in [('collection', 'Metadata', 'ratingKey'), ('genre', 'Directory', 'key')]:
            client = self.client({shape: [{identity: '1', 'title': 'First'}], 'totalSize': 2},
                                 {shape: [{identity: '2', 'title': 'Second'}], 'totalSize': 2})
            self.assertEqual(len(client.metadata_choices({'key': '3'}, field)), 2)
            self.assertEqual(client.request.call_args.kwargs['params']['X-Plex-Container-Start'], 1)

    def test_incomplete_or_repeating_pages_are_errors(self):
        for field, shape, identity in [('collection', 'Metadata', 'ratingKey'), ('genre', 'Directory', 'key')]:
            page = {shape: [{identity: '1', 'title': 'First'}], 'totalSize': 2}
            for second in ({shape: [], 'totalSize': 2}, page):
                client = self.client(page, second)
                with self.assertRaises(PlexError):
                    client.metadata_choices({'key': '3'}, field)

    def test_empty_catalog_and_invalid_field(self):
        client = self.client({})
        self.assertEqual(client.metadata_choices({'key': '3'}, 'label'), [])
        with self.assertRaisesRegex(PlexError, 'Unsupported'):
            client.metadata_choices({'key': '3'}, '../all')
        self.assertEqual(client.request.call_count, 1)


class MetadataChoices(unittest.TestCase):
    setUp = test_curator.Workflows.setUp
    tearDown = test_curator.Workflows.tearDown

    def test_lookup_is_read_only_and_uses_selected_library(self):
        self.plex.metadata_choices = Mock(return_value=[{'title': 'Travel'}])
        self.assertEqual(self.service.library_metadata_choices(self.asset['library'], 'genre'),
                         {'choices': [{'title': 'Travel'}]})
        self.assertEqual(self.plex.metadata_choices.call_args.args[0]['id'], self.asset['library'])
        self.assertEqual(self.plex.writes, [])

    def test_invalid_field_never_calls_plex(self):
        self.plex.metadata_choices = Mock()
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            self.service.library_metadata_choices(self.asset['library'], 'actor')
        self.plex.metadata_choices.assert_not_called()
