"""Who started an action, and the logging bridge into Curator history.

Job history is the existing per-task event trail. Curator history holds events about
Curator itself: configuration and standards changes, connections, scans, application
lifecycle and system errors. Both live in the events table, told apart by category.
"""

import contextvars
import logging
from contextlib import contextmanager

from .logs import redact

INITIATORS = ('operator', 'rule', 'ai', 'curator')
_initiator = contextvars.ContextVar('curator_initiator', default=None)


def current_initiator():
    return _initiator.get()


@contextmanager
def acting(initiator):
    """Attribute everything recorded inside this block to initiator."""
    if initiator is not None and initiator not in INITIATORS:
        raise ValueError('Unknown initiator')
    token = _initiator.set(initiator)
    try:
        yield
    finally:
        _initiator.reset(token)


class HistoryHandler(logging.Handler):
    """Records Curator's logged errors in Curator history, redacted, without tracebacks.

    The full traceback stays in the private log file. Writing never blocks on, or joins,
    another thread's transaction: the store defers the row until it can commit it alone.
    """

    def __init__(self, store):
        super().__init__(logging.ERROR)
        self.store = store

    def emit(self, record):
        try:
            details = {'logger': record.name}
            if record.exc_info and record.exc_info[1] is not None:
                error = record.exc_info[1]
                details['error'] = redact(f'{type(error).__name__}: {error}')[:500]
            details['log'] = 'Full details are in logs/curator.log'
            self.store.record_soon('error', redact(record.getMessage())[:300], level='error', details=details)
        except Exception:
            self.handleError(record)
