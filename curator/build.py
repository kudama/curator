"""Public build identity captured once, when this process imports Curator."""
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess

VERSION = '0.2.0'


def capture_build(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parent.parent
    result = {'version': VERSION, 'revision': 'unknown', 'dirty': None,
              'started_at': datetime.now(timezone.utc).isoformat()}
    def git(*args):
        return subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                              text=True, timeout=2, check=True).stdout.strip()
    try:
        # A ZIP inside another checkout must not inherit that checkout's identity.
        if Path(git('rev-parse', '--show-toplevel')).resolve() != root.resolve():
            return result
        revision = git('rev-parse', 'HEAD')
        if re.fullmatch(r'[0-9a-f]{40,64}', revision):
            result['revision'] = revision
            result['dirty'] = bool(git('status', '--porcelain', '--untracked-files=normal'))
    except (OSError, subprocess.SubprocessError):
        pass
    return result


RUNNING_BUILD = capture_build()
