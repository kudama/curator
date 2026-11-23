"""Keep observed Plex type, first-connect suggestion and chosen standard separate."""

import copy
from .rules import library_kind


def suggested_kind(library):
    observed = library_kind(library)
    scanner = ' '.join(str(library.get('scanner') or '').casefold().split())
    if library.get('type') == 'movie' and scanner in {'plex video files', 'plex video files scanner'}:
        return 'other_videos'
    return observed


def observe_library(fresh, previous=None):
    previous = previous or {}
    observed = library_kind(fresh)
    chosen = previous.get('standard_kind') or previous.get('kind') or suggested_kind(fresh)
    return dict(kind=observed, observed_kind=observed, standard_kind=chosen, suggested_kind=suggested_kind(fresh))


def migrated_profile_overrides(library, parent):
    """Preserve disagreeing legacy intent without changing its chosen type.

    Explicit library overrides win. Customized parent fields win over built-in
    legacy profile defaults; fill only otherwise inherited, untouched fields.
    """
    from .standards import DEFAULTS

    kind = library.get('standard_kind') or library.get('kind') or library_kind(library)
    desired_kind = {'home': 'other_videos', 'commercial': 'movie'}.get(library.get('profile'))
    overrides = copy.deepcopy(library.get('standard_overrides') or {})
    if not desired_kind or desired_kind == kind or kind == 'show' and desired_kind == 'movie':
        return overrides
    for dimension, fields in DEFAULTS[desired_kind].items():
        for field, value in fields.items():
            inherited = parent[dimension][field]
            if (
                field not in overrides.get(dimension, {})
                and inherited == DEFAULTS[kind][dimension][field]
                and value != inherited
            ):
                overrides.setdefault(dimension, {})[field] = copy.deepcopy(value)
    return overrides
