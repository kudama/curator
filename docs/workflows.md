# Curator: theoretical workflows

## Library audit

Read authorized Plex metadata and filesystem attributes. Probe candidate files within resource limits; correlate provider items with files. Emit findings with evidence and confidence, then let the user review proposed corrections. No automatic deletion of duplicates or orphaned files.

## Approved conversion

Discover a candidate → estimate savings and quality tradeoffs → create a versioned plan → obtain approval → confirm the source has not changed → transcode to a temporary output → validate required streams, playback, and quality → replace safely → rescan Plex and verify → retain the rollback original. On failure, preserve the original and record the error.

## Why did Plex transcode?

Correlate session decision, media tracks, client capabilities, and available compute/network/storage telemetry. Distinguish confirmed evidence from an inferred compatibility bottleneck. Refer broader infrastructure diagnosis to Jarvis rather than giving Curator unrestricted infrastructure control.

## Metadata correction or quality upgrade

Show the current state and proposed change, including edition/match or storage/quality tradeoffs. Apply only approved changes through the authoritative provider. Read back the result and retain the prior metadata where supported for recovery.

## Home-movie intake

Keep private originals intact. Detect possible duplicates without deleting them, extract local technical/date metadata, and create separate previews. Local semantic tagging is a future optional capability. Raw videos and recognition results remain outside the repository.

## Backup and application upgrade

Check configuration/database backups independently of commercial-media preservation. Preview the upgrade and affected services, obtain approval, verify recoverable backups, apply, and run health checks. Restore or ask for intervention when checks fail.
