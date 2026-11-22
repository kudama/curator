"""Completed-scan arrival ledger with a mandatory no-backfill activation baseline."""

from datetime import datetime
import uuid

from .history import acting
from .maintenance_policy import digest
from .store import now

STABILITY_SECONDS = 30


def identity_tokens(asset):
    """Conservative aliases: rematch/rename/copy clues never create another arrival."""
    values = [('asset', asset['id']), ('item', asset.get('rating_key'))]
    guid = asset.get('item', {}).get('guid')
    if guid:
        values.append(('guid', guid))
    source = asset.get('fingerprint') or {}
    if source.get('device') is not None and source.get('inode') is not None:
        values.append(('file', source['device'], source['inode']))
    if source.get('size') is not None and source.get('modified') is not None:
        values.append(('possible_copy', source['size'], source['modified']))
    return [digest(value) for value in values if value[-1] is not None]


class MaintenanceArrivals:
    def maintenance_arrivals(self, library):
        return [
            row
            for row in self.store.all('settings')
            if isinstance(row, dict)
            and row.get('record_type') == 'maintenance_arrival'
            and row.get('library') == library
        ]

    def observe_maintenance_scan(self, library_id, observed_ids, completed=None):
        """Only called after a completely successful authoritative scan.

        The first completed scan is a baseline even if its files are new to the
        app. Observations while disabled do not become retroactive permissions.
        """
        library = self.library(library_id)
        key = 'maintenance-arrivals:' + library_id
        instant = self.maintenance_clock()
        instant_text = instant.isoformat()
        scope = digest(self.maintenance_scope(library))
        observed_ids = set(observed_ids)
        assets = [asset for asset in self.store.all('assets') if asset['library'] == library_id]
        with self.lock, self.store.transaction(), acting('curator'):
            registry = self.store.get('settings', key)
            if registry is None or registry.get('scope') != scope:
                registry = dict(
                    id=key,
                    record_type='maintenance_arrivals',
                    library=library_id,
                    generation=uuid.uuid4().hex,
                    scope=scope,
                    sequence=1,
                    completed_scan=completed or now(),
                    observed_at=instant_text,
                    known={},
                )
                for asset in assets:
                    for token in identity_tokens(asset):
                        registry['known'][token] = 'baseline'
                self.store.record(
                    'maintenance_baseline',
                    'Authoritative arrival baseline recorded; existing catalog is excluded',
                    library=library_id,
                    details={'items': len(assets), 'sequence': 1},
                )
                self.store.put('settings', key, registry)
                return dict(baseline=True, arrivals=0, sequence=1)
            if instant < datetime.fromisoformat(registry['observed_at']):
                self.store.record(
                    'maintenance_clock',
                    'Clock moved backwards; arrival eligibility held for review',
                    library=library_id,
                    level='warning',
                )
                return dict(held=True, reason='clock rollback', arrivals=0)
            registry.update(
                sequence=registry['sequence'] + 1, completed_scan=completed or now(), observed_at=instant_text
            )
            count = 0
            for asset in assets:
                if asset['id'] not in observed_ids or not asset.get('present', True):
                    continue
                tokens = identity_tokens(asset)
                aliases = {registry['known'][token] for token in tokens if token in registry['known']}
                if aliases == {'baseline'} or 'baseline' in aliases:
                    for token in tokens:
                        registry['known'][token] = 'baseline'
                    continue
                if len(aliases) > 1:
                    self.store.record(
                        'maintenance_ambiguity',
                        'Possible rematch/copy has multiple arrival identities; automatic action withheld',
                        library=library_id,
                        level='warning',
                    )
                    continue
                identity = next(iter(aliases), 'maintenance-arrival:' + uuid.uuid4().hex)
                arrival = self.store.get('settings', identity)
                if arrival is None:
                    arrival = dict(
                        id=identity,
                        record_type='maintenance_arrival',
                        library=library_id,
                        generation=registry['generation'],
                        first_sequence=registry['sequence'],
                        asset=asset['id'],
                        phase='observing',
                        fingerprint=asset.get('fingerprint'),
                        stable_since=instant_text,
                        created=now(),
                    )
                    count += 1
                elif arrival['phase'] in {'observing', 'ready'}:
                    arrival['asset'] = asset['id']
                    if (
                        arrival.get('fingerprint') != asset.get('fingerprint')
                        or asset.get('blocked')
                        or asset.get('availability_error')
                    ):
                        arrival.update(
                            phase='observing', fingerprint=asset.get('fingerprint'), stable_since=instant_text
                        )
                    elif (
                        asset.get('fingerprint')
                        and (instant - datetime.fromisoformat(arrival['stable_since'])).total_seconds()
                        >= STABILITY_SECONDS
                    ):
                        arrival['phase'] = 'ready'
                arrival.update(last_sequence=registry['sequence'], updated=now())
                for token in tokens:
                    registry['known'][token] = identity
                self.store.put('settings', identity, arrival)
            self.store.record(
                'maintenance_arrivals',
                'Completed-scan arrival identities reconciled',
                library=library_id,
                details={'new': count, 'sequence': registry['sequence']},
            )
            self.store.put('settings', key, registry)
        return dict(baseline=False, arrivals=count, sequence=registry['sequence'])
