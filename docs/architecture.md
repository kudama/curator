# Architecture

Curator is a standalone local Mac application: Python 3.11+ standard library, loopback threaded HTTP server, plain HTML/CSS/JavaScript, and SQLite state on local disk. Shared media stays on mapped storage; the state database must not live on a network share.

`store.py` owns records, transactions, events, and a single-instance state lock. `plex.py` wraps Plex HTTP APIs without accessing its internal database. `paths.py` translates declared Plex roots to mounted Mac paths. `service.py` coordinates catalog/task workflows; `folders.py` and `file_workflows.py` keep bulk metadata and file operations scoped. `tools.py`, `multipart.py`, and `progress.py` handle subprocess plans, video validation/joins, and telemetry. `web.py` serves the local UI and API. The static workbench, metadata pickers, and application scripts require no build.

Task lifecycle: recommendation → explicit approval/queue → processing → validation → review/comparison → accepted publication → verified completion. Metadata saves and approved folder writes use their own preview/readback workflows. Source or plan changes invalidate approvals. Per-task reservations prevent conflicting operations. Background publication avoids holding the catalog lock during slow copies/hashes.

Encoding creates separate outputs. Replacement verifies sources, retained output, and staging hashes; preserves an in-place original; installs the replacement; then refreshes and verifies Plex. Joins retain every part. Recovery receipts distinguish interrupted or uncertain results from success. No automatic original deletion or replay is provided.

The local server checks Host, session cookie, origin and request headers for mutations; serves a restrictive content security policy; and hides credentials from image URLs. External commands use argv arrays, not shell strings. Credentials and runtime catalogs stay outside source control.

Curator can run without Thoth or Forge. Future agent integration should use bounded interfaces rather than sharing runtime files or credentials.
