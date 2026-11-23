"""Child-only hard output-file limit before exec; never a threaded preexec_fn.

Invoked only for an explicitly approved maintenance process-to-separate-output
step. RLIMIT_FSIZE is inherited by the real tool and every descendant. Unsupported
platforms fail closed rather than weakening the reviewed bound.
"""

import os
import signal
import sys


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(argv) < 3 or argv[1] != '--' or not argv[0].isascii() or not argv[0].isdigit():
            raise ValueError()
        bound = int(argv[0])
        if not 1 <= bound <= 2**50:
            raise ValueError()
        import resource

        if not hasattr(resource, 'RLIMIT_FSIZE') or not hasattr(signal, 'SIGXFSZ'):
            raise ValueError()
        resource.setrlimit(resource.RLIMIT_FSIZE, (bound, bound))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
    except (ImportError, AttributeError, ValueError, OSError, OverflowError):
        sys.stderr.write('Hard output limit could not be installed; tool was not started.\n')
        return 78
    try:
        os.execvpe(argv[2], argv[2:], os.environ)
    except OSError:
        sys.stderr.write('The bounded processing tool could not be started.\n')
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
