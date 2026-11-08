"""Translate native Ubuntu Plex paths to explicitly mapped Mac storage roots."""
from pathlib import Path, PurePosixPath


def map_path(source: str, mappings: list[dict], require_exists: bool = True) -> Path:
    """Return canonical local path or raise ValueError.

    mappings contain plex_root and local_root. Both must be absolute.
    Reject '..' in any input path, ambiguous equal roots and symlink escape.
    Select the longest matching source root by complete path components.
    For require_exists, mapped root must exist as a directory and target a file.
    No match or unavailable mount is an error; never guess an alternative path.
    """
    def absolute(value, cls):
        if not isinstance(value, str) or not value or '\x00' in value:
            raise ValueError('Invalid mapping path')
        path = cls(value)
        if not path.is_absolute() or '..' in path.parts or value.startswith('//'):
            raise ValueError('Mapping paths must be absolute without traversal')
        return path

    source_path = absolute(source, PurePosixPath)
    matches = []
    seen = set()
    for mapping in mappings:
        root = absolute(mapping.get('plex_root'), PurePosixPath)
        local = absolute(mapping.get('local_root'), Path)
        if root in seen:
            raise ValueError('Ambiguous duplicate Plex root')
        seen.add(root)
        if source_path.is_relative_to(root):
            matches.append((len(root.parts), root, local))
    if not matches:
        raise ValueError('No mapping for this Plex path')
    _, root, local = max(matches, key=lambda item: item[0])
    if require_exists and not local.is_dir():
        raise ValueError('Mapped storage root is unavailable')
    target = (local / source_path.relative_to(root)).resolve()
    if not target.is_relative_to(local.resolve()):
        raise ValueError('Mapped file escapes configured storage')
    if require_exists and not target.is_file():
        raise ValueError('Mapped media file is unavailable')
    return target


def media_presence(source, mappings, previous=None):
    """Distinguish a missing file from unavailable storage/mapping/access."""
    import stat
    try:
        target=map_path(source,mappings,require_exists=False)
        plex=PurePosixPath(source)
        mapping=max((m for m in mappings if plex.is_relative_to(PurePosixPath(m['plex_root']))),
                    key=lambda m:len(PurePosixPath(m['plex_root']).parts))
        root=Path(mapping['local_root']).expanduser().resolve()
        root_stat=root.stat()
        if not stat.S_ISDIR(root_stat.st_mode):raise ValueError('Mapped storage root is unavailable')
        # A leftover /Volumes directory must not masquerade as its unmounted share.
        if len(root.parts)>2 and root.parts[1]=='Volumes' and not Path(*root.parts[:3]).is_mount():
            raise ValueError('Mapped storage share is not mounted')
        try:
            result=target.stat()
        except FileNotFoundError:
            if previous and previous.get('device')!=root_stat.st_dev:
                raise ValueError('Mapped storage device changed or is not mounted')
            return dict(state='missing',path=str(target))
        if not stat.S_ISREG(result.st_mode):raise ValueError('Mapped media path is not a regular file')
        return dict(state='present',path=str(target))
    except (OSError,ValueError):
        return dict(state='unavailable',reason='Mapped storage or file access is unavailable; check the mount, permissions and path mapping')
