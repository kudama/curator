"""Finite complete inventory verification before any scheduled media access."""

import json
import time
from urllib.parse import quote

from .errors import UserError
from .maintenance_policy import digest

MAX_INVENTORY_BYTES = 16 * 1024 * 1024


def verified_inventory(client, library, options, guard, deadline=None):
    """Explicitly bounded known Plex paging, never an unbounded generator.

    Both complete inventories must match before any caller may stat/probe a file.
    """
    deadline = deadline if deadline is not None else time.monotonic() + options['scan_timeout_seconds']
    requests = 0

    def request(path, params=None, response_bytes=None):
        nonlocal requests
        guard()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise UserError('Bounded inventory deadline reached; no media probes were authorized')
        requests += 1
        return client.request(
            path,
            params=params,
            timeout=min(options['request_timeout_seconds'], remaining),
            max_bytes=response_bytes or options['response_limit_bytes'],
        )

    identity = request('/identity', response_bytes=4096)
    if not isinstance(identity, dict) or identity.get('machineIdentifier') != library['server']:
        raise UserError('Configured Plex server identity changed; no media probes authorized')
    path = '/library/sections/' + quote(str(library['key']), safe='') + '/all'

    def inventory():
        rows, seen, expected, start, byte_count = [], set(), None, 0, 0
        for _ in range(options['max_pages']):
            block = request(
                path,
                {
                    'type': 4 if library['type'] == 'show' else 1,
                    'X-Plex-Container-Start': start,
                    'X-Plex-Container-Size': min(options['page_size'], options['inventory_limit'] - start),
                },
            )
            if (
                not isinstance(block, dict)
                or type(block.get('totalSize')) is not int
                or not 0 <= block['totalSize'] <= options['inventory_limit']
            ):
                raise UserError(
                    'Complete inventory exceeds the approved catalogue cap or has no trustworthy total; increase the reviewed cap or scan manually'
                )
            if expected is None:
                expected = block['totalSize']
            elif expected != block['totalSize']:
                raise UserError('Inventory changed during pagination; no media probes authorized')
            page = block.get('Metadata', [])
            if not isinstance(page, list) or len(page) > options['page_size'] or start + len(page) > expected:
                raise UserError('Inventory pagination is incomplete or inconsistent; no media probes authorized')
            if block.get('offset', start) != start or block.get('size', len(page)) != len(page):
                raise UserError('Inventory page offsets/counts changed; no media probes authorized')
            byte_count += len(json.dumps(block, ensure_ascii=False).encode())
            if byte_count > MAX_INVENTORY_BYTES:
                raise UserError('Complete inventory exceeds the 16 MiB safe memory bound; use a manual scan')
            for item in page:
                if (
                    not isinstance(item, dict)
                    or type(item.get('ratingKey')) not in {str, int}
                    or not str(item['ratingKey'])
                    or len(str(item['ratingKey'])) > 256
                ):
                    raise UserError('Inventory item identity is incomplete; no media probes authorized')
                key = str(item['ratingKey'])
                if key in seen:
                    raise UserError('Inventory pagination repeated an identity; no media probes authorized')
                seen.add(key)
                rows.append(item)
            start += len(page)
            if start == expected:
                return sorted(rows, key=lambda row: str(row['ratingKey']))
            if not page:
                raise UserError('Inventory ended before its declared total; no media probes authorized')
        raise UserError('Approved inventory page-request cap reached; no media probes authorized')

    first, second = inventory(), inventory()
    stamp = digest(first)
    if stamp != digest(second):
        raise UserError('Verification inventories differ; no media probes authorized')
    guard()
    return dict(items=first, digest=stamp, requests=requests, count=len(first))
