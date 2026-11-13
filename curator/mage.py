"""Optional, read-only Mage capability discovery. Generation remains fail-closed.

The documented catalog price covers the architecture's default settings, not a
quote for an arbitrary Mango variant. Never use discovery as spending consent.
"""
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener

BASE = 'https://api.mage.space/v1'
DEFAULT_MODEL = 'mango-v3'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Mage:
    def __init__(self, root, opener=None):
        self.key_path = Path(root) / 'mage-api-key'
        self.opener = opener or build_opener(NoRedirect())

    def save_key(self, key):
        if not isinstance(key, str) or len(key) > 1000 or any(c.isspace() for c in key):
            raise ValueError('Enter a valid Mage API key without whitespace')
        if self.key_path.is_symlink():
            raise ValueError('Mage key storage cannot be a symlink')
        if not key:
            self.key_path.unlink(missing_ok=True)
            return
        fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as out:
            os.fchmod(out.fileno(), 0o600)
            out.write(key)
            out.flush()
            os.fsync(out.fileno())

    def configured(self):
        return self.key_path.is_file() and not self.key_path.is_symlink()

    def get(self, path):
        if path not in {'/architectures', '/account'}:
            raise ValueError('Unsupported Mage discovery endpoint')
        if not self.configured():
            raise ValueError('Configure a Mage API key first')
        key = self.key_path.read_text().strip()
        request = Request(BASE + path, headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'})
        try:
            with self.opener.open(request, timeout=20) as response:
                data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise ValueError('Mage discovery response is too large')
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError('Invalid Mage discovery response')
            return value
        except HTTPError as error:
            error.close()
            # Do not echo provider bodies, headers, tokens or redirect URLs.
            if error.code == 401:
                raise ValueError('Mage API key was refused') from None
            if error.code == 429:
                raise ValueError('Mage rate limit reached; retry discovery later') from None
            raise ValueError('Mage discovery failed (HTTP ' + str(error.code) + ')') from None
        except (OSError, URLError, json.JSONDecodeError):
            raise ValueError('Mage is unavailable or returned an invalid response') from None

    def discover(self):
        catalog = self.get('/architectures')
        mango = next((r for r in catalog.get('architectures', []) if isinstance(r, dict) and r.get('id') == 'mango'), None)
        if not mango:
            raise ValueError('Mage no longer advertises the Mango architecture')
        properties = mango.get('input_schema', {}).get('properties', {})
        models = properties.get('model_id', {}).get('enum', [])
        if not isinstance(models, list) or not all(isinstance(v, str) for v in models):
            raise ValueError('Mage returned invalid model options')
        balance = None
        balance_status = 'unavailable'
        try:
            value = self.get('/account').get('gems', {}).get('balance')
            if type(value) in (int, float) and value >= 0:
                balance, balance_status = value, 'available'
        except ValueError:
            pass  # Balance is optional; discovery and manual artwork remain usable.
        return dict(models=models, default_model=DEFAULT_MODEL if DEFAULT_MODEL in models else None,
                    options=mango.get('options', {}), options_by_model=mango.get('options_by_model', {}),
                    balance=balance, balance_status=balance_status, generation_enabled=False,
                    reason='Paid submission is unavailable until a reliable price for the selected configuration can be shown before charging. Manual prompt and image import remain available.')
