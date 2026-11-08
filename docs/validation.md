# Preview validation — 2026-11-08

The standalone snapshot contains the same runtime and test sources as the reviewed application under Thoth, including the latest Collections, Tags / genres, and Labels pickers.

Fresh local run: 260 unittest cases, 257 passed and 3 skipped because optional local media tools were unavailable. Python compilation and all three JavaScript syntax checks pass. Tests use synthetic fixtures and temporary catalogs; they do not establish compatibility with every Plex/NAS configuration.

Coverage includes path mappings and multiple library roots, source fingerprints/stale approvals, metadata and artwork readback, cast, folder defaults/no-op updates, catalog presence, cancellation/deletion, encoding progress, multipart joins, publication collisions and injected recovery failures. Earlier isolated browser checks exercised the workbench and metadata pickers against fake Plex, not a public demo or broad provider certification.

Limited operator/provider observations exist for actual encoding, publication, and Plex cast display. Broader licensed Topaz acceptance, representative-content encoding quality, local-vision quality, and real-storage interruption/recovery remain open. No live process restart, media write, or library metadata change was performed while preparing this public snapshot.

The public repository starts with an audited application snapshot rather than importing the platform's full history. Runtime media, settings, databases, and internal engineering records are excluded.
