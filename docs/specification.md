# Curator: proposed specification

Status: theoretical design, not implemented.

## Ownership and adapters

Plex remains authoritative for its catalog and playback sessions; Sonarr/Radarr for their management state; Synology/filesystem for stored files. Curator records evidence, findings, recommendations, jobs, and verification. Supported APIs and available telemetry must be verified during implementation.

## Proposed records

MediaAsset links a provider item ID to a protected local file reference, library, edition, size, technical metadata, and scan timestamp. Finding records evidence, severity, confidence, and suggested resolution. OptimizationPlan records original identity/hash, expected savings, preservation constraints, proposed operation, approval, temporary output location, and rollback location. Job records phase, progress, resource budget, verification, errors, and recovery status.

Store household watch history and home-movie metadata locally with access controls and retention rules. Home movies use separate policies and preserve originals; no external analysis without a deliberate grant.

## Proposed interfaces and execution

`GET /findings`, `GET /storage/summary`, and `GET /playback/diagnostics` expose authorized observations. `POST /plans` creates a recommendation; `POST /plans/{id}/approve` approves the exact version; `GET /jobs/{id}` returns progress. All are proposed contracts.

Read-only scans precede mutations. Use separate credentials for write operations. Plan changes or changed source files invalidate approval. Conversion writes a separate output, checks decodability, duration, required audio/subtitle tracks, and a chosen quality criterion. Only validated output can replace a commercial-media original. Replacement must account for filesystem atomicity and cross-volume limitations. Preserve recoverable originals until a documented retention policy permits cleanup.

## Acceptance criteria and open decisions

The first prototype inventories a small authorized commercial-media sample, explains findings without modification, and estimates storage by library/codec. Later tests must demonstrate failed conversions never replace originals, stale approvals cannot execute, and home-movie originals are preserved. Cancellation must leave a recoverable state.

Database, worker queue, transcoder/toolchain, quality thresholds, backup retention, API permissions, telemetry sources, rate limits, and deployment hardware remain undecided. Avoid asserting visually lossless output or reclaimable savings until measured.
