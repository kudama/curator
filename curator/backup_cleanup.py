"""Preview and explicitly delete only receipt-backed retained originals."""
from pathlib import Path
import stat
import threading
import uuid
import os
import shutil
from . import tools
from .paths import map_path
from .file_workflows import exclusive_move, UNSUPPORTED_MOVE
from .store import now
from .logs import log
from .rules import ACTIVE
