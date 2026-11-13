import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

from curator.mage import Mage, NoRedirect


class MageDiscovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.opener = Mock()
        self.mage = Mage(self.tmp.name, self.opener)
        self.mage.save_key('synthetic-test-key')

    def responses(self, *values):
        self.opener.open.side_effect = [io.BytesIO(json.dumps(v).encode()) for v in values]

    def catalog(self):
        return {'architectures': [{'id': 'mango', 'input_schema': {'properties': {
            'model_id': {'enum': ['mango-v3', 'mango-v4']}}},
            'options_by_model': {'mango-v3': {'resolution': ['1K','2K']}}}]}

    def test_discovery_is_read_only_and_returns_live_models_and_optional_balance(self):
        self.responses(self.catalog(), {'gems': {'balance': 123}})
        result = self.mage.discover()
        self.assertEqual(result['default_model'], 'mango-v3')
        self.assertEqual(result['balance'], 123)
        self.assertFalse(result['generation_enabled'])
        self.assertNotIn('synthetic-test-key', json.dumps(result))
        for call in self.opener.open.call_args_list:
            request = call.args[0]
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(request.host, 'api.mage.space')
            self.assertIsNone(request.data)

    def test_missing_mango3_never_silently_switches_to_provider_default(self):
        catalog = self.catalog();catalog['architectures'][0]['input_schema']['properties']['model_id']['enum']=['mango-v4']
        self.responses(catalog, {'gems': {'balance': 0}})
        self.assertIsNone(self.mage.discover()['default_model'])

    def test_optional_balance_failure_does_not_break_manual_workflow(self):
        self.opener.open.side_effect=[io.BytesIO(json.dumps(self.catalog()).encode()), URLError('offline')]
        self.assertEqual(self.mage.discover()['balance_status'], 'unavailable')

    def test_http_errors_do_not_expose_key_or_provider_body(self):
        for code, message in [(401, 'refused'),(429, 'rate limit'),(500, 'HTTP 500'),(302, 'HTTP 302')]:
            self.opener.open.side_effect=HTTPError('https://api.mage.space',code,'secret-provider-body',{},None)
            with self.assertRaisesRegex(ValueError, message) as context:
                self.mage.get('/account')
            self.assertNotIn('secret', str(context.exception))

    def test_timeout_and_invalid_json_are_recoverable(self):
        for response in [TimeoutError('private information'), io.BytesIO(b'invalid')]:
            self.opener.open.side_effect=None
            if isinstance(response, Exception):self.opener.open.side_effect=response
            else:self.opener.open.return_value=response
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                self.mage.get('/account')

    def test_redirects_never_forward_bearer_credential(self):
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://elsewhere.invalid'))

    def test_private_key_storage_delete_and_symlink_refusal(self):
        path=Path(self.tmp.name)/'mage-api-key'
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.mage.save_key('');self.assertFalse(self.mage.configured())
        other=Path(self.tmp.name)/'other';other.write_text('untouched');path.symlink_to(other)
        with self.assertRaisesRegex(ValueError, 'symlink'):self.mage.save_key('new-key')
        self.assertEqual(other.read_text(), 'untouched')

    def test_unknown_endpoint_and_absent_key_make_no_network_request(self):
        self.mage.save_key('')
        for path in ['/account','/mango/generate','https://other.invalid']:
            with self.assertRaises(ValueError):self.mage.get(path)
        self.opener.open.assert_not_called()
