"""Explainable movie picks from the saved catalogue; browsing never calls a provider."""

import copy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math
import re
from .errors import UserError
from .rules import library_kind, stable_id
from .store import now

FEEDBACK = {'more', 'not_for_me', 'hide', 'clear'}
SOURCES = [
    dict(id='catalogue', name='Saved Plex movie catalogue', available=True),
    dict(id='feedback', name='Your local feedback', available=True),
    dict(
        id='external',
        name='External ratings, trends and social sources',
        available=False,
        reason='No external source or account is connected by this feature.',
    ),
    dict(
        id='household',
        name='Other household viewing',
        available=False,
        reason='Not used. No household history is read or exported.',
    ),
    dict(
        id='tv',
        name='Television recommendations',
        available=False,
        reason='Series indexing is required; episodes are not recommended as shows.',
    ),
]


def timestamp(value):
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            result = float(value)
        elif isinstance(value, str) and value:
            result = datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
        else:
            return None
        return result if math.isfinite(result) and result > 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def number(value, maximum=None):
    try:
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
            return None
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 and (maximum is None or result <= maximum) else None
    except InvalidOperation:
        return None


def rounded(value):
    return int(value.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def typed_identity(asset, library):
    item = asset.get('item') or {}
    guids = set()
    for row in item.get('Guid', []) if isinstance(item.get('Guid', []), list) else []:
        value = row.get('id') if isinstance(row, dict) else None
        if isinstance(value, str) and re.fullmatch(r'(?:tmdb|tvdb)://[1-9][0-9]*|imdb://tt[0-9]+', value.lower()):
            guids.add(value.lower())
    return dict(media_type='movie', server=str(library.get('server', '')), guids=sorted(guids))


def unit(asset, libraries):
    library = libraries[asset['library']]
    return (str(library.get('server', '')), asset['library'], str(asset['rating_key']))


def movie_catalogue(assets, libraries):
    """One pick per verified Plex item, never one per episode, edition or file part."""
    rows = {}
    for asset in assets:
        library = libraries.get(asset.get('library'))
        item = asset.get('item') or {}
        if (
            not library
            or not library.get('server')
            or not library.get('key')
            or (library.get('kind') or library_kind(library)) != 'movie'
            or library.get('profile') == 'home'
            or item.get('type') != 'movie'
            or not asset.get('present')
            or asset.get('deleted')
            or asset.get('missing_file')
            or not isinstance(asset.get('title'), str)
            or not asset['title'].strip()
            or not asset.get('rating_key')
            or str(item.get('ratingKey', '')) != str(asset['rating_key'])
        ):
            continue
        identity = unit(asset, libraries)
        previous = rows.get(identity)
        if previous is None or (timestamp(asset.get('scanned')) or 0, asset['id']) > (
            timestamp(previous.get('scanned')) or 0,
            previous['id'],
        ):
            rows[identity] = asset
    return sorted(rows.values(), key=lambda a: (a['library'], str(a['rating_key']), a['id']))


def resolve_feedback(record, assets, catalogue, libraries):
    """Resolve only exact assets or a single same-type, same-server movie identity."""
    identity = record.get('identity') or {}
    if identity.get('media_type') != 'movie':
        return None, 'detached'
    originals = {a['id']: a for a in assets}
    by_unit = {unit(a, libraries): a for a in catalogue}
    original = originals.get(record.get('asset'))
    if (
        original
        and original.get('present')
        and not original.get('missing_file')
        and (original.get('item') or {}).get('type') == 'movie'
        and original.get('library') in libraries
        and unit(original, libraries) in by_unit
    ):
        target = by_unit[unit(original, libraries)]
        current = typed_identity(target, libraries[target['library']])
        old_ids, new_ids = set(identity.get('guids', [])), set(current['guids'])
        if identity.get('server') != current['server'] or old_ids and new_ids and not old_ids.intersection(new_ids):
            return None, 'identity_changed'
        return by_unit[unit(original, libraries)], 'attached'
    matches = []
    for candidate in catalogue:
        current = typed_identity(candidate, libraries[candidate['library']])
        if identity.get('server') == current['server'] and set(identity.get('guids', [])).intersection(
            current['guids']
        ):
            matches.append(candidate)
    return (matches[0], 'reattached') if len(matches) == 1 else (None, 'ambiguous' if matches else 'detached')


def rating_signals(item):
    facts = {}
    if 'Rating' in item:
        rows = item['Rating'] if isinstance(item['Rating'], list) else []
        for row in rows:
            if not isinstance(row, dict) or row.get('type') not in {'critic', 'audience'}:
                continue
            value = number(row.get('value'), Decimal(10))
            if value is not None:
                facts.setdefault(row['type'], value * 10)
    else:
        for role, field in [('critic', 'rating'), ('audience', 'audienceRating')]:
            value = number(item.get(field), Decimal(10))
            if value is not None:
                facts[role] = value * 10
    return facts


def discovery_version(asset, library):
    return stable_id(
        asset['id'],
        asset['library'],
        str(asset['rating_key']),
        typed_identity(asset, library),
        asset.get('fingerprint'),
        (asset.get('item') or {}).get('type'),
    )


def genres(asset):
    rows = (asset.get('item') or {}).get('Genre', [])
    rows = rows if isinstance(rows, list) else []
    return {
        r['tag'].strip().casefold()
        for r in rows
        if isinstance(r, dict) and isinstance(r.get('tag'), str) and r['tag'].strip()
    }


class Discovery:
    def discovery_settings(self):
        return self.store.get('settings', 'discovery-settings', dict(revision=1, enabled=True, detached_days=90))

    def save_discovery_settings(self, revision, changes):
        if (
            not isinstance(changes, dict)
            or set(changes) - {'enabled', 'detached_days'}
            or 'enabled' in changes
            and type(changes['enabled']) is not bool
            or 'detached_days' in changes
            and (type(changes['detached_days']) is not int or not 1 <= changes['detached_days'] <= 365)
        ):
            raise UserError('Choose discovery on/off and 1–365 days of detached feedback retention')
        with self.store.transaction():
            row = self.discovery_settings()
            if type(revision) is not int or revision != row['revision']:
                raise UserError('Discovery settings changed; reload before saving')
            values = {**row, **changes}
            if values != row:
                values['revision'] += 1
                self.store.put('settings', 'discovery-settings', values)
                self.store.record(
                    'discovery settings', 'Changed local discovery preferences', details=dict(fields=sorted(changes))
                )
        return values

    def discovery_feedback_state(self):
        return self.store.get('settings', 'discovery-feedback', dict(revision=1, entries={}))

    def _discovery_context(self):
        libraries = {lib['id']: lib for lib in self.store.all('libraries')}
        assets = self.store.all('assets')
        return libraries, assets, movie_catalogue(assets, libraries)

    def _discovery_resolved(self, state, libraries, assets, catalogue, clock):
        rows, detached = {}, []
        days = self.discovery_settings()['detached_days']
        for key, record in state['entries'].items():
            target, status = resolve_feedback(record, assets, catalogue, libraries)
            missing = timestamp(record.get('detached_since'))
            expired = missing is not None and clock - missing >= days * 86400
            if target is None or expired:
                detached.append(
                    dict(
                        asset=key,
                        title=record.get('title', 'Unavailable title'),
                        feedback=record['feedback'],
                        status='expired' if expired else status,
                        at=record['at'],
                    )
                )
                continue
            target_unit = unit(target, libraries)
            old = rows.get(target_unit)
            if old is None or (record['at'], key) > (old['record']['at'], old['key']):
                rows[target_unit] = dict(key=key, record=record, asset=target, status=status)
        return rows, detached

    def discovery_feedback_list(self):
        clock = timestamp(now())
        state = self.discovery_feedback_state()
        libraries, assets, catalogue = self._discovery_context()
        rows, detached = self._discovery_resolved(state, libraries, assets, catalogue, clock)
        entries = [
            dict(
                asset=row['key'],
                title=row['asset']['title'],
                feedback=row['record']['feedback'],
                status=row['status'],
                at=row['record']['at'],
            )
            for row in rows.values()
        ]
        return dict(revision=state['revision'], entries=entries + detached)

    def discovery_feedback(self, data):
        if (
            not isinstance(data, dict)
            or not {'asset', 'feedback', 'revision'}.issubset(data)
            or set(data) - {'asset', 'feedback', 'revision', 'asset_version'}
            or not isinstance(data['asset'], str)
            or not 1 <= len(data['asset']) <= 128
            or data['feedback'] not in FEEDBACK
            or type(data['revision']) is not int
        ):
            raise UserError('Choose a title and current local feedback revision')
        with self.store.transaction():
            state = self.discovery_feedback_state()
            if data['revision'] != state['revision']:
                raise UserError('Feedback changed in another view; reload and try again')
            libraries, assets, catalogue = self._discovery_context()
            current = next((a for a in catalogue if a['id'] == data['asset']), None)
            resolved, _ = self._discovery_resolved(state, libraries, assets, catalogue, timestamp(now()))
            keys = {data['asset']}
            if current:
                keys.update(r['key'] for identity, r in resolved.items() if identity == unit(current, libraries))
            elif data['feedback'] != 'clear' or data['asset'] not in state['entries']:
                raise UserError('This movie is no longer available for discovery feedback')
            if data['feedback'] != 'clear' and data.get('asset_version') != discovery_version(
                current, libraries[current['library']]
            ):
                raise UserError('Movie identity changed; reload before saving feedback')
            previous = copy.deepcopy(state['entries'])
            for key in keys:
                state['entries'].pop(key, None)
            if data['feedback'] != 'clear':
                state['entries'][current['id']] = dict(
                    asset=current['id'],
                    identity=typed_identity(current, libraries[current['library']]),
                    title=current['title'],
                    feedback=data['feedback'],
                    at=now(),
                    detached_since=None,
                )
            if previous != state['entries']:
                state['revision'] += 1
                self.store.put('settings', 'discovery-feedback', state)
                self.store.record(
                    'discovery feedback',
                    'Updated local recommendation feedback',
                    details=dict(asset=data['asset'], feedback=data['feedback']),
                )
        return dict(revision=state['revision'], feedback=data['feedback'])

    def reconcile_discovery_feedback(self):
        """Local maintenance after a successful scan; never changes Plex or media."""
        with self.store.transaction():
            state = self.discovery_feedback_state()
            libraries, assets, catalogue = self._discovery_context()
            changed, at = False, now()
            for key, record in list(state['entries'].items()):
                detached = timestamp(record.get('detached_since'))
                if (
                    detached is not None
                    and timestamp(at) - detached >= self.discovery_settings()['detached_days'] * 86400
                ):
                    del state['entries'][key]
                    changed = True
                    continue
                target, status = resolve_feedback(record, assets, catalogue, libraries)
                if target is None:
                    if not record.get('detached_since'):
                        record['detached_since'], changed = at, True
                    elif (
                        timestamp(at) - (timestamp(record['detached_since']) or timestamp(at))
                        >= self.discovery_settings()['detached_days'] * 86400
                    ):
                        del state['entries'][key]
                        changed = True
                elif record.get('detached_since'):
                    record['detached_since'], changed = None, True
                if target and status == 'reattached' and record.get('reattached_asset') != target['id']:
                    record['reattached_asset'], changed = target['id'], True
                    self.store.record(
                        'discovery feedback',
                        'Reattached feedback to one verified movie identity',
                        details=dict(asset=key, current_asset=target['id']),
                    )
            if changed:
                state['revision'] += 1
                self.store.put('settings', 'discovery-feedback', state)

    def discovery(self, row='picked', library='all', limit=20):
        if row not in {'new', 'picked'} or type(limit) is not int or not 1 <= limit <= 50:
            raise UserError('Choose a discovery row and a limit of 1–50')
        libraries, assets, catalogue = self._discovery_context()
        if library != 'all' and library not in libraries:
            raise UserError('Select a connected library')
        at, settings = now(), self.discovery_settings()
        clock, state = timestamp(at), self.discovery_feedback_state()
        feedback, detached = self._discovery_resolved(state, libraries, assets, catalogue, clock)
        liked = set().union(*(genres(r['asset']) for r in feedback.values() if r['record']['feedback'] == 'more'))
        items = []
        for asset in catalogue if settings['enabled'] else []:
            if library != 'all' and asset['library'] != library:
                continue
            item = asset['item']
            vote = feedback.get(unit(asset, libraries))
            if vote and vote['record']['feedback'] in {'not_for_me', 'hide'}:
                continue
            count = number(item.get('viewCount'))
            if count is not None and count > 0:
                continue
            added = number(item.get('addedAt'))
            added = float(added) if added is not None and added <= Decimal(str(clock)) else None
            if row == 'new' and (added is None or clock - added > 30 * 86400):
                continue
            observed = timestamp(asset.get('scanned'))
            observed_at = asset.get('scanned') if observed is not None and observed <= clock else None
            stale = observed_at is None or clock - observed > 86400
            why = [
                dict(
                    signal='added',
                    text=f'Added {math.ceil((clock - added) / 86400)} days ago'
                    if added
                    else 'Plex arrival date unavailable',
                    source='plex.added',
                    observed_at=observed_at,
                )
            ]
            facts = rating_signals(item)
            mean = sum(facts.values(), Decimal(0)) / len(facts) if facts else None
            label = ', '.join(
                f'{"Critics" if kind == "critic" else "audience"} {rounded(value)}%' for kind, value in facts.items()
            )
            why.append(
                dict(signal='rating', text=label or 'No rating in Plex', source='plex.rating', observed_at=observed_at)
            )
            offset = number(item.get('viewOffset'))
            view = 'in_progress' if offset is not None and offset > 0 else 'unwatched' if count == 0 else 'view_unknown'
            why.append(
                dict(
                    signal=view,
                    text={
                        'in_progress': 'In progress',
                        'unwatched': 'Not watched yet',
                        'view_unknown': 'Viewing state unavailable',
                    }[view],
                    source='plex.view',
                    observed_at=observed_at,
                )
            )
            bonus = 10 if row == 'picked' and genres(asset).intersection(liked) else 0
            if bonus:
                dates = [
                    r['record']['at']
                    for r in feedback.values()
                    if r['record']['feedback'] == 'more' and genres(r['asset']).intersection(genres(asset))
                ]
                why.append(
                    dict(
                        signal='feedback',
                        text='Like something you marked “More like this”',
                        source='curator.feedback',
                        observed_at=max(dates),
                    )
                )
            items.append(
                dict(
                    asset=asset['id'],
                    library=asset['library'],
                    title=asset['title'],
                    media_type='movie',
                    asset_version=discovery_version(asset, libraries[asset['library']]),
                    rating_key=str(asset['rating_key']),
                    kind='in_library',
                    score=rounded(mean + bonus) if mean is not None else None,
                    why=why,
                    stale=stale,
                    feedback=vote['record']['feedback'] if vote else None,
                    observed_at=observed_at,
                    added_at=added,
                )
            )
        items.sort(
            key=lambda pick: (
                pick['score'] is None,
                -(pick['score'] or 0),
                -(pick['added_at'] or 0),
                pick['title'].casefold(),
                pick['library'],
                pick['asset'],
            )
        )
        outage = bool(self.plex_failure) or any(
            s.get('error') for key, s in self.scan_status.items() if library == 'all' or key == library
        )
        stale = outage or any(pick['stale'] for pick in items)
        empty = (
            'Discovery is off'
            if not settings['enabled']
            else 'No verified Movies catalogue is available; TV and Other Videos are not included'
            if not catalogue
            else 'Nothing new in 30 days'
            if row == 'new'
            else 'Nothing unwatched to pick from'
        )
        return dict(
            row=row,
            generated_at=at,
            stale=stale,
            items=items[:limit],
            total=len(items),
            empty_reason=empty if not items else None,
            feedback_revision=state['revision'],
            detached_feedback=len(detached),
            settings=settings,
            sources=copy.deepcopy(SOURCES),
            status='Plex connection unavailable; showing saved catalogue'
            if outage
            else 'Saved Plex catalogue; no provider requests',
            limitation='Movies only. Ratings are observations from Plex metadata, not a direct provider refresh. No viewing history is exported.',
        )
