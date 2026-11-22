"""Manual NFO/artwork packages. Fresh review snapshots, existing File operations.

Preparing a manifest performs destination reads only. No Plex edits or refreshes,
media renames, image generation or automatic execution are part of this workflow.
"""

import copy
from datetime import date
import json
import os
from pathlib import Path
import re
import threading
import uuid
import xml.etree.ElementTree as ET

from . import development, tools
from .errors import UserError
from .history import acting, current_initiator
from .nfo_sidecars import (
    image_info,
    image_name,
    plan_sidecar,
    sha256,
    write_sidecar,
    inspect_sidecar,
    _read_at,
    verify_destination,
)
from .paths import map_path, media_presence
from .plex import Plex
from .store import now

VERSION = 1
MAX_ITEMS = 2000
MAX_ITEM_PREVIEW = 256 * 1024
MAX_PREVIEW = 8 * 1024 * 1024
MOVIES = {'.mkv', '.mp4', '.m4v', '.mov', '.avi', '.mpg', '.mpeg', '.wmv', '.webm', '.ts', '.m2ts'}
FIELDS = (
    'guid',
    'editionTitle',
    'title',
    'originalTitle',
    'summary',
    'tagline',
    'originallyAvailableAt',
    'year',
    'studio',
    'Genre',
    'Collection',
    'Label',
    'Guid',
    'Director',
    'Writer',
    'Role',
    'rating',
    'ratingImage',
    'audienceRating',
    'audienceRatingImage',
    'userRating',
    'contentRating',
    'duration',
)
KNOWN_TAGS = {
    'title',
    'originaltitle',
    'plot',
    'tagline',
    'premiered',
    'year',
    'studio',
    'genre',
    'director',
    'credits',
    'actor',
    'mpaa',
    'runtime',
    'ratings',
}


def revision(value):
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    )


def metadata(item):
    return {key: copy.deepcopy(item[key]) for key in FIELDS if key in item}


def catalog_id(value):
    match = re.fullmatch(r'(imdb|tmdb|tvdb)://(.+)', str(value))
    if not match:
        return None
    kind, identity = match.groups()
    return (kind, identity) if re.fullmatch(r'tt\d+' if kind == 'imdb' else r'\d+', identity) else None


def parse_nfo(raw):
    if len(raw) > 2 * 1024 * 1024 or re.search(rb'<!\s*(?:DOCTYPE|ENTITY)', raw, re.I):
        raise UserError('Existing NFO contains unsupported XML declarations or exceeds 2 MiB')
    try:
        raw = raw.decode('utf-8-sig')
        root = ET.fromstring(raw, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    except (ET.ParseError, ValueError, UnicodeError):
        raise UserError('Existing NFO is not safe, complete XML') from None
    if root.tag != 'movie':
        raise UserError('Existing NFO is not a movie record')
    return root


def text(value):
    value = str(value)
    if any(
        not (c in '\t\n\r' or 0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF)
        for c in value
    ):
        raise UserError('Metadata contains characters that XML 1.0 cannot represent')
    return value


def movie_xml(item, previous=None):
    """Deterministic UTF-8 movie XML; existing unknown elements/IDs survive updates."""
    root = parse_nfo(previous) if previous else ET.Element('movie')
    for child in root:
        if child.tag not in KNOWN_TAGS:
            continue
        if child.attrib or child.tag not in {'actor', 'ratings'} and list(child):
            raise UserError('Existing NFO extends a generated field; keep it unchanged rather than losing unknown XML')
        if child.tag == 'actor' and any(
            row.tag not in {'name', 'role', 'order'} or row.attrib or list(row) for row in child
        ):
            raise UserError('Existing NFO has additional actor data; keep it unchanged rather than losing unknown XML')
        if child.tag == 'ratings' and any(
            row.tag != 'rating'
            or set(row.attrib) != {'name', 'max'}
            or any(value.tag != 'value' or value.attrib or list(value) for value in row)
            for row in child
        ):
            raise UserError('Existing NFO has additional rating data; keep it unchanged rather than losing unknown XML')
    for child in list(root):
        if child.tag in KNOWN_TAGS:
            root.remove(child)

    def add(tag, value, parent=root):
        if value is not None and value != '':
            return _add(parent, tag, value)
        return None

    for source, tag in [
        ('title', 'title'),
        ('originalTitle', 'originaltitle'),
        ('summary', 'plot'),
        ('tagline', 'tagline'),
        ('studio', 'studio'),
        ('contentRating', 'mpaa'),
    ]:
        add(tag, item.get(source))
    released = item.get('originallyAvailableAt')
    if released:
        try:
            released = date.fromisoformat(str(released)).isoformat()
        except ValueError:
            released = None
        add('premiered', released)
    year = item.get('year')
    if isinstance(year, int) and not isinstance(year, bool) and 1 <= year <= 9999:
        add('year', year)
    duration = item.get('duration')
    if isinstance(duration, (float, int)) and not isinstance(duration, bool) and duration > 0:
        add('runtime', int(duration / 60000))
    for source, tag in [('Genre', 'genre'), ('Director', 'director'), ('Writer', 'credits')]:
        for row in item.get(source, []):
            if row.get('tag'):
                add(tag, row['tag'])
    for index, row in enumerate(item.get('Role', [])):
        if not row.get('tag'):
            continue
        actor = ET.SubElement(root, 'actor')
        add('name', row['tag'], actor)
        add('role', row.get('role'), actor)
        add('order', index, actor)
        # Plex-relative/token-bearing portraits cannot be made portable merely
        # by copying the URL. Keep working portraits unchanged in Plex/Curator.
    existing_ids = {row.get('type'): row.text for row in root.findall('uniqueid')}
    for row in item.get('Guid', []):
        pair = catalog_id(row.get('id', ''))
        if not pair:
            continue
        kind, value = pair
        if kind in existing_ids:
            if existing_ids[kind] != value:
                raise UserError('An existing NFO catalog identifier conflicts with current metadata')
        else:
            _add(root, 'uniqueid', value).set('type', kind)
            existing_ids[kind] = value
    ratings = ET.Element('ratings')
    for key, source_key in [('rating', 'ratingImage'), ('audienceRating', 'audienceRatingImage')]:
        value, provider = item.get(key), str(item.get(source_key, '')).split('://')[0]
        if (
            isinstance(value, (float, int))
            and not isinstance(value, bool)
            and 0 <= value <= 10
            and provider in {'imdb', 'rottentomatoes', 'themoviedb'}
        ):
            rating = ET.SubElement(ratings, 'rating', {'name': provider, 'max': '10'})
            _add(rating, 'value', value)
    if list(ratings):
        root.append(ratings)
    ET.indent(root, space='  ')
    generated = ET.tostring(root, encoding='utf-8', xml_declaration=True, short_empty_elements=True) + b'\n'
    parse_nfo(generated)
    return generated


def _add(parent, tag, value):
    element = ET.SubElement(parent, tag)
    element.text = text(value)
    return element


def xml_differences(previous, proposed):
    def values(raw):
        result = {}
        if raw is not None:
            for child in parse_nfo(raw):
                if child.tag in KNOWN_TAGS or child.tag == 'uniqueid':
                    result.setdefault(child.tag, []).append(
                        ' · '.join(value.strip() for value in child.itertext() if value.strip())
                    )
        return result

    before, after = values(previous), values(proposed)
    return [
        dict(field=key, before=before.get(key, []), after=after.get(key, []))
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    ]


class NfoExports:
    def nfo_exports(self, library):
        self.library(library)
        rows = [
            r
            for r in self.store.all('settings')
            if isinstance(r, dict) and r.get('record_type') == 'nfo_export' and r.get('library') == library
        ]
        return dict(
            exports=[
                dict(id=r['id'], phase=r['phase'], created=r['created'], count=len(r['assets']))
                for r in sorted(rows, key=lambda r: r['created'], reverse=True)[:20]
            ]
        )

    def nfo_manifest(self, identity):
        record = self.store.get('settings', identity)
        if not isinstance(record, dict) or record.get('record_type') != 'nfo_export':
            raise UserError('NFO export preview was not found')
        if record.get('job') and record.get('phase') == 'queued':
            job = self.store.get('settings', record['job'], {})
            if job.get('phase') == 'cancelled':
                record.update(
                    phase='cancelled',
                    error='Remaining export work was cancelled. Existing verified files and outcomes are retained.',
                )
        return record

    def _save_nfo(self, record):
        record['updated'] = now()
        with self.store.transaction():
            self.store.put('settings', record['id'], record)

    def recover_nfo_exports(self):
        for record in self.store.all('settings'):
            if (
                isinstance(record, dict)
                and record.get('record_type') == 'nfo_export'
                and record.get('phase') in {'preparing', 'queued', 'running'}
            ):
                record.update(
                    phase='interrupted',
                    error='Restarted. Inspect file outcomes and prepare a fresh preview before retrying.',
                )
                self._save_nfo(record)

    def create_nfo_preview(self, data, background=True):
        library = self.library(data.get('library'))
        scope = data.get('scope', 'selected')
        rows = [a for a in self.store.all('assets') if a.get('library') == library['id'] and a.get('present', True)]
        if scope == 'selected':
            ids = data.get('assets')
            if (
                not isinstance(ids, list)
                or not ids
                or any(not isinstance(key, str) for key in ids)
                or len(ids) != len(set(ids))
            ):
                raise UserError('Select current files in this library')
            rows = [a for a in rows if a['id'] in ids]
            if len(rows) != len(ids):
                raise UserError('Some selected files changed or are not in this library')
        elif scope == 'folder':
            folder = data.get('folder')
            if not isinstance(folder, str):
                raise UserError('Choose an exact media folder')
            rows = [a for a in rows if str(Path(a['plex_path']).parent) == folder]
        elif scope != 'library':
            raise UserError('Choose selected files, an exact folder or the library')
        filter_by = data.get('filter', 'all')
        if filter_by not in {'all', 'missing', 'changed', 'failed'}:
            raise UserError('Choose an export filter')
        if not rows or len(rows) > MAX_ITEMS:
            raise UserError('Choose between 1 and 2,000 files; split larger libraries by folder')
        record = dict(
            id='nfo-export:' + uuid.uuid4().hex,
            record_type='nfo_export',
            version=VERSION,
            library=library['id'],
            scope=scope,
            filter=filter_by,
            phase='preparing',
            assets=[a['id'] for a in sorted(rows, key=lambda a: (a['plex_path'], a['id']))],
            items=[],
            preview_bytes=0,
            created=now(),
            initiator=current_initiator(),
        )
        with self.lock:
            self._save_nfo(record)
            self.active.add(record['id'])

        def prepare():
            try:
                with acting(record['initiator']):
                    self._prepare_nfo(record['id'])
            except Exception:
                with self.lock:
                    current = self.nfo_manifest(record['id'])
                    if current['phase'] == 'preparing':
                        current.update(
                            phase='failed',
                            error='Preview preparation failed; no destination files were written. Prepare a fresh preview.',
                        )
                        self._save_nfo(current)
            finally:
                with self.lock:
                    self.active.discard(record['id'])

        if background:
            threading.Thread(target=prepare, daemon=True).start()
        else:
            prepare()
        return self.nfo_manifest(record['id'])

    def cancel_nfo_preview(self, identity):
        with self.lock:
            record = self.nfo_manifest(identity)
            if record['phase'] not in {'preparing', 'ready'}:
                raise UserError('Only an unqueued preview can be cancelled')
            record['phase'] = 'cancelled'
            self._save_nfo(record)
            return record

    def _nfo_source(self, asset):
        library = self.library(asset['library'])
        path = map_path(asset['plex_path'], library.get('mappings', []))
        presence = media_presence(asset['plex_path'], library.get('mappings', []), asset.get('fingerprint'))
        if (
            presence['state'] != 'present'
            or str(path) != asset.get('local_path')
            or tools.fingerprint(path) != asset.get('fingerprint')
        ):
            raise UserError('Source file or mapping changed; refresh the library first')
        if library.get('type') != 'movie':
            raise UserError('TV/show/episode NFO export is not supported by this movie workflow')
        if asset.get('artwork_target') or asset.get('multipart'):
            raise UserError('Only ordinary single-part media items can be exported')
        self.check_busy_sources(dict(id='nfo-export-check', asset=asset['id'], plan={}))
        if development.root():
            item, client = copy.deepcopy(asset.get('item', {})), None
        else:
            client = self.checked_client(library)
            item = client.item(asset['rating_key'])
        parts = [part.get('file') for media in item.get('Media', []) for part in media.get('Part', [])]
        if (
            str(item.get('ratingKey')) != str(asset['rating_key'])
            or item.get('type') != 'movie'
            or parts != [asset['plex_path']]
        ):
            raise UserError('Current Plex identity/edition/parts do not uniquely match this file')
        if item.get('librarySectionID') is not None and str(item['librarySectionID']) != str(library['key']):
            raise UserError('Current Plex library identity changed')
        if metadata(asset.get('item', {})) != metadata(item):
            raise UserError(
                'Saved Curator metadata differs from current Plex metadata; refresh and review before exporting'
            )
        if not isinstance(item.get('title'), str) or not item['title'].strip():
            raise UserError('Save a title in metadata before exporting this item')
        selected = {kind: Plex.artwork_path(item, kind) for kind in Plex.ARTWORK}
        source = dict(
            asset=asset['id'],
            library=library['id'],
            rating_key=asset['rating_key'],
            plex_path=asset['plex_path'],
            local_path=str(path),
            fingerprint=tools.fingerprint(path),
            mappings=copy.deepcopy(library.get('mappings', [])),
            metadata=metadata(item),
            artwork=selected,
            updated_at=item.get('updatedAt'),
        )
        if development.root():
            source['development_artwork'] = copy.deepcopy(asset.get('development_artwork', {}))
        return source, item, client

    def _nfo_image(self, source, client, kind):
        if development.root():
            path = source.get('development_artwork', {}).get(kind)
            if not path:
                return None
            return development.check_path(path).read_bytes()
        if not source['artwork'].get(kind):
            return None
        return client.image(source['rating_key'], kind)

    def _verify_nfo_art_layout(self, file, source):
        folder = Path(source['local_path']).parent
        siblings = [p for p in folder.iterdir() if p.suffix.lower() in MOVIES]
        if len(siblings) != 1 or siblings[0].resolve() != Path(source['local_path']):
            raise UserError('Media folder is now shared or ambiguous; prepare a fresh preview')
        if any(
            p.stem.casefold() == Path(file['name']).stem.casefold()
            and p.suffix.lower() in {'.png', '.jpg', '.jpeg'}
            and p.name != file['name']
            for p in folder.iterdir()
        ):
            raise UserError('Another artwork filename now occupies this slot; prepare a fresh preview')

    def _nfo_item(self, identity):
        asset = self.asset({'asset': identity})
        source, item, client = self._nfo_source(asset)
        folder = Path(source['local_path']).parent
        warnings = []
        # Generic artwork names are safe only when the actual destination folder
        # contains exactly this media file, including files not scanned by Plex.
        siblings = [p for p in folder.iterdir() if p.suffix.lower() in MOVIES]
        single = len(siblings) == 1 and siblings[0].resolve() == Path(source['local_path'])
        nfo_name = Path(source['local_path']).stem + '.nfo'
        old = inspect_sidecar(folder, nfo_name)
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            observed = _read_at(fd, nfo_name)
        finally:
            os.close(fd)
        previous = observed[1] if observed else None
        if (observed[0] if observed else None) != old['existing']:
            raise UserError('Existing NFO changed during preview')
        receipt = self.store.get('settings', 'nfo-receipt:' + identity, {})
        owned = bool(
            old['existing']
            and receipt.get('nfo_sha256') == old['existing']['sha256']
            and receipt.get('source_asset') == identity
        )
        xml = movie_xml(item, previous if owned else None)
        plan = plan_sidecar(folder, nfo_name, xml, update=owned)
        plan.update(kind='nfo', source='Current saved metadata', content=xml.decode('utf-8'), owned=owned)
        if plan['action'] == 'kept':
            plan['reason'] = 'Existing NFO is not a verified Curator-written version. It will be kept unchanged.'
        files = [plan]
        if item.get('Collection'):
            warnings.append(
                'Collection relationships are retained in Curator; multi-collection NFO mapping is not certified.'
            )
        if item.get('Label'):
            warnings.append('Labels/tags are retained in Curator and omitted from this NFO.')
        if item.get('userRating') is not None:
            warnings.append('Personal Plex ratings are retained in Curator/Plex and omitted from this NFO.')
        if any(not catalog_id(row.get('id', '')) for row in item.get('Guid', [])):
            warnings.append(
                'Unverified/custom identifiers are omitted; stable Curator identity remains in the export receipt.'
            )
        for key, provider in [('rating', 'ratingImage'), ('audienceRating', 'audienceRatingImage')]:
            if item.get(key) is not None and str(item.get(provider, '')).split('://')[0] not in {
                'imdb',
                'rottentomatoes',
                'themoviedb',
            }:
                warnings.append('A rating with an unverified source or scale is omitted.')
        if any(row.get('thumb') for row in item.get('Role', [])):
            warnings.append(
                'Cast names, roles and order are exported. Portrait references are omitted because durable credential-free import was not verified; existing portraits are unchanged.'
            )
        for kind in Plex.ARTWORK:
            try:
                data = self._nfo_image(source, client, kind)
                if data is None:
                    files.append(dict(kind=kind, action='missing', reason='No currently selected artwork'))
                    continue
                info = image_info(data)
                name = image_name(kind, info)
                if not single:
                    files.append(
                        dict(
                            kind=kind,
                            action='blocked',
                            reason='Shared/ambiguous media folder; generic artwork would affect other videos',
                        )
                    )
                    continue
                # An alternate extension is the same artwork slot, not a second
                # create-missing destination. Never shadow another selection.
                alternates = [
                    p.name
                    for p in folder.iterdir()
                    if p.stem.casefold() == Path(name).stem.casefold()
                    and p.suffix.lower() in {'.jpg', '.jpeg', '.png'}
                    and p.name != name
                ]
                if alternates:
                    files.append(
                        dict(
                            kind=kind,
                            action='blocked',
                            reason='An alternate artwork filename/extension already occupies this slot',
                        )
                    )
                    continue
                art = plan_sidecar(folder, name, data)
                art.update(kind=kind, source='Current selected artwork', format=info)
                files.append(art)
                if kind == 'cover' and info['width'] >= info['height']:
                    warnings.append(
                        'Current cover is landscape. Its original bytes are retained without crop, stretch or regeneration.'
                    )
            except (OSError, ValueError):
                files.append(
                    dict(
                        kind=kind,
                        action='blocked',
                        reason='Current selected artwork could not be read or is not a supported JPEG/PNG',
                    )
                )
        return dict(
            asset=identity,
            title=item.get('title', asset.get('title', 'Media item')),
            source=source,
            source_revision=revision(source),
            files=files,
            warnings=warnings,
            phase='ready',
            field_values=metadata(item),
            previous_nfo=previous.decode('utf-8', errors='replace') if previous else None,
            differences=xml_differences(previous if owned else None, xml),
        )

    def _prepare_nfo(self, identity):
        record = self.nfo_manifest(identity)
        for aid in record['assets']:
            if self.nfo_manifest(identity)['phase'] != 'preparing':
                return
            try:
                row = self._nfo_item(aid)
                nfo = row['files'][0]
                receipt = self.store.get('settings', 'nfo-receipt:' + aid, {})
                include = (
                    record['filter'] == 'all'
                    or record['filter'] == 'missing'
                    and nfo['existing'] is None
                    or record['filter'] == 'changed'
                    and nfo['action'] in {'create', 'update'}
                    or record['filter'] == 'failed'
                    and receipt.get('phase') in {'partial', 'failed', 'interrupted'}
                )
                if not include:
                    row.update(phase='skipped', reason='Outside the chosen filter')
            except (OSError, ValueError) as error:
                row = dict(
                    asset=aid,
                    title='Unavailable item',
                    phase='blocked',
                    reason=str(error) if isinstance(error, UserError) else 'Source or destination could not be read',
                    files=[],
                )
            with self.lock:
                current = self.nfo_manifest(identity)
                if current['phase'] != 'preparing':
                    return
                size = len(json.dumps(row, ensure_ascii=False).encode())
                if size > MAX_ITEM_PREVIEW or current.get('preview_bytes', 0) + size > MAX_PREVIEW:
                    row = dict(
                        asset=aid,
                        title='Preview limit reached',
                        phase='blocked',
                        reason='Metadata/XML exceeds the bounded preview budget. Export a smaller scope or simplify the metadata first.',
                        files=[],
                    )
                    size = len(json.dumps(row).encode())
                current['items'].append(row)
                current['preview_bytes'] = current.get('preview_bytes', 0) + size
                self._save_nfo(current)
        with self.lock:
            current = self.nfo_manifest(identity)
            if current['phase'] == 'preparing':
                current.update(phase='ready', review_revision=revision(current['items']))
                self._save_nfo(current)

    def queue_nfo_export(self, data):
        with self.lock:
            record = self.nfo_manifest(data.get('id'))
            if record['phase'] != 'ready' or data.get('revision') != record.get('review_revision'):
                raise UserError('NFO export preview changed; prepare a fresh review')
            selected = data.get('assets')
            updates = data.get('updates', [])
            eligible = {row['asset']: row for row in record['items'] if row['phase'] == 'ready'}
            if (
                not isinstance(selected, list)
                or not selected
                or len(selected) != len(set(selected))
                or any(key not in eligible for key in selected)
            ):
                raise UserError('Select reviewed eligible items')
            if (
                not isinstance(updates, list)
                or len(updates) != len(set(updates))
                or any(key not in selected or eligible[key]['files'][0]['action'] != 'update' for key in updates)
            ):
                raise UserError('Approve existing Curator-written NFO updates separately per item')
            for aid in selected:
                fresh, _, client = self._nfo_source(self.asset({'asset': aid}))
                if revision(fresh) != eligible[aid]['source_revision']:
                    raise UserError('A source changed since preview; prepare a fresh review')
                for file in eligible[aid]['files']:
                    if not file.get('name'):
                        continue
                    fd = os.open(file['directory'], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        verify_destination(file, fd)
                    finally:
                        os.close(fd)
                    if file['kind'] != 'nfo':
                        self._verify_nfo_art_layout(file, fresh)
                        if sha256(self._nfo_image(fresh, client, file['kind'])) != file['sha256']:
                            raise UserError('Selected artwork bytes changed since preview; prepare a fresh review')
            record.update(
                phase='queued',
                selected=selected,
                approved_updates=updates,
                approved_by=current_initiator(),
                approved=now(),
            )

            # Persist admission and manifest together. Queuing never starts a queue.
            def admit(job):
                record['job'] = job['id']
                record['updated'] = now()
                self.store.put('settings', record['id'], record)

            self.queue_file_operation(
                'nfo_export',
                dict(plan=record['id'], library=record['library'], title=f'NFO export · {len(selected)} items'),
                background=True,
                start=False,
                admit=admit,
            )
            self.store.record(
                'nfo_export_queued', f'NFO package approved: {len(selected)} items', library=record['library']
            )
            return record

    def execute_nfo_export(self, identity):
        record = self.nfo_manifest(identity)
        if record['phase'] != 'queued':
            raise UserError('Export is no longer queued; inspect outcomes and prepare a fresh preview')
        record['phase'] = 'running'
        self._save_nfo(record)
        for row in record['items']:
            if row['asset'] not in record['selected'] or row['phase'] != 'ready':
                continue
            if self.file_queue_paused():
                record['phase'] = 'queued'
                self._save_nfo(record)
                return dict(manifest=identity, phase='paused', items=len(record['selected']))
            try:
                with self.lock:
                    fresh, _, client = self._nfo_source(self.asset({'asset': row['asset']}))
                    if revision(fresh) != row['source_revision']:
                        raise UserError('Source metadata, artwork, file or mapping changed since review')

                    def verify():
                        check, _, _ = self._nfo_source(self.asset({'asset': row['asset']}))
                        if revision(check) != row['source_revision']:
                            raise UserError('Source changed during export; prepare a fresh preview')

                    for file in row['files']:
                        if file['action'] in {'missing', 'blocked'}:
                            continue
                        if file['action'] == 'update' and row['asset'] not in record['approved_updates']:
                            file['outcome'] = dict(state='kept', reason='Existing NFO update not approved')
                        else:
                            data = (
                                file['content'].encode('utf-8')
                                if file['kind'] == 'nfo'
                                else self._nfo_image(fresh, client, file['kind'])
                            )

                            def verify_file():
                                verify()
                                if file['kind'] != 'nfo':
                                    self._verify_nfo_art_layout(file, fresh)

                            file['outcome'] = write_sidecar(file, data, verify_file)
                        self._save_nfo(record)
                    incomplete = row['warnings'] or any(
                        f['action'] in {'missing', 'blocked'} or f.get('outcome', {}).get('state') == 'kept'
                        for f in row['files']
                    )
                    row['phase'] = 'partial' if incomplete else 'complete'
            except Exception as error:
                row.update(
                    phase='failed',
                    error=str(error)
                    if isinstance(error, UserError)
                    else 'A sidecar could not be committed. Inspect existing/retained files before retrying.',
                )
            nfo = row['files'][0] if row['files'] else {}
            outcome = nfo.get('outcome', {})
            receipt = dict(
                source_asset=row['asset'],
                manifest=record['id'],
                phase=row['phase'],
                source_revision=row.get('source_revision'),
                outcomes=copy.deepcopy(row['files']),
                updated=now(),
            )
            # Ownership is earned only by an actual verified create/update (or a
            # verified unchanged file already owned by this stable asset).
            if (
                outcome.get('state') in {'created', 'updated'}
                or outcome.get('state') == 'unchanged'
                and nfo.get('owned')
            ):
                receipt['nfo_sha256'] = nfo['sha256']
            elif outcome.get('state') == 'kept' and nfo.get('owned'):
                receipt['nfo_sha256'] = nfo['existing']['sha256']
            with self.store.transaction():
                self.store.put('settings', 'nfo-receipt:' + row['asset'], receipt)
                record['updated'] = now()
                self.store.put('settings', record['id'], record)
        record.update(
            phase='partial'
            if any(
                r['phase'] in {'partial', 'failed', 'blocked'}
                for r in record['items']
                if r['asset'] in record['selected']
            )
            else 'complete',
            finished=now(),
        )
        self._save_nfo(record)
        self.store.record('nfo_export_finished', 'NFO package ' + record['phase'], library=record['library'])
        return dict(manifest=identity, phase=record['phase'], items=len(record['selected']))
