"""Bounded view-only Seerr client. No live connection is configured by this module."""

import http.cookiejar
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPCookieProcessor
from datetime import datetime
from . import development
from .errors import UserError
from .logs import register_secret

REQUEST_VIEW = 16384
MAX_RESULTS = 5000


class SeerrError(UserError):
    def __init__(self, state, message, http_status=None):
        super().__init__(message)
        self.state = state
        self.http_status = http_status


class NoSeerrRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if fp is not None:
            fp.close()
        raise SeerrError('incompatible', 'Seerr redirects are refused; use its direct server address')


def timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        raise SeerrError('incompatible', 'Seerr returned an invalid request timestamp')
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError()
        return stamp.timestamp()
    except (ValueError, OverflowError):
        raise SeerrError('incompatible', 'Seerr returned an invalid request timestamp') from None


def normalize_request(row, stream):
    if not isinstance(row, dict) or not isinstance(row.get('media'), dict):
        raise SeerrError('incompatible', 'Seerr request media is missing')
    media = row['media']
    if row.get('type') != stream or media.get('mediaType') != stream:
        raise SeerrError('incompatible', 'Seerr request type disagrees with its typed stream')
    for value, allowed in ((row.get('status'), range(1, 6)), (media.get('status'), range(1, 8))):
        if type(value) is not int or value not in allowed:
            raise SeerrError('incompatible', 'Seerr returned an unsupported request or media state')
    if type(row.get('id')) is not int or row['id'] <= 0 or type(row.get('is4k')) is not bool:
        raise SeerrError('incompatible', 'Seerr returned an invalid request identity')
    for name in ('tmdbId', 'tvdbId'):
        value = media.get(name)
        if value is not None and (type(value) is not int or value <= 0):
            raise SeerrError('incompatible', 'Seerr returned an invalid external ID')
    return dict(
        id=row['id'],
        type=stream,
        status=row['status'],
        media_status=media['status'],
        is4k=row['is4k'],
        created_at=timestamp(row.get('createdAt')),
        tmdb=media.get('tmdbId'),
        tvdb=media.get('tvdbId'),
    )


class SeerrClient:
    def __init__(self, base, *, expected_user, verified_versions=(), transport=None, allow_sign_in=False):
        if not isinstance(base, str) or base != base.strip() or any(ord(c) < 32 for c in base):
            raise SeerrError('not_configured', 'Invalid Seerr server address')
        try:
            parsed = urlsplit(base)
            parsed.port
        except ValueError:
            raise SeerrError('not_configured', 'Invalid Seerr server address') from None
        if (
            parsed.scheme not in {'http', 'https'}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {'', '/'}
        ):
            raise SeerrError('not_configured', 'Use a direct Seerr HTTP(S) server root without credentials')
        if type(expected_user) is not int or expected_user <= 0:
            raise SeerrError('not_configured', 'A separately verified view-only Seerr user is required')
        self.base = base.rstrip('/')
        self.expected_user = expected_user
        self.verified_versions = frozenset(verified_versions)
        self.allow_sign_in = allow_sign_in
        self.cookies = http.cookiejar.CookieJar()
        self.transport = transport or build_opener(NoSeerrRedirect(), HTTPCookieProcessor(self.cookies)).open
        self.synthetic = transport is not None

    def request(self, path, *, method='GET', params=None, data=None):
        if method == 'GET' and path in {'/status', '/auth/me'}:
            if params or data is not None:
                raise SeerrError('incompatible', 'Unsupported Seerr read parameters')
        elif method == 'GET' and path == '/request':
            if (
                not isinstance(params, dict)
                or set(params) != {'filter', 'mediaType', 'sort', 'sortDirection', 'take', 'skip'}
                or params['filter'] != 'all'
                or params['mediaType'] not in {'movie', 'tv'}
                or params['sort'] != 'added'
                or params['sortDirection'] != 'desc'
                or type(params['take']) is not int
                or params['take'] != 100
                or type(params['skip']) is not int
                or not 0 <= params['skip'] < MAX_RESULTS
                or data is not None
            ):
                raise SeerrError('incompatible', 'Unsupported Seerr request query')
        elif method == 'POST' and path == '/auth/local' and self.allow_sign_in:
            if (
                params
                or not isinstance(data, dict)
                or set(data) != {'email', 'password'}
                or any(not isinstance(value, str) or not value or len(value) > 4096 for value in data.values())
            ):
                raise SeerrError('not_authorized', 'Explicit local sign-in requires an email and password')
            register_secret(data['password'])
        else:
            raise SeerrError('incompatible', 'Seerr operation is outside the read-only allowlist')
        if not self.synthetic:
            development.block_external()
        headers = {'Accept': 'application/json'}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        query = '?' + urlencode(params) if params else ''
        req = Request(
            self.base + '/api/v1' + path + query,
            method=method,
            data=json.dumps(data).encode() if data is not None else None,
            headers=headers,
        )
        try:
            with self.transport(req, timeout=15) as response:
                # Refuse redirect-shaped injected transports as well as urllib's no-redirect handler.
                if response.geturl() != req.full_url:
                    raise SeerrError('incompatible', 'Seerr redirects are refused')
                for cookie in self.cookies:
                    register_secret(cookie.value)
                raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise SeerrError('incompatible', 'Seerr response exceeds the safety limit')
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except HTTPError as error:
            code = error.code
            error.close()
            raise SeerrError(
                'not_authorized' if code in {401, 403} else 'unreachable',
                'Seerr refused the session' if code in {401, 403} else 'Seerr could not be reached',
                http_status=code,
            ) from None
        except (URLError, TimeoutError, OSError):
            raise SeerrError('unreachable', 'Seerr could not be reached') from None
        except (ValueError, UnicodeError):
            raise SeerrError('incompatible', 'Seerr returned an unsupported response') from None

    def check_session(self):
        user = self.request('/auth/me')
        # Only the separately verified view permission is accepted, never an admin key or management account.
        if (
            type(user.get('id')) is not int
            or user.get('id') != self.expected_user
            or type(user.get('permissions')) is not int
            or user['permissions'] != REQUEST_VIEW
        ):
            raise SeerrError('not_authorized', 'This Seerr session is not the verified view-only user')

    def stream(self, kind):
        rows, total = [], None
        for offset in range(0, MAX_RESULTS, 100):
            block = self.request(
                '/request',
                params=dict(filter='all', mediaType=kind, sort='added', sortDirection='desc', take=100, skip=offset),
            )
            page = block.get('results')
            size = block.get('pageInfo', {}).get('results') if isinstance(block.get('pageInfo'), dict) else None
            if not isinstance(page, list) or len(page) > 100 or type(size) is not int or size < 0:
                raise SeerrError('incompatible', 'Seerr pagination is unsupported')
            if size > MAX_RESULTS or (total is not None and size != total):
                raise SeerrError('partial', 'Seerr changed during paging or exceeded the safe bound')
            total = size
            rows.extend(normalize_request(row, kind) for row in page)
            if len({row['id'] for row in rows}) != len(rows):
                raise SeerrError(
                    'partial', 'Seerr repeated requests during paging; retaining the last complete snapshot'
                )
            if len(rows) == total:
                break
            if len(rows) > total or not page:
                raise SeerrError('partial', 'Seerr paging did not yield the complete selected stream')
        if total is None or len(rows) != total:
            raise SeerrError('partial', 'Seerr paging did not complete within the safe bound')
        if [(r['created_at'], r['id']) for r in rows] != sorted(
            ((r['created_at'], r['id']) for r in rows), reverse=True
        ):
            raise SeerrError('partial', 'Seerr ordering changed during paging')
        return rows

    def snapshot(self, credentials=None):
        status = self.request('/status')
        if not isinstance(status.get('version'), str) or status['version'] not in self.verified_versions:
            raise SeerrError('incompatible', 'This Seerr version has not been separately verified')
        renewed = False
        while True:
            try:
                self.check_session()
                first = self.stream('movie') + self.stream('tv')
                second = self.stream('movie') + self.stream('tv')
                if first != second or len({row['id'] for row in second}) != len(second):
                    raise SeerrError(
                        'partial',
                        'Seerr changed between bounded consistency passes; retaining the last complete snapshot',
                    )
                self.check_session()
                return dict(
                    version=status['version'], requests=second, consistency='two_matching_bounded_passes_not_atomic'
                )
            except SeerrError as error:
                if error.http_status != 401 or renewed or not credentials or not self.allow_sign_in:
                    raise
                renewed = True
                self.request('/auth/local', method='POST', data=credentials)
