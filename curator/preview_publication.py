"""Separately approved additive local trailers on the shared file-operation queue."""

import os
import hashlib
from pathlib import Path, PurePosixPath
import re
import uuid
from urllib.parse import quote
from . import development, tools
from .errors import UserError
from .exclusive_install import install_exclusive_at
from .store import now

VIDEO_SUFFIXES = {'.mp4', '.mkv', '.mov', '.avi', '.m4v', '.ts', '.m2ts', '.wmv'}
EXTRA = re.compile(r'-(trailer|behindthescenes|deleted|featurette|interview|scene|short|other)$', re.I)


def safe_directory(path):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in [path, *path.parents]) or not path.is_dir():
        raise UserError('Trailer destination is missing or uses a symbolic link; inspect the mapping')
    stat = path.stat()
    return dict(device=stat.st_dev, inode=stat.st_ino)


def digest_at(directory_fd, name):
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    with os.fdopen(handle, 'rb') as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
        return digest.hexdigest()


class PreviewPublication:
    def preview_publication_target(self, task):
        asset = self.asset(task)
        library = self.library(asset['library'])
        if library['type'] != 'movie':
            raise UserError('Local trailer publication currently supports movies only')
        item = self.checked_client(library).item(asset['rating_key'])
        media = item.get('Media', [])
        if (
            item.get('type') != 'movie'
            or str(item.get('ratingKey')) != str(asset['rating_key'])
            or len(media) != 1
            or len(media[0].get('Part', [])) != 1
            or media[0]['Part'][0].get('file') != asset['plex_path']
        ):
            raise UserError('Plex movie, edition or file identity is ambiguous; rescan and review')
        section = item.get('librarySectionID')
        if section is not None and str(section) != str(library['key']):
            raise UserError('Plex item belongs to another library; rescan and review')
        guid = item.get('guid')
        guids = item.get('Guid') or []
        if (
            (guid is not None and (not isinstance(guid, str) or len(guid) > 2048))
            or not isinstance(guids, list)
            or len(guids) > 50
        ):
            raise UserError('Plex canonical movie identity is unsupported; rescan and review')
        if any(
            not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'] or len(row['id']) > 2048
            for row in guids
        ):
            raise UserError('Plex external movie identity is unsupported; rescan and review')
        external_guids = sorted({row['id'] for row in guids})
        folder = Path(asset['local_path']).parent
        directory = safe_directory(folder)
        for sibling in folder.iterdir():
            if (
                sibling != Path(asset['local_path'])
                and sibling.suffix.lower() in VIDEO_SUFFIXES
                and not EXTRA.search(sibling.stem)
            ):
                raise UserError('Use a dedicated movie/edition folder before publishing a trailer')
        roots = [str(row.get('plex_root', '')).rstrip('/') for row in library.get('mappings', [])]
        if str(PurePosixPath(asset['plex_path']).parent) in roots:
            raise UserError('Move this movie into its own mapped movie/edition folder before publishing')
        return asset, dict(
            server=library['server'],
            library=library['id'],
            rating_key=asset['rating_key'],
            edition=item.get('editionTitle'),
            guid=guid,
            external_guids=external_guids,
            plex_section=str(section) if section is not None else None,
            source=self.preview_source(asset),
            directory=directory,
        )

    def preview_publication_plan(self, identity, version):
        task = self.get_task(identity)
        if (
            type(version) is not int
            or version != task['version']
            or task['status'] not in {'awaiting_review', 'applied'}
        ):
            raise UserError('Reopen a completed preview before publication')
        output, _ = self.preview_candidate(identity)
        asset, target = self.preview_publication_target(task)
        self.check_busy_sources(task)
        if tools.digest(asset['local_path']) != output['source_hash']:
            raise UserError('Source bytes changed; review a fresh preview')
        filename = Path(asset['local_path']).stem + '-Curator-' + output['sha256'][:16] + '-trailer.mp4'
        destination = Path(asset['local_path']).with_name(filename)
        if destination.exists() or destination.is_symlink():
            raise UserError('This trailer destination already exists; inspect it instead of publishing again')
        plan = dict(
            id=uuid.uuid4().hex,
            record_type='preview_publication',
            task=identity,
            version=version,
            target=target,
            destination=str(destination),
            plex_destination=str(PurePosixPath(asset['plex_path']).with_name(filename)),
            sha256=output['sha256'],
            source_hash=output['source_hash'],
            status='review',
            created=now(),
            prior_trailers=sorted(p.name for p in destination.parent.iterdir() if p.stem.lower().endswith('-trailer')),
        )
        with self.store.transaction():
            self.store.put('settings', 'preview-publication:' + plan['id'], plan)
        return self.public_preview_publication(plan)

    def public_preview_publication(self, record):
        job = self.store.get('settings', record['file_job']) if record.get('file_job') else None
        return dict(
            id=record['id'],
            task=record['task'],
            title=self.get_task(record['task'])['title'],
            destination=record['plex_destination'],
            sha256=record['sha256'],
            edition=record['target']['edition'],
            status=record['status'],
            file_job=record.get('file_job'),
            phase=job.get('phase') if job else None,
            error=job.get('error') if job else None,
            association=record.get('association', 'not_saved'),
            prior_trailers=record.get('prior_trailers', []),
        )

    def get_preview_publication(self, identity):
        if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{32}', identity):
            raise UserError('Trailer publication not found')
        record = self.store.get('settings', 'preview-publication:' + identity)
        if not record or record.get('record_type') != 'preview_publication':
            raise UserError('Trailer publication not found')
        return record

    def check_preview_publication(self, record):
        task = self.get_task(record['task'])
        output, candidate = self.preview_candidate(task['id'])
        asset, target = self.preview_publication_target(task)
        if (
            task['version'] != record['version']
            or task['status'] not in {'awaiting_review', 'applied'}
            or target != record['target']
            or output['sha256'] != record['sha256']
            or tools.digest(asset['local_path']) != record['source_hash']
        ):
            raise UserError('Trailer approval is stale; review a new publication plan')
        self.check_busy_sources(task)
        destination = Path(record['destination'])
        if destination.exists() or destination.is_symlink():
            raise UserError('Trailer destination exists; inspect retained files, never replay automatically')
        development.check_path(destination)
        return candidate, destination

    def approve_preview_publication(self, identity, request_id):
        if not isinstance(request_id, str) or not re.fullmatch(r'[0-9a-fA-F-]{32,36}', request_id):
            raise UserError('Invalid trailer publication request')
        key = 'preview-publication-submit:' + request_id
        with self.lock:
            with self.store.transaction():
                existing = self.store.get('settings', key)
                if existing:
                    if existing['plan'] != identity:
                        raise UserError('Publication request belongs to another plan')
                    return self.public_preview_publication(self.get_preview_publication(identity))
                record = self.get_preview_publication(identity)
                if record['status'] != 'review':
                    raise UserError('Publication already submitted; inspect its retained receipt')
                self.check_preview_publication(record)
                for other in self.store.all('settings'):
                    if (
                        isinstance(other, dict)
                        and other.get('record_type') == 'preview_publication'
                        and other.get('destination') == record['destination']
                        and other['status'] not in {'review', 'abandoned_unattempted'}
                    ):
                        owner = self.store.get('settings', other.get('file_job')) if other.get('file_job') else None
                        old_stage = Path(other['destination']).with_name('.curator-trailer-' + other['id'] + '.partial')
                        unattempted = (
                            other['status'] == 'queued'
                            and not other.get('staging')
                            and owner
                            and owner.get('record_type') == 'file_operation'
                            and owner.get('operation') == 'preview_publish'
                            and owner.get('payload') == {'task': other['task'], 'publication': other['id']}
                            and owner.get('phase') in {'failed', 'interrupted', 'cancelled'}
                            and not Path(other['destination']).exists()
                            and not Path(other['destination']).is_symlink()
                            and not old_stage.exists()
                            and not old_stage.is_symlink()
                        )
                        if not unattempted:
                            raise UserError('Another publication owns this destination; inspect its receipt')
                        other.update(status='abandoned_unattempted', abandoned_at=now(), superseded_by=identity)
                        self.store.put('settings', 'preview-publication:' + other['id'], other)
                        self.store.event(
                            other['task'],
                            dict(
                                action='unattempted trailer publication superseded by fresh approval',
                                publication=other['id'],
                                replacement=identity,
                            ),
                        )
                job = dict(
                    id='file-operation:' + uuid.uuid4().hex,
                    record_type='file_operation',
                    operation='preview_publish',
                    payload=dict(task=record['task'], publication=identity),
                    library=record['target']['library'],
                    title=self.get_task(record['task'])['title'],
                    phase='waiting',
                    synchronous=False,
                    created=now(),
                    updated=now(),
                )
                record.update(status='queued', file_job=job['id'], approved_at=now())
                self.store.put('settings', job['id'], job)
                self.store.put('settings', 'preview-publication:' + identity, record)
                self.store.put('settings', key, dict(plan=identity, file_job=job['id']))
                self.store.event(record['task'], dict(action='trailer publication approved', publication=identity))
        self.start_file_queue()
        return self.public_preview_publication(record)

    def execute_preview_publication(self, payload):
        identity = payload['publication']
        record = self.get_preview_publication(identity)
        if record['status'] != 'queued':
            raise UserError('Trailer write was already attempted; inspect retained files')
        candidate, destination = self.check_preview_publication(record)
        stage = destination.with_name('.curator-trailer-' + identity + '.partial')
        record.update(status='attempted', staging=str(stage), attempted_at=now())
        with self.store.transaction():
            self.store.put('settings', 'preview-publication:' + identity, record)
        directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            stat = os.fstat(directory)
            if dict(device=stat.st_dev, inode=stat.st_ino) != record['target']['directory']:
                raise UserError('Trailer directory changed; inspect retained files')
            staged = os.open(stage.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            with candidate.open('rb') as source, os.fdopen(staged, 'wb') as output:
                for chunk in iter(lambda: source.read(8 * 1024 * 1024), b''):
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if digest_at(directory, stage.name) != record['sha256']:
                raise UserError('Staged trailer differs; retained staging needs inspection')
            self.check_preview_publication(record)
            install_exclusive_at(directory, stage.name, destination.name)
            os.fsync(directory)
            if digest_at(directory, destination.name) != record['sha256']:
                raise UserError('Installed trailer differs; inspect the retained receipt')
            if safe_directory(destination.parent) != record['target']['directory']:
                raise UserError('Trailer directory moved; inspect the retained receipt')
        finally:
            os.close(directory)
        record.update(status='local_saved', association='pending', saved_at=now())
        with self.store.transaction():
            self.store.put('settings', 'preview-publication:' + identity, record)
            self.store.event(
                record['task'], dict(action='trailer saved locally; Plex association pending', publication=identity)
            )
        return self.public_preview_publication(record)

    def reconcile_preview_publication(self, identity):
        record = self.get_preview_publication(identity)
        if record['status'] != 'local_saved':
            raise UserError('Only a verified local save can check Plex association')
        destination = Path(record['destination'])
        if (
            safe_directory(destination.parent) != record['target']['directory']
            or tools.digest(destination) != record['sha256']
        ):
            raise UserError('Saved trailer changed; inspect the retained receipt')
        _, target = self.preview_publication_target(self.get_task(record['task']))
        if target != record['target']:
            raise UserError('Movie identity changed; association cannot be verified')
        client = self.checked_client(self.library(target['library']))
        item = client.request(
            '/library/metadata/' + quote(str(target['rating_key']), safe=''), params={'includeExtras': 1}
        ).get('Metadata', [])
        extras = item[0].get('Extras', {}).get('Metadata', []) if len(item) == 1 else []
        verified = any(
            extra.get('extraType') in {1, '1'}
            and any(
                part.get('file') == record['plex_destination']
                for media in extra.get('Media', [])
                for part in media.get('Part', [])
            )
            for extra in extras
        )
        if verified:
            record.update(association='verified', verified_at=now())
            with self.store.transaction():
                self.store.put('settings', 'preview-publication:' + identity, record)
        return self.public_preview_publication(record)
