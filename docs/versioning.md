# Version and running build identity

Curator uses a pre-1.0 semantic version in `curator/build.py` (`VERSION`). Release changes update that authoritative value. Git checkouts also report a revision and whether local changes were present; extracted ZIP installs without Git report `unknown`.

The UI header, private `/api/service/status` diagnostics and startup log identify the running process. Build identity is captured once when the process imports Curator. Updating checkout files does not change this identity or prove the process has reloaded code. Restart after active queues, publication and scans finish. Static styles can update independently without changing the backend's running build identity.

An upgrade changes source; a restart loads source. Back up private state using the supported stopped-state procedure before upgrades. Original retention is separate from database compatibility. The current version does not promise arbitrary database downgrades; restore a compatible state backup together with matching source when rollback requires it. No state migration is introduced by build identity.
