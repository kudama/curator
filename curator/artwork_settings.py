"""Versioned shared guide edits and explicit folder artwork scope."""
import copy
import hashlib
import json
from . import branding
from .errors import UserError


class ArtworkSettings:
    def artwork_style_guides(self):
        rows=self.config().get('branding_presets',branding.DEFAULT_PRESETS)
        revision=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
        return dict(styles=copy.deepcopy(rows),revision=revision)

    def save_artwork_style_guides(self, revision, rows):
        branding.validate_presets(rows)
        with self.store.transaction():
            if self.artwork_style_guides()['revision']!=revision:raise UserError('Style guides changed; reopen before saving')
            config=self.config();config['branding_presets']=copy.deepcopy(rows);self.store.put('settings','config',config)
        return self.artwork_style_guides()

    def folder_artwork_scope(self, identity, recursive):
        if type(recursive) is not bool:raise UserError('Choose explicit subfolder scope')
        folder=self.folder_node(identity)
        return dict(folder=folder,assets=self.folder_members(folder,recursive),recursive=recursive)

    def shared_artwork_preview(self, asset_ids, image, original=None, scope=None, expected=None):
        if not isinstance(asset_ids,list) or not asset_ids or any(not isinstance(a,str) for a in asset_ids) or len(asset_ids)!=len(set(asset_ids)):raise UserError('Choose exact selected artwork targets')
        expected=expected or {}
        if not isinstance(expected,dict) or set(expected)-set(asset_ids) or any(value is not None and (not isinstance(value,str) or not __import__('re').fullmatch(r'[a-f0-9]{64}',value)) for value in expected.values()):raise UserError('Choose only selected current artwork hashes')
        if scope:
            if not isinstance(scope,dict) or set(scope)!={'folder','recursive'}:raise UserError('Choose exact folder scope')
            available={a['id'] for a in self.folder_artwork_scope(scope['folder'],scope['recursive'])['assets']}
            if not set(asset_ids)<=available:raise UserError('Selected artwork targets left this folder scope')
        result=self.artwork_preview(asset_ids,'background','16:9',dict.fromkeys(asset_ids,image),dict.fromkeys(asset_ids,original) if original else None)
        for task in result['tasks']:
            if task['asset'] in expected and task['plan']['original']!=expected[task['asset']]:
                raise UserError('Current artwork changed after display; retained drafts need a fresh review')
        return result
