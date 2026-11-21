"""Optional isolated test profile. Never enabled by a browser setting."""

import os
from pathlib import Path
from .errors import UserError

VARIABLE = 'CURATOR_DEVELOPMENT_ROOT'


def root():
    value = os.environ.get(VARIABLE)
    return Path(value).resolve() if value else None


def check_path(value):
    path = Path(value).expanduser().resolve()
    sandbox = root()
    if sandbox and not path.is_relative_to(sandbox):
        raise UserError('DEV / TEST paths must stay inside the development sandbox')
    return path


def block_external():
    if root():
        raise UserError('External integrations are disabled in DEV / TEST')


def configure(value, state, create=True):
    """Opt in before opening Store; refuse existing unmarked application state."""
    sandbox = Path(value).expanduser().resolve()
    state = Path(state).expanduser().resolve()
    production = (Path.home() / 'Library/Application Support/Curator').resolve()
    if sandbox == Path.home() or production.is_relative_to(sandbox) or sandbox.is_relative_to(production):
        raise UserError('Development sandbox must not contain production state or the home folder')
    if state == sandbox or not state.is_relative_to(sandbox):
        raise UserError('Development state must be a child of the sandbox')
    marker = state / 'development-profile'
    if marker.is_symlink() or (marker.exists() and marker.read_text() != str(sandbox)):
        raise UserError('Development profile marker does not match this sandbox')
    if (state / 'curator.sqlite3').exists() and not marker.is_file():
        raise UserError('Use fresh development state; existing unmarked state was preserved')
    if not create:
        return
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not marker.exists():
        with marker.open('x') as stream:
            stream.write(str(sandbox))
        marker.chmod(0o600)
    os.environ[VARIABLE] = str(sandbox)
