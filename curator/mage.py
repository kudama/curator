"""Optional Mage adapter; generation requires an exact supported price and consent.

Catalog-default Gems never price a different model or reference configuration.
"""

from . import development

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener

from .logs import register_secret
from .errors import UserError

BASE = 'https://api.mage.space/v1'
DEFAULT_MODEL = 'mango-v3'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Mage:
    def __init__(self, root, opener=None):
        self.key_path = Path(root) / 'mage-api-key'
        self.opener = opener or build_opener(NoRedirect())
        self._job_credential = None

    def save_key(self, key):
        development.block_external()
        self._job_credential = None
        if not isinstance(key, str) or len(key) > 1000 or any(c.isspace() for c in key):
            raise UserError('Enter a valid Mage API key without whitespace')
        if self.key_path.is_symlink():
            raise UserError('Mage key storage cannot be a symlink')
        if not key:
            self.key_path.unlink(missing_ok=True)
            return
        register_secret(key)
        fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as out:
            os.fchmod(out.fileno(), 0o600)
            out.write(key)
            out.flush()
            os.fsync(out.fileno())

    def configured(self):
        return self.key_path.is_file() and not self.key_path.is_symlink()

    def register_key_secret(self):
        """Keep a stored key out of the diagnostic log; never fails startup."""
        try:
            if self.configured():
                register_secret(self.key_path.read_text().strip())
        except (OSError, UnicodeError):
            pass

    def get(self, path):
        development.block_external()
        if path not in {'/architectures', '/account'}:
            raise UserError('Unsupported Mage discovery endpoint')
        if not self.configured():
            raise UserError('Configure a Mage API key first')
        key = self.key_path.read_text().strip()
        request = Request(BASE + path, headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'})
        try:
            with self.opener.open(request, timeout=20) as response:
                data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise UserError('Mage discovery response is too large')
            value = json.loads(data)
            if not isinstance(value, dict):
                raise UserError('Invalid Mage discovery response')
            return value
        except HTTPError as error:
            error.close()
            # Do not echo provider bodies, headers, tokens or redirect URLs.
            if error.code == 401:
                raise UserError('Mage API key was refused') from None
            if error.code == 429:
                raise UserError('Mage rate limit reached; retry discovery later') from None
            raise UserError('Mage discovery failed (HTTP ' + str(error.code) + ')') from None
        except (OSError, URLError, json.JSONDecodeError):
            raise UserError('Mage is unavailable or returned an invalid response') from None

    def discover(self):
        catalog = self.get('/architectures')
        from .mage_catalog import models

        catalog_models = models(catalog)
        mango = next(
            (r for r in catalog.get('architectures', []) if isinstance(r, dict) and r.get('id') == 'mango'), {}
        )
        model_ids = [r['id'] for r in catalog_models]
        balance = None
        balance_status = 'unavailable'
        try:
            value = self.get('/account').get('gems', {}).get('balance')
            if type(value) in (int, float) and __import__('math').isfinite(value) and value >= 0:
                balance, balance_status = value, 'available'
        except ValueError:
            pass  # Balance is optional; discovery and manual artwork remain usable.
        return dict(
            models=model_ids,
            model_catalog=catalog_models,
            default_model=DEFAULT_MODEL if DEFAULT_MODEL in model_ids else None,
            options=mango.get('options', {}),
            options_by_model=mango.get('options_by_model', {}),
            balance=balance,
            balance_status=balance_status,
            generation_enabled=False,
            reason='Paid generation requires a saved plan, usable pre-submit estimate and explicit consent. Exact catalog defaults use catalog pricing. Other configurations require a usable request-specific MCP estimate; unsupported schemas stay blocked.',
        )

    def _job_request(self, method, path, body=None, idempotency_key=None):
        development.block_external()
        import re

        allowed = (
            method == 'POST'
            and re.fullmatch(r'/[a-z][a-z0-9_-]{0,60}/generate', path)
            or re.fullmatch(r'/requests/[a-f0-9-]{36}/' + ('status' if method == 'GET' else 'cancel'), path)
        )
        if not allowed or method not in {'GET', 'POST'}:
            raise UserError('Unsupported Mage job operation')
        if not self.configured():
            raise UserError('Configure a Mage API key first')
        headers = {'Authorization': 'Bearer ' + self.job_credential(), 'Content-Type': 'application/json'}
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key
        request = Request(
            BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None, headers=headers
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise UserError('Mage job response too large')
            value = json.loads(data)
            if not isinstance(value, dict):
                raise UserError('Invalid Mage job response')
            return value
        except HTTPError as error:
            code = error.code
            error.close()
            raise UserError('Mage job HTTP ' + str(code) + '; inspect request state before retrying') from None
        except (OSError, URLError, json.JSONDecodeError):
            raise UserError('Mage job outcome is uncertain; resume with the same saved request identity') from None

    def job_credential(self):
        if self._job_credential is None:
            if not self.configured():
                raise UserError('Configure a Mage API key first')
            self._job_credential = self.key_path.read_text().strip()
        return self._job_credential

    def credential_identity(self):
        import hashlib

        if not self.configured():
            raise UserError('Configure a Mage API key first')
        return hashlib.sha256(self.job_credential().encode()).hexdigest()

    def quote(self, settings, references=0, reference_images=None):
        catalog = self.get('/architectures')
        from .mage_catalog import resolve, request_body

        mango, row = resolve(catalog, settings['model'])
        if references:
            if not isinstance(reference_images, list) or len(reference_images) != references:
                raise UserError('No verified pre-submit price without the exact reference images')
            if any(not isinstance(image, str) or len(image) > 4 * 1024 * 1024 for image in reference_images):
                raise UserError('Mage pricing references must be at most 3 MiB each')
        properties = mango.get('input_schema', {}).get('properties', {})
        body = request_body(mango, row, settings, reference_images or [])
        defaults = dict(mango.get('base_config', {}))
        for field, value in properties.items():
            if isinstance(value, dict) and 'default' in value:
                defaults.setdefault(field, value['default'])
        # The only documented pre-submit price is for exact architecture defaults.
        # Never apply it to Mango 3 merely because Mango 4 is the API default.
        if (
            references
            or '@' in settings['prompt']
            or any(defaults.get(field) != value for field, value in body.items() if field != 'prompt')
        ):
            from .mage_mcp import MagePricing

            pricing = MagePricing(self.job_credential(), self.opener)
            return pricing.quote(body) if row['architecture'] == 'mango' else pricing.quote(body, row['architecture'])
        gems = mango.get('gems')
        if type(gems) not in (int, float) or gems < 0 or not __import__('math').isfinite(gems):
            raise UserError('Mage has no usable pre-submit price')
        return {
            'gems': gems,
            'body': body,
            **({'architecture': row['architecture']} if row['architecture'] != 'mango' else {}),
            'basis': 'Live catalog price for exact architecture defaults; estimate, not a provider-enforced spend cap',
        }

    def _retry_job(self, method, path, body=None, key=None):
        import time

        for attempt in range(3):
            try:
                return self._job_request(method, path, body, key)
            except ValueError as error:
                transient = 'outcome is uncertain' in str(error) or any(
                    'HTTP ' + str(code) in str(error) for code in (408, 429, 500, 502, 503, 504)
                )
                # Submission retries always carry the original persisted idempotency key.
                if attempt == 2 or not transient:
                    raise
                time.sleep(2**attempt)

    def submit(self, body, key, architecture='mango'):
        import re

        if not isinstance(architecture, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,60}', architecture):
            raise UserError('Invalid Mage image architecture')
        return self._retry_job('POST', '/' + architecture + '/generate', body, key)

    def status(self, request_id):
        return self._retry_job('GET', '/requests/' + request_id + '/status')

    def cancel(self, request_id):
        return self._retry_job('POST', '/requests/' + request_id + '/cancel', {})

    def download(self, url):
        development.block_external()
        from urllib.parse import urlsplit

        parsed = urlsplit(url)
        if (
            parsed.scheme != 'https'
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or not parsed.hostname
            or not (parsed.hostname == 'mage.space' or parsed.hostname.endswith('.mage.space'))
        ):
            raise UserError('Unverified Mage result host; retained request identity is available for manual recovery')
        try:
            # No API authorization header on asset downloads, and no redirects.
            with self.opener.open(
                Request(url, headers={'User-Agent': 'Curator/0.5.0', 'Accept': 'image/png,image/jpeg'}), timeout=30
            ) as response:
                data = response.read(10 * 1024 * 1024 + 1)
            if len(data) > 10 * 1024 * 1024 or not data.startswith((b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff')):
                raise UserError('Mage result is not a supported JPEG/PNG under 10 MiB')
            return data
        except (OSError, URLError):
            raise UserError('Mage result download failed; request retained for recovery') from None
