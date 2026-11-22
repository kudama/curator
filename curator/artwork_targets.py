"""Collection-owned artwork identities, kept outside the scanned media catalog."""

import copy
import hashlib
from .store import now
from .plex import PlexError
from .errors import UserError
from .rules import stable_id


class ArtworkTargets:
    def artwork_targets(self):
        return self.store.where('settings', record_type='artwork_target')

    def artwork_collections(self, library_id):
        library = self.library(library_id)
        return dict(collections=self.checked_client(library).collections(library))

    def collection_artwork_target(self, library_id, rating_key):
        library = self.library(library_id)
        client = self.checked_client(library)
        if not any(str(row['key']) == str(rating_key) for row in client.collections(library)):
            raise UserError('Collection does not belong to this library')
        item = client.item(str(rating_key))
        if item.get('type') != 'collection' or str(item.get('ratingKey')) != str(rating_key):
            raise UserError('Plex collection identity changed')
        identity = stable_id(library['server'], library_id, str(rating_key))
        asset = dict(
            id=identity,
            record_type='artwork_target',
            artwork_target='collection',
            library=library_id,
            rating_key=str(rating_key),
            title=item['title'],
            plex_path='',
            present=True,
            item=copy.deepcopy(item),
            updated=now(),
        )
        with self.store.transaction():
            self.store.put('settings', 'artwork-target:' + identity, asset)
        return dict(asset=asset)

    def person_artwork_target(self, profile_id, library_id):
        self.library(library_id)
        profile = self.store.get('settings', 'cast_profiles', {}).get(profile_id)
        if not profile:
            raise UserError('Person not found')
        identity = hashlib.sha256(('person:' + profile_id).encode()).hexdigest()[:24]
        existing = self.store.get('settings', 'artwork-target:' + identity)
        asset = dict(
            id=identity,
            record_type='artwork_target',
            artwork_target='person',
            profile_id=profile_id,
            library=existing['library'] if existing else library_id,
            rating_key=profile_id,
            title=profile['name'],
            plex_path='',
            present=True,
            item=dict(
                title=profile['name'],
                summary='Square portrait of ' + profile['name'],
                ratingKey=profile_id,
                guid='person:' + profile_id,
            ),
            updated=now(),
        )
        with self.store.transaction():
            self.store.put('settings', 'artwork-target:' + identity, asset)
        return dict(asset=asset)

    def artwork_preview(self, asset_ids, kind, ratio, images, originals=None):
        from .image_contract import editor_png

        if (
            not isinstance(asset_ids, list)
            or not 1 <= len(asset_ids) <= 100
            or any(not isinstance(a, str) for a in asset_ids)
            or len(set(asset_ids)) != len(asset_ids)
        ):
            raise UserError('Select one to 100 distinct artwork targets')
        from . import branding

        if kind not in {'cover', 'background', 'square', 'logo'}:
            raise UserError('Choose an artwork type')
        if not isinstance(images, dict) or set(images) != set(asset_ids):
            raise UserError('Choose a candidate for every selected item')
        if (
            kind == 'background'
            and ratio != '16:9'
            or kind == 'square'
            and ratio != '1:1'
            or kind == 'cover'
            and ratio != '2:3'
            or kind == 'logo'
            and ratio is not None
        ):
            raise UserError('Choose the correct artwork format')
        for aid in asset_ids:
            asset = self.asset({'asset': aid}, check=False)
            if asset.get('artwork_target') == 'collection' and kind == 'cover' and ratio != '2:3':
                raise UserError('Collection posters use 2:3')
            editor_png(images[aid], ratio, logo=kind == 'logo')
        presets = self.config().get('branding_presets', branding.DEFAULT_PRESETS)
        return self.artwork_plan(
            asset_ids, kind, presets[0]['id'], {'ratio': ratio} if ratio else {}, images, originals
        )

    def artwork_reference_frames(self, asset_id):
        from . import tools

        asset = self.asset({'asset': asset_id})
        frames = tools.frames(
            asset['local_path'], self.store.root / 'frames' / asset_id, asset['technical'], self.config()
        )
        return dict(frames=frames)

    def artwork_target_image(self, asset_id, kind):
        from . import development, tools

        if development.root():
            asset = self.store.get('assets', asset_id, {})
            source = asset.get('development_artwork', {}).get(kind)
            if not source:
                raise UserError('No synthetic artwork for this target')
            return tools.image_bytes(development.check_path(source))
        from .plex import Plex

        if kind not in Plex.ARTWORK:
            raise UserError('Unknown artwork type')
        asset = self.asset({'asset': asset_id}, check=False)
        if asset.get('artwork_target') == 'person':
            if kind != 'square':
                raise UserError('Person portraits are square')
            return self.cast_profile_image(asset['profile_id'])
        client = self.checked_client(self.library(asset['library']))
        try:
            return client.image(asset['rating_key'], kind)
        except PlexError as error:
            pending = asset.get('rename_pending_plex') or {}
            if 'HTTP 404' not in str(error) or pending.get('destination') != asset.get('plex_path'):
                raise
        # A completed, verified Curator rename may be rematched by Plex later.
        # Follow only one exact destination in the same verified library and file.
        self.asset({'asset': asset_id})
        matches = {
            str(item['ratingKey']): item
            for item in client.items(self.library(asset['library']))
            if any(
                part.get('file') == asset['plex_path']
                for media in item.get('Media', [])
                for part in media.get('Part', [])
            )
        }
        if len(matches) != 1:
            raise UserError('Plex artwork identity is ambiguous; rescan and reopen the editor')
        current = next(iter(matches.values()))
        if asset.get('item', {}).get('type') and current.get('type') != asset['item']['type']:
            raise UserError('Plex artwork target type changed; rescan before editing')
        self.asset({'asset': asset_id})
        with self.store.transaction():
            latest = self.store.get('assets', asset_id)
            if not latest or any(latest.get(key) != asset.get(key) for key in ('plex_path', 'fingerprint')):
                raise UserError('Artwork target changed while refreshing; reopen the editor')
            if latest['rating_key'] not in {asset['rating_key'], str(current['ratingKey'])}:
                raise UserError('Plex artwork identity changed while refreshing; reopen the editor')
            latest.update(
                rating_key=str(current['ratingKey']),
                item=copy.deepcopy(current),
                title=current.get('title', latest['title']),
            )
            latest.pop('rename_pending_plex', None)
            self.store.put('assets', asset_id, latest)
        with self.lock:
            for key in list(self.thumbnail_cache):
                if key[0] == asset_id:
                    self.thumbnail_cache.pop(key, None)
        return client.image(str(current['ratingKey']), kind)
