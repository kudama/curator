"""Private diagnostic log: records why an operation failed, never credentials.

User-facing messages stay short and generic. The full cause, with its traceback,
goes to <state>/logs/curator.log so an operator can find out what actually
happened. The log directory is 0700, every log file is 0600 and never follows a
symlink, and known secrets (the Plex token, the Mage key, bearer tokens and
token-style URL parameters) are redacted before anything is written.
"""

import logging
import os
import re
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from .errors import UserError

log = logging.getLogger('curator')
# Without a configured file (tests, library use) records go nowhere, rather than
# falling through to logging's last-resort stderr handler.
log.addHandler(logging.NullHandler())

REDACTED = '[redacted]'
PATTERNS = (
    re.compile(r'(X-Plex-Token\s*[=:]\s*)[^&\s\'",}]+', re.IGNORECASE),
    re.compile(r'(Bearer\s+)[^\s\'",}]+', re.IGNORECASE),
    re.compile(r'((?:api[_-]?key|token|password|secret)[\'"]?\s*[=:]\s*[\'"]?)[^\s&\'",}]+', re.IGNORECASE),
)
_secrets = set()
_secrets_lock = threading.Lock()


def register_secret(value):
    """Redact this exact value from every later log record."""
    if isinstance(value, str) and len(value.strip()) >= 6:
        with _secrets_lock:
            _secrets.add(value.strip())


def redact(text):
    for pattern in PATTERNS:
        text = pattern.sub(lambda match: match.group(1) + REDACTED, text)
    with _secrets_lock:
        values = sorted(_secrets, key=len, reverse=True)
    for value in values:
        text = text.replace(value, REDACTED)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))


class PrivateRotatingFileHandler(RotatingFileHandler):
    """Rotating handler whose files are created 0600 and never through a symlink."""

    def handleError(self, record):
        # The default implementation prints the original record and exception
        # context to stderr, bypassing redaction. Drop diagnostics if the private
        # destination fails; never fall back to an unprotected output or logger.
        pass

    def _open(self):
        fd = os.open(self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        return os.fdopen(fd, 'a', encoding=self.encoding)


def configure(root, max_bytes=1_000_000, backups=3):
    """Send Curator's log to <root>/logs/curator.log. Safe to call more than once."""
    directory = Path(root) / 'logs'
    if directory.is_symlink():
        raise UserError('Curator log directory cannot be a symlink')
    directory.mkdir(mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    path = directory / 'curator.log'
    handler = PrivateRotatingFileHandler(path, maxBytes=max_bytes, backupCount=backups, encoding='utf-8')
    handler.setFormatter(RedactingFormatter('%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s'))
    handler.curator_private = True
    for existing in list(log.handlers):
        if getattr(existing, 'curator_private', False):
            log.removeHandler(existing)
            existing.close()
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    # Keep private diagnostics out of stdout/stderr, which a service manager may collect.
    log.propagate = False
    return path
