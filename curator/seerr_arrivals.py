"""Typed catalog matching and last-complete snapshot retention; live access stays off."""

from datetime import datetime, timezone
import re
from .errors import UserError
from .seerr_client import SeerrError, timestamp
from .store import now


def external_ids(item):
    result = {}
    for row in item.get('Guid') or []:
        value = row.get('id') if isinstance(row, dict) else None
        match = re.fullmatch(r'(tmdb|tvdb)://([1-9][0-9]*)', value) if isinstance(value, str) else None
        if match:
            result.setdefault(match[1], set()).add(int(match[2]))
    return result


def added_at(item):
    value = item.get('addedAt')
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit() and int(value) > 0:
        return int(value)
    return None


def arrivals_view(requests, assets, libraries, *, series=(), tv_verified=False, clock=None):
    clock = clock if clock is not None else datetime.now(timezone.utc).timestamp()
    libs = {row['id']: row for row in libraries}
    movies, shows = {}, {}
    for asset in assets:
        library = libs.get(asset.get('library'), {})
        item = asset.get('item', {})
        if (
            not asset.get('present', True)
            or library.get('type') != 'movie'
            or library.get('profile') == 'home'
            or 'personal' in (library.get('agent') or '').lower()
            or library.get('agent') == 'com.plexapp.agents.none'
            or item.get('type') != 'movie'
        ):
            continue
        movies.setdefault(
            (asset['library'], asset['rating_key']),
            dict(
                asset=asset['id'],
                library=asset['library'],
                rating_key=asset['rating_key'],
                title=asset.get('title', 'Movie'),
                ids=external_ids(item),
                added=added_at(item),
            ),
        )
    if tv_verified:
        for row in series:
            library = libs.get(row.get('library'), {})
            item = row.get('item', {})
            if (
                library.get('type') != 'show'
                or item.get('type') != 'show'
                or library.get('profile') == 'home'
                or 'personal' in (library.get('agent') or '').lower()
                or library.get('agent') == 'com.plexapp.agents.none'
            ):
                continue
            episodes = [
                asset
                for asset in assets
                if asset.get('library') == row['library']
                and asset.get('present', True)
                and asset.get('item', {}).get('type') == 'episode'
                and str(asset.get('item', {}).get('grandparentRatingKey')) == str(row['rating_key'])
            ]
            shows[(row['library'], row['rating_key'])] = dict(
                library=row['library'],
                rating_key=row['rating_key'],
                title=item.get('title', 'Series'),
                ids=external_ids(item),
                episodes=episodes,
            )
    output = []
    for request in requests:
        row = dict(request=request['id'], type=request['type'], state='requested', matches=[])
        # Request state has priority over a shared media object's availability.
        if request['status'] != 2:
            row['state'] = {1: 'requested', 3: 'declined', 4: 'request_failed', 5: 'request_completed'}.get(
                request['status'], 'unsupported'
            )
        elif request['is4k']:
            row['state'] = '4k_excluded'
        elif request['media_status'] in {6, 7}:
            row['state'] = 'blocklisted' if request['media_status'] == 6 else 'removed'
        elif request['type'] == 'tv' and not tv_verified:
            row['state'] = 'tv_unavailable'
        elif request['media_status'] not in {4, 5} or (request['type'] == 'movie' and request['media_status'] != 5):
            row['state'] = 'on_its_way'
        else:
            field = 'tvdb' if request['type'] == 'tv' and request.get('tvdb') else 'tmdb'
            identifier = request.get(field)
            source = movies.values() if request['type'] == 'movie' else shows.values()
            candidates = [entry for entry in source if identifier and identifier in entry['ids'].get(field, set())]
            matches = []
            for candidate in candidates:
                if request['type'] == 'movie':
                    matches.append(
                        {key: candidate[key] for key in ('asset', 'library', 'rating_key', 'title', 'added')}
                    )
                else:
                    episodes = [a for a in candidate['episodes'] if added_at(a.get('item', {})) is not None]
                    episodes.sort(key=lambda a: added_at(a['item']), reverse=True)
                    if episodes:
                        matches.append(
                            dict(
                                asset=episodes[0]['id'],
                                library=candidate['library'],
                                rating_key=candidate['rating_key'],
                                title=candidate['title'],
                                added=added_at(episodes[0]['item']),
                            )
                        )
            row['matches'] = matches
            if len(matches) > 1:
                row['state'] = 'ambiguous'
            elif not matches:
                row['state'] = 'available_not_scanned'
            elif matches[0]['added'] is None:
                row['state'] = 'catalog_time_unavailable'
            elif matches[0]['added'] < request['created_at']:
                row['state'] = 'already_in_plex'
            else:
                row['state'] = 'partly_landed' if request['type'] == 'tv' and request['media_status'] == 4 else 'landed'
            row['landed_at'] = max((m['added'] for m in matches if m['added'] is not None), default=None)
        row['recent'] = row.get('landed_at') is not None and clock - 7 * 86400 <= row['landed_at'] <= clock
        output.append(row)
    return output


def cached_arrivals_view(record, assets, libraries, *, clock=None, series=(), tv_verified=False):
    clock = clock if clock is not None else datetime.now(timezone.utc).timestamp()
    success = record.get('last_success')
    try:
        age = clock - timestamp(success)
    except SeerrError:
        age = None
    stale = record.get('status') != 'complete' or age is None or age > 300
    hidden = age is None or age < -300 or age > 86400 or record.get('status') in {'incompatible', 'not_authorized'}
    rows = (
        []
        if hidden
        else arrivals_view(
            record.get('snapshot', {}).get('requests', []),
            assets,
            libraries,
            clock=clock,
            series=series,
            tv_verified=tv_verified,
        )
    )
    return dict(
        status=record.get('status', 'not_configured'),
        last_success=success,
        stale=stale,
        counts_visible=not hidden,
        rows=rows,
        recent_count=None
        if hidden
        else sum(row['recent'] and row['state'] in {'landed', 'partly_landed', 'ambiguous'} for row in rows),
        consistency=record.get('snapshot', {}).get('consistency'),
    )


class SeerrArrivals:
    def seerr_status(self):
        # No live instance/version/account has been selected or granted. Even imported
        # configuration cannot enable access through the ordinary config API.
        return dict(
            supported=True,
            enabled=False,
            status='not_configured',
            live_access_available=False,
            message='Seerr is not connected. Instance and view-only account review are still required.',
            tv_message='TV requests are not matched yet.',
            credential_configured=False,
        )

    def seerr_arrivals(self):
        return dict(**self.seerr_status(), rows=[], last_success=None, stale=False)

    def refresh_seerr_fixture(self, client):
        """Internal synthetic acceptance seam, never an HTTP action or a live transport."""
        if not getattr(client, 'synthetic', False):
            raise UserError('Live Seerr connections are not enabled; use separately reviewed configuration')
        key = 'seerr-offline-snapshot'
        previous = self.store.get('settings', key, {})
        try:
            snapshot = client.snapshot()
            record = dict(status='complete', last_success=now(), snapshot=snapshot, origin='synthetic')
        except SeerrError as error:
            record = {
                **previous,
                'status': error.state,
                'last_attempt': now(),
                'error': 'Seerr snapshot unavailable; retaining the last complete result',
            }
        with self.store.transaction():
            self.store.put('settings', key, record)
            if record['status'] != previous.get('status'):
                self.store.event(None, dict(action='Seerr offline connection state', state=record['status']))
        return record
