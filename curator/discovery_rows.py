"""Exact, explicitly approved Curator-owned Plex collection rows; no ranking control."""

import copy
import re
import uuid
from urllib.parse import quote
from .discovery import discovery_version, typed_identity
from .errors import UserError
from .rules import stable_id
from .store import now

ROLES = {'new': 'New and worth watching', 'picked': 'Picked by Curator'}
VISIBILITY = ('recommended', 'home', 'shared')
PLEX_FLAGS = dict(recommended='promotedToRecommended', home='promotedToOwnHome', shared='promotedToSharedHome')


def plex_bool(value):
    if value in (False, 0, '0'):
        return False
    if value in (True, 1, '1'):
        return True
    raise UserError('Plex returned an unknown capability or visibility flag')


def numeric_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,18}', value):
        raise UserError('Plex item identity is unsupported for row publication')
    return value


def managed_hubs(client, library):
    payload = client.request('/hubs/sections/' + quote(library['key'], safe='') + '/manage')
    raw = payload.get('Hub')
    if not isinstance(raw, list) or len(raw) > 1000 or int(payload.get('totalSize', len(raw))) > len(raw):
        raise UserError('Plex managed-row capability is unavailable or incomplete')
    rows = []
    for row in raw:
        identity = row.get('identifier') if isinstance(row, dict) else None
        if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,200}', identity):
            raise UserError('Plex returned an unsupported managed-row identity')
        rows.append(
            dict(identifier=identity, visibility={name: plex_bool(row.get(flag)) for name, flag in PLEX_FLAGS.items()})
        )
    if len({row['identifier'] for row in rows}) != len(rows):
        raise UserError('Plex managed rows are ambiguous')
    return rows


def row_capabilities(client, library):
    """Require observed writable/Pass/Hub responses, never just a version guess."""
    numeric_key(library['key'])
    root = client.request('/')
    if root.get('machineIdentifier') != library['server']:
        raise UserError('Plex server identity changed')
    owner_features = root.get('ownerFeatures', [])
    if isinstance(owner_features, str):
        owner_features = owner_features.split(',')
    pass_reported = 'pass' in owner_features if isinstance(owner_features, list) else False
    if not pass_reported:
        pass_reported = plex_bool(root.get('myPlexSubscription'))
    if not pass_reported or plex_bool(root.get('readOnlyLibraries')):
        raise UserError('Plex did not verify writable Plex Pass collection-row capability')
    return dict(supported=True, hubs=managed_hubs(client, library), client_display_verified=False)


def hub_for(hubs, library, collection):
    identity = 'custom.collection.' + library['key'] + '.' + numeric_key(collection)
    return next(
        (copy.deepcopy(row) for row in hubs if row['identifier'] == identity),
        dict(identifier=identity, visibility={key: False for key in VISIBILITY}, absent=True),
    )


def collection_manifest(client, library, key):
    key = numeric_key(key)
    item = client.item(key)
    if (
        item.get('type') != 'collection'
        or str(item.get('ratingKey', '')) != key
        or str(item.get('librarySectionID', '')) != library['key']
        or plex_bool(item.get('smart', 0))
    ):
        raise UserError('Owned collection identity, section or smart status changed')
    title = item.get('title')
    if not isinstance(title, str) or not title.strip():
        raise UserError('Owned collection title is unavailable')
    payload = client.request('/library/metadata/' + key + '/children', params={'X-Plex-Container-Size': 1000})
    members = payload.get('Metadata', [])
    if not isinstance(members, list) or int(payload.get('totalSize', len(members))) > len(members):
        raise UserError('Owned collection membership is incomplete')
    keys = []
    for member in members:
        if member.get('type') != 'movie' or str(member.get('librarySectionID', library['key'])) != library['key']:
            raise UserError('Owned collection contains unsupported or cross-library items')
        keys.append(numeric_key(str(member.get('ratingKey', ''))))
    if len(set(keys)) != len(keys):
        raise UserError('Owned collection membership is ambiguous')
    return dict(kind='collection', key=key, keys=sorted(keys), title=title)


def verify_movie(client, library, member):
    payload = client.request('/library/metadata/' + numeric_key(member['rating_key']), params={'includeGuids': 1})
    rows = payload.get('Metadata', [])
    if (
        not isinstance(rows, list)
        or len(rows) != 1
        or rows[0].get('type') != 'movie'
        or str(rows[0].get('ratingKey', '')) != member['rating_key']
        or str(rows[0].get('librarySectionID', '')) != library['key']
    ):
        raise UserError('A reviewed Plex movie moved or changed type')
    observed = typed_identity({'item': rows[0]}, library)
    if not member['identity']['guids'] or not set(member['identity']['guids']).intersection(observed['guids']):
        raise UserError('A reviewed Plex movie identity is missing or changed; rescan before publication')


def update_visibility(client, library, key, expected, visibility):
    current = hub_for(managed_hubs(client, library), library, key)
    if current != expected:
        raise UserError('Plex row visibility changed since review')
    if current['visibility'] == visibility:
        return current
    endpoint = '/hubs/sections/' + quote(library['key'], safe='') + '/manage'
    params = {PLEX_FLAGS[name]: int(visibility[name]) for name in VISIBILITY}
    method = 'PUT'
    if current.get('absent'):
        params['metadataItemId'] = numeric_key(key)
        method = 'POST'
    else:
        endpoint += '/' + quote(current['identifier'], safe='')
    client.request(endpoint, method, params, ignore_body=True)
    observed = hub_for(managed_hubs(client, library), library, key)
    if observed.get('absent') or observed['visibility'] != visibility:
        raise UserError('Plex did not verify the requested row visibility; inspect the receipt')
    return observed


class DiscoveryRows:
    def discovery_row(self, library, row):
        if not isinstance(row, str) or row not in ROLES:
            raise UserError('Choose a supported Curator row')
        return self.store.get(
            'settings',
            'discovery-row:' + library + ':' + row,
            dict(
                revision=0,
                collection=None,
                title=ROLES[row],
                visibility={k: False for k in VISIBILITY},
                uncertain=False,
            ),
        )

    def discovery_rows(self, library):
        self.library(library)
        receipts = [
            r for r in self.store.where('settings', record_type='discovery_row_receipt') if r['library'] == library
        ]
        return dict(
            rows={row: self.discovery_row(library, row) for row in ROLES},
            receipts=sorted(receipts, key=lambda r: r['created'], reverse=True)[:10],
            note='Off by default. Review exact membership and visibility before each explicit publication. No automatic updates.',
        )

    def recover_discovery_rows(self):
        with self.store.transaction():
            for receipt in self.store.where('settings', record_type='discovery_row_receipt', status='applying'):
                receipt.update(
                    status='needs_inspection',
                    error='Interrupted Plex write; inspect before a fresh preview',
                    updated=now(),
                )
                self.store.put('settings', receipt['id'], receipt)
                owned = self.discovery_row(receipt['library'], receipt['row'])
                self.store.put(
                    'settings',
                    'discovery-row:' + receipt['library'] + ':' + receipt['row'],
                    {**owned, 'revision': owned['revision'] + 1, 'uncertain': True, 'receipt': receipt['id']},
                )

    def discovery_row_preview(self, data):
        if not isinstance(data, dict) or set(data) != {'library', 'row', 'title', 'visibility', 'limit', 'revision'}:
            raise UserError('Invalid Plex row preview')
        library = self.library(data['library'])
        if (
            (library.get('standard_kind') or self.library_standard(library)['kind']) != 'movie'
            or library.get('profile') == 'home'
            or library['type'] != 'movie'
        ):
            raise UserError('Curator recommendation rows currently support Movies libraries only')
        row, title, visibility = data['row'], data['title'], data['visibility']
        if (
            not isinstance(row, str)
            or row not in ROLES
            or not isinstance(title, str)
            or not title.strip()
            or len(title) > 100
            or any(ord(c) < 32 for c in title)
            or not isinstance(visibility, dict)
            or set(visibility) != set(VISIBILITY)
            or any(type(v) is not bool for v in visibility.values())
            or type(data['limit']) is not int
            or not 1 <= data['limit'] <= 20
        ):
            raise UserError('Choose a row name, exact visibility and 1–20 movies')
        owned = self.discovery_row(library['id'], row)
        if type(data['revision']) is not int or data['revision'] != owned['revision'] or owned['uncertain']:
            raise UserError('Owned row changed or needs inspection; reload its receipt')
        if owned['collection'] and title.strip() != owned['title']:
            raise UserError('Keep the owned collection title; renaming is a separate Plex action')
        client = self.checked_client(library)
        capabilities = row_capabilities(client, library)
        existing = client.collections(library)
        collisions = [c for c in existing if c['title'].casefold() == title.strip().casefold()]
        if collisions and (
            len(collisions) != 1 or not owned['collection'] or collisions[0]['key'] != owned['collection']['key']
        ):
            raise UserError('That title belongs to an unmanaged or ambiguous collection; choose another title')
        before = collection_manifest(client, library, owned['collection']['key']) if owned['collection'] else None
        if before and (before['title'] != owned['title'] or set(before['keys']) != set(owned['collection']['keys'])):
            raise UserError('Owned collection changed in Plex; inspect before replacing membership')
        current_hub = hub_for(capabilities['hubs'], library, before['key']) if before else None
        if before and current_hub['visibility'] != owned['visibility']:
            raise UserError('Owned row visibility changed in Plex; inspect before replacing it')
        picks = self.discovery(row, library['id'], data['limit'])
        members = [
            dict(
                asset=pick['asset'],
                rating_key=numeric_key(pick['rating_key']),
                asset_version=pick['asset_version'],
                identity=typed_identity(self.store.get('assets', pick['asset']), library),
                title=pick['title'],
            )
            for pick in picks['items']
        ]
        if not any(visibility.values()):
            # Hiding a row never silently empties or deletes its collection.
            members = []
            keys = before['keys'] if before else []
        else:
            keys = [p['rating_key'] for p in members]
            if not keys:
                raise UserError('No eligible movies are available; unpublish instead of creating an empty row')
        for member in members:
            verify_movie(client, library, member)
        plan = dict(
            id=uuid.uuid4().hex,
            record_type='discovery_row_plan',
            library=library['id'],
            server=library['server'],
            row=row,
            title=title.strip(),
            owned=owned,
            before=before,
            before_hub=current_hub,
            members=members,
            keys=keys,
            visibility=copy.deepcopy(visibility),
            created=now(),
            feedback_revision=picks['feedback_revision'],
            settings_revision=picks['settings']['revision'],
        )
        plan['token'] = stable_id(plan, length=64)
        with self.store.transaction():
            if self.discovery_row(library['id'], row) != owned:
                raise UserError('Owned row changed while creating the preview')
            self.store.put('settings', 'discovery-row-plan:' + plan['id'], plan)
        return self.public_discovery_row_plan(plan)

    @staticmethod
    def public_discovery_row_plan(plan):
        return {
            key: copy.deepcopy(plan[key])
            for key in (
                'id',
                'token',
                'library',
                'row',
                'title',
                'before',
                'before_hub',
                'members',
                'keys',
                'visibility',
                'created',
            )
        }

    def _row_plan(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{32}', identity):
            raise UserError('Plex row preview not found')
        plan = self.store.get('settings', 'discovery-row-plan:' + identity)
        if not plan or plan.get('record_type') != 'discovery_row_plan':
            raise UserError('Plex row preview not found')
        return plan

    def _save_row_receipt(self, receipt):
        receipt['updated'] = now()
        with self.store.transaction():
            self.store.put('settings', receipt['id'], receipt)

    def apply_discovery_row(self, identity, token, approved):
        plan = self._row_plan(identity)
        if approved is not True or token != plan['token']:
            raise UserError('Approve the exact reviewed Plex row changes')
        library = self.library(plan['library'])
        with self.operation_lock('discovery-rows:' + library['id']):
            receipt_id = 'discovery-row-receipt:' + identity
            receipt = self.store.get('settings', receipt_id)
            if receipt:
                if receipt['status'] == 'verified':
                    return receipt
                raise UserError('This publication was already attempted; inspect its receipt before a fresh preview')
            owned = self.discovery_row(library['id'], plan['row'])
            if owned != plan['owned'] or library['server'] != plan['server']:
                raise UserError('Owned row or server identity changed; review a fresh preview')
            if (
                self.discovery_feedback_state()['revision'] != plan['feedback_revision']
                or self.discovery_settings()['revision'] != plan['settings_revision']
            ):
                raise UserError('Discovery feedback or settings changed; review a fresh preview')
            current = {a['id']: a for a in self._discovery_context()[2]}
            for member in plan['members']:
                asset = current.get(member['asset'])
                if not asset or discovery_version(asset, self.library(asset['library'])) != member['asset_version']:
                    raise UserError('A reviewed movie identity changed; review a fresh preview')
            client = self.checked_client(library)
            caps = row_capabilities(client, library)
            for member in plan['members']:
                verify_movie(client, library, member)
            if plan['before']:
                before = collection_manifest(client, library, plan['before']['key'])
                if before != plan['before'] or hub_for(caps['hubs'], library, before['key']) != plan['before_hub']:
                    raise UserError('Plex collection membership or visibility changed since review')
            else:
                if any(c['title'].casefold() == plan['title'].casefold() for c in client.collections(library)):
                    raise UserError('A collection with this title appeared; nothing was adopted')
            receipt = dict(
                id=receipt_id,
                record_type='discovery_row_receipt',
                library=library['id'],
                row=plan['row'],
                plan=identity,
                created=now(),
                status='applying',
                stage='approved',
                collection=owned['collection'],
                expected=dict(keys=plan['keys'], visibility=plan['visibility']),
                before=plan['before'],
                error=None,
            )
            self._save_row_receipt(receipt)
            try:
                if not plan['keys'] and not plan['before']:
                    receipt['stage'] = 'no collection or row to hide'
                else:

                    def checkpoint(value):
                        numeric_key(value['key'])
                        receipt.update(
                            collection=copy.deepcopy(value),
                            stage='collection verified'
                            if not value.get('uncertain')
                            else 'collection creation outcome pending',
                        )
                        self._save_row_receipt(receipt)

                    receipt['stage'] = 'updating collection membership'
                    self._save_row_receipt(receipt)
                    group = client.managed_group(
                        library, 'collection', plan['title'], plan['keys'], owned['collection'], checkpoint
                    )
                    manifest = collection_manifest(client, library, group['key'])
                    if manifest['title'] != plan['title'] or set(manifest['keys']) != set(plan['keys']):
                        raise UserError('Plex did not verify collection membership')
                    receipt.update(collection=group, stage='updating row visibility')
                    self._save_row_receipt(receipt)
                    expected_hub = plan['before_hub'] or hub_for(managed_hubs(client, library), library, group['key'])
                    observed = update_visibility(client, library, group['key'], expected_hub, plan['visibility'])
                    receipt['observed_visibility'] = observed
                updated = dict(
                    revision=owned['revision'] + 1,
                    collection=receipt['collection'],
                    title=plan['title'],
                    visibility=plan['visibility'],
                    uncertain=False,
                )
                with self.store.transaction():
                    self.store.put('settings', 'discovery-row:' + library['id'] + ':' + plan['row'], updated)
                    receipt.update(status='verified', stage='membership and visibility verified', updated=now())
                    self.store.put('settings', receipt_id, receipt)
                    self.store.record(
                        'discovery publication',
                        'Verified explicitly approved Curator collection row',
                        library=library['id'],
                        details=dict(row=plan['row'], receipt=receipt_id),
                    )
                return receipt
            except Exception as error:
                receipt.update(
                    status='needs_inspection',
                    error=str(error)
                    if isinstance(error, UserError)
                    else 'Publication outcome is uncertain; inspect Plex before retrying',
                )
                self._save_row_receipt(receipt)
                with self.store.transaction():
                    self.store.put(
                        'settings',
                        'discovery-row:' + library['id'] + ':' + plan['row'],
                        {**owned, 'revision': owned['revision'] + 1, 'uncertain': True, 'receipt': receipt_id},
                    )
                return receipt

    def inspect_discovery_row(self, identity, accept_current=False):
        plan = self._row_plan(identity)
        library = self.library(plan['library'])
        with self.operation_lock('discovery-rows:' + library['id']):
            receipt = self.store.get('settings', 'discovery-row-receipt:' + identity)
            if not receipt:
                raise UserError('Publication receipt not found')
            client = self.checked_client(library)
            caps = row_capabilities(client, library)
            group = receipt.get('collection')
            if not group:
                collisions = [
                    c for c in client.collections(library) if c['title'].casefold() == plan['title'].casefold()
                ]
                result = {
                    **receipt,
                    'inspection': dict(
                        collection=None,
                        title_exists=bool(collisions),
                        note='No verified collection ID returned. A matching title is never adopted; resolve it in Plex before retrying.',
                    ),
                }
                if accept_current is True:
                    owned = self.discovery_row(library['id'], plan['row'])
                    if not owned['uncertain'] or owned.get('receipt') != receipt['id'] or collisions:
                        raise UserError('Resolve the unknown collection in Plex before acknowledging this receipt')
                    with self.store.transaction():
                        self.store.put(
                            'settings',
                            'discovery-row:' + library['id'] + ':' + plan['row'],
                            {**owned, 'revision': owned['revision'] + 1, 'uncertain': False},
                        )
                        result.update(status='inspected_no_collection', updated=now())
                        self.store.put('settings', receipt['id'], result)
                return result
            observed = collection_manifest(client, library, group['key'])
            if observed['title'] != plan['title']:
                raise UserError('Collection title changed; manual inspection is required')
            hub = hub_for(caps['hubs'], library, group['key'])
            complete = set(observed['keys']) == set(plan['keys']) and hub['visibility'] == plan['visibility']
            result = {**receipt, 'inspection': dict(collection=observed, hub=hub, matches_approved=complete)}
            if accept_current is True:
                owned = self.discovery_row(library['id'], plan['row'])
                if not owned['uncertain'] or owned.get('receipt') != receipt['id']:
                    raise UserError('This receipt no longer owns the uncertain row')
                with self.store.transaction():
                    state = dict(
                        revision=owned['revision'] + 1,
                        collection=dict(kind='collection', key=group['key'], keys=observed['keys']),
                        title=observed['title'],
                        visibility=hub['visibility'],
                        uncertain=False,
                    )
                    self.store.put('settings', 'discovery-row:' + library['id'] + ':' + plan['row'], state)
                    result.update(status='verified' if complete else 'inspected_partial', updated=now())
                    self.store.put('settings', receipt['id'], result)
                    self.store.record(
                        'discovery publication',
                        'Accepted inspected Plex row state locally; no Plex write',
                        library=library['id'],
                        details=dict(receipt=receipt['id']),
                    )
            return result
