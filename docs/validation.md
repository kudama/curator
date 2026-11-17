# Workflow release validation — 2026-11-17

Version 0.5.0 workflow changes passed 405 Python cases (three optional media
integrations skipped), 53 JavaScript behavior cases, Python compilation, all
three UI script parses and whitespace checks. Synthetic threaded fixtures cover
global concurrency, lower-limit draining, source exclusion, file-operation cap,
pause/restart holds, bulk decisions, retained files, bounded preflight retries,
fixed run membership and persisted review progress.

An isolated browser fixture with generated comparison images and a fake
publisher verified all-library Queue, one-upscale/two-encode/four-file limits,
readiness display, automatic comparison loading, accept-to-next without a
confirmation, reject/reset-to-next, the skip shortcut and resume at the saved
fourth item after reload. It exposed and prompted comparison-first layout,
compact decision controls, accurate global labels and immediate capability
rendering. No real media or Plex/provider calls were used. The in-app browser
stalled on its native bulk confirmation; exact warning/count/cancellation and
duplicate-submission behavior passed automated JavaScript tests instead.

Real encoder throughput, representative media quality, mounted-storage fault
acceptance and production deployment remain separate. Source changes and passing
checks do not claim the running Foundry process was upgraded.

# Preview validation — 2026-11-08

Third-party readiness follow-up: 265 tests pass with generated-video integration enabled and no skips on the review host, including a clean stdlib-only source copy. Credential-redirect, publication-collision, generic tool discovery and startup regressions are covered. See [release readiness](release-readiness.md) for findings, corrections and remaining acceptance. The historical 260-case snapshot evidence below is retained for provenance.

The standalone snapshot contains the same runtime and test sources as the reviewed application under Thoth, including the latest Collections, Tags / genres, and Labels pickers.

Fresh local run: 260 unittest cases, 257 passed and 3 skipped because optional local media tools were unavailable. Python compilation and all three JavaScript syntax checks pass. Tests use synthetic fixtures and temporary catalogs; they do not establish compatibility with every Plex/NAS configuration.

Coverage includes path mappings and multiple library roots, source fingerprints/stale approvals, metadata and artwork readback, cast, folder defaults/no-op updates, catalog presence, cancellation/deletion, encoding progress, multipart joins, publication collisions and injected recovery failures. Earlier isolated browser checks exercised the workbench and metadata pickers against fake Plex, not a public demo or broad provider certification.

Limited operator/provider observations exist for actual encoding, publication, and Plex cast display. Broader licensed Topaz acceptance, representative-content encoding quality, local-vision quality, and real-storage interruption/recovery remain open. No live process restart, media write, or library metadata change was performed while preparing this public snapshot.

The public repository starts with an audited application snapshot rather than importing the platform's full history. Runtime media, settings, databases, and internal engineering records are excluded.
