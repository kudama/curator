"""Reviewed media-adjacent sidecars: real formats, no overwrite and retained updates.

All public planning helpers are read-only. The writer admits only the reviewed
directory/file identities, stages complete bytes on that filesystem, and installs
with an exclusive directory-relative install (including Darwin SMB). Updating is
explicit: move the observed old file to
a private retention directory first, then use the same no-overwrite installation.
A concurrent writer can block our install, but its file is never overwritten.
"""

import hashlib
import errno
import os
from pathlib import Path
import stat
import struct
import uuid
import zlib

from . import development
from .errors import UserError
from .exclusive_install import install_exclusive_at

MAX_SIDECAR = 32 * 1024 * 1024
IMAGE_NAMES = dict(cover='poster', background='background', square='square', logo='logo')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _name(name):
    if not isinstance(name, str) or not name or Path(name).name != name or name in {'.', '..'}:
        raise UserError('Choose a sidecar filename without a path')
    if any(ord(c) < 32 for c in name) or '/' in name or '\\' in name:
        raise UserError('Invalid sidecar filename')
    return name


def image_info(data):
    """Inspect source format/geometry without converting, cropping or decoding it."""
    if not isinstance(data, bytes) or not data or len(data) > MAX_SIDECAR:
        raise UserError('Selected artwork is missing or exceeds 32 MiB')
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        at, dimensions, ended, alpha = 8, None, False, False
        while at + 12 <= len(data):
            length = struct.unpack('>I', data[at : at + 4])[0]
            end = at + length + 12
            if end > len(data):
                raise UserError('Selected PNG artwork is incomplete')
            kind, body = data[at + 4 : at + 8], data[at + 8 : end - 4]
            if zlib.crc32(kind + body) & 0xFFFFFFFF != struct.unpack('>I', data[end - 4 : end])[0]:
                raise UserError('Selected PNG artwork has an invalid checksum')
            if kind == b'IHDR':
                if at != 8 or length != 13 or dimensions:
                    raise UserError('Selected PNG artwork has an invalid header')
                width, height, _, color, _, _, _ = struct.unpack('>IIBBBBB', body)
                dimensions, alpha = (width, height), color in {4, 6}
            if kind == b'tRNS':
                alpha = True
            if kind == b'IEND':
                ended = True
                break
            at = end
        if not dimensions or not ended or not all(0 < n <= 100000 for n in dimensions):
            raise UserError('Selected PNG artwork is incomplete')
        return dict(extension='png', width=dimensions[0], height=dimensions[1], alpha=alpha)
    if data.startswith(b'\xff\xd8\xff'):
        at = 2
        while at + 4 <= len(data):
            if data[at] != 255:
                break
            while at < len(data) and data[at] == 255:
                at += 1
            if at >= len(data):
                break
            marker = data[at]
            at += 1
            if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
                continue
            if at + 2 > len(data):
                break
            length = struct.unpack('>H', data[at : at + 2])[0]
            if length < 2 or at + length > len(data):
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if length >= 7:
                    height, width = struct.unpack('>HH', data[at + 3 : at + 7])
                    if width and height and data.endswith(b'\xff\xd9'):
                        return dict(extension='jpg', width=width, height=height, alpha=False)
                break
            if marker == 0xDA:
                break
            at += length
    raise UserError('Selected artwork is not a supported PNG or JPEG')


def image_name(kind, info):
    if kind not in IMAGE_NAMES:
        raise UserError('Unknown sidecar artwork kind')
    if kind == 'logo' and info['extension'] != 'png':
        raise UserError('A logo sidecar must retain PNG bytes')
    return IMAGE_NAMES[kind] + '.' + info['extension']


def directory_identity(folder):
    folder = Path(folder)
    if not folder.is_absolute() or folder.is_symlink() or folder.resolve() != folder or not folder.is_dir():
        raise UserError('Media folder changed or is unavailable')
    development.check_path(folder)
    current = folder.stat()
    return dict(device=current.st_dev, inode=current.st_ino)


def _read_at(fd, name):
    try:
        handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        return None
    except OSError:
        raise UserError('A sidecar is not an accessible regular file') from None
    with os.fdopen(handle, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SIDECAR:
            raise UserError('A sidecar is not a supported regular file under 32 MiB')
        data = stream.read(MAX_SIDECAR + 1)
        after = os.fstat(stream.fileno())
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns')
    if len(data) > MAX_SIDECAR or any(getattr(before, f) != getattr(after, f) for f in fields):
        raise UserError('A sidecar changed while it was read')
    return dict(
        sha256=sha256(data), bytes=len(data), device=after.st_dev, inode=after.st_ino, modified=after.st_mtime_ns
    ), data


def inspect_sidecar(folder, name):
    """Capture destination state without writing; case collisions are conflicts."""
    name = _name(name)
    parent = directory_identity(folder)
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        collisions = [n for n in os.listdir(fd) if n.casefold() == name.casefold() and n != name]
        if collisions:
            raise UserError('A differently capitalized sidecar already occupies this filename')
        result = _read_at(fd, name)
        return dict(directory=str(folder), parent=parent, name=name, existing=result[0] if result else None)
    finally:
        os.close(fd)


def plan_sidecar(folder, name, data, update=False):
    if not isinstance(data, bytes) or len(data) > MAX_SIDECAR:
        raise UserError('Sidecar contents exceed the supported size')
    planned = inspect_sidecar(folder, name)
    planned.update(sha256=sha256(data), bytes=len(data))
    old = planned['existing']
    planned['action'] = (
        'create'
        if old is None
        else 'unchanged'
        if old['sha256'] == planned['sha256']
        else 'update'
        if update
        else 'kept'
    )
    if planned['action'] == 'update':
        planned['retention'] = '.curator-retained-' + uuid.uuid4().hex
    return planned


def verify_destination(planned, fd):
    current = os.fstat(fd)
    if dict(device=current.st_dev, inode=current.st_ino) != planned['parent']:
        raise UserError('Media folder identity changed; make a new export preview')
    name = _name(planned['name'])
    if any(n.casefold() == name.casefold() and n != name for n in os.listdir(fd)):
        raise UserError('Sidecar filename now collides; make a new export preview')
    current = _read_at(fd, name)
    if (current[0] if current else None) != planned['existing']:
        raise UserError('Sidecar changed since review; make a new export preview')
    return current[1] if current else None


def write_sidecar(planned, data, verify_source=lambda: None):
    """Commit reviewed bytes only. Return an outcome; retain every replaced byte.

    An update can leave the destination absent on interruption, with the previous
    bytes in its named retention directory. That is an inspectable failure, never
    an automatic retry. No existing destination is overwritten by our install.
    """
    if not isinstance(data, bytes) or len(data) != planned['bytes'] or sha256(data) != planned['sha256']:
        raise UserError('Sidecar source bytes changed since preview')
    folder = Path(planned['directory'])
    directory_identity(folder)
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = '.curator-stage-' + uuid.uuid4().hex
    try:
        previous = verify_destination(planned, fd)
        verify_source()
        if planned['action'] in {'kept', 'unchanged'}:
            if directory_identity(folder) != planned['parent']:
                raise UserError('Media folder pathname changed; make a new export preview')
            return dict(state=planned['action'], sha256=(planned['existing'] or {}).get('sha256'))
        if planned['action'] not in {'create', 'update'}:
            raise UserError('Unsupported sidecar operation')
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=fd)
        with os.fdopen(handle, 'wb') as stage:
            stage.write(data)
            stage.flush()
            os.fsync(stage.fileno())
        verify_source()
        verify_destination(planned, fd)
        retained = None
        if planned['action'] == 'update':
            retained = _name(planned['retention'])
            os.mkdir(retained, 0o700, dir_fd=fd)
            backup_fd = os.open(retained, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                # Keep a separate immutable copy: an external open file descriptor
                # may still mutate the inode after we move it out of the way.
                saved = os.open('reviewed-original', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=backup_fd)
                with os.fdopen(saved, 'wb') as out:
                    out.write(previous)
                    out.flush()
                    os.fsync(out.fileno())
                os.rename(planned['name'], 'observed-original', src_dir_fd=fd, dst_dir_fd=backup_fd)
                moved = _read_at(backup_fd, 'observed-original')
                os.fsync(backup_fd)
                os.fsync(fd)
                if not moved or moved[0] != planned['existing']:
                    # Restore the observed file only if nobody installed another.
                    try:
                        os.link(
                            'observed-original',
                            planned['name'],
                            src_dir_fd=backup_fd,
                            dst_dir_fd=fd,
                            follow_symlinks=False,
                        )
                    except FileExistsError:
                        pass
                    raise UserError('A competing sidecar change was retained; inspect the recovery directory')
            finally:
                os.close(backup_fd)
        try:
            install_exclusive_at(fd, temporary, planned['name'])
        except FileExistsError:
            raise UserError(
                'A sidecar appeared during commit; it was kept. Inspect retained files before retrying'
            ) from None
        except OSError as error:
            if error.errno in {errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS}:
                raise UserError(
                    'Destination filesystem does not support safe no-overwrite installation; no existing file was overwritten'
                ) from None
            raise
        observed = _read_at(fd, planned['name'])
        if not observed or observed[0]['sha256'] != planned['sha256']:
            raise UserError('Sidecar readback changed; inspect files before retrying')
        os.fsync(fd)
        if directory_identity(folder) != planned['parent']:
            raise UserError('Media folder pathname changed during commit; inspect retained files before retrying')
        return dict(
            state='updated' if retained else 'created', sha256=planned['sha256'], bytes=len(data), retention=retained
        )
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass
        os.close(fd)
