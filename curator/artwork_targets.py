"""Collection-owned artwork identities, kept outside the scanned media catalog."""
import copy
import hashlib
import json
from .store import now


class ArtworkTargets:
    def artwork_targets(self):
        return [row for row in self.store.all('settings') if isinstance(row,dict) and row.get('record_type') == 'artwork_target']

    def artwork_collections(self, library_id):
        library = self.library(library_id)
        return dict(collections=self.checked_client(library).collections(library))

    def collection_artwork_target(self, library_id, rating_key):
        library = self.library(library_id)
        client = self.checked_client(library)
        if not any(str(row['key']) == str(rating_key) for row in client.collections(library)):
            raise ValueError('Collection does not belong to this library')
        item = client.item(str(rating_key))
        if item.get('type') != 'collection' or str(item.get('ratingKey')) != str(rating_key):
            raise ValueError('Plex collection identity changed')
        identity = hashlib.sha256(json.dumps([library['server'], library_id, str(rating_key)]).encode()).hexdigest()[:24]
        asset = dict(id=identity, record_type='artwork_target', artwork_target='collection',
                     library=library_id, rating_key=str(rating_key), title=item['title'],
                     plex_path='', present=True, item=copy.deepcopy(item), updated=now())
        with self.store.transaction():
            self.store.put('settings', 'artwork-target:'+identity, asset)
        return dict(asset=asset)

    def artwork_preview(self, asset_ids, kind, ratio, images, originals=None):
        from .image_contract import editor_png
        if not isinstance(asset_ids,list) or not 1<=len(asset_ids)<=100 or any(not isinstance(a,str) for a in asset_ids) or len(set(asset_ids))!=len(asset_ids):
            raise ValueError('Select one to 100 distinct artwork targets')
        from . import branding
        if kind not in {'cover','background','square','logo'}:
            raise ValueError('Choose an artwork type')
        if not isinstance(images,dict) or set(images)!=set(asset_ids):
            raise ValueError('Choose a candidate for every selected item')
        if kind=='background' and ratio!='16:9' or kind=='square' and ratio!='1:1' or kind=='cover' and ratio not in {'2:3','16:9'} or kind=='logo' and ratio is not None:
            raise ValueError('Choose the correct artwork format')
        for aid in asset_ids:
            asset=self.asset({'asset':aid},check=False)
            if asset.get('artwork_target')=='collection' and kind=='cover' and ratio!='2:3':
                raise ValueError('Collection posters use 2:3')
            editor_png(images[aid],ratio,logo=kind=='logo')
        presets=self.config().get('branding_presets',branding.DEFAULT_PRESETS)
        return self.artwork_plan(asset_ids,kind,presets[0]['id'],{'ratio':ratio} if ratio else {},images,originals)

    def artwork_reference_frames(self, asset_id):
        from . import tools
        asset=self.asset({'asset':asset_id})
        frames=tools.frames(asset['local_path'],self.store.root/'frames'/asset_id,asset['technical'],self.config())
        return dict(frames=frames)

    def artwork_target_image(self, asset_id, kind):
        from .plex import Plex
        if kind not in Plex.ARTWORK:raise ValueError('Unknown artwork type')
        asset=self.asset({'asset':asset_id},check=False)
        return self.checked_client(self.library(asset['library'])).image(asset['rating_key'],kind)
