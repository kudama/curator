# Setup and recovery

## First launch

Curator requires Python 3.11 or newer. Apple's bundled Python may be older; check `python3 --version`. Install a current Python and use that interpreter, or use `Curator.command`, which checks common Homebrew and Python.org locations. The launcher accepts the same options as `python3 -m curator.web`.

If you see `No module named curator`, open Terminal in the extracted repository folder, alongside `Curator.command`, before running the command. Curator is run from source; there is no pip package or signed desktop installer.

If the port is occupied, close the other application or use `python3 -m curator.web --port 8791 --open`. A second instance cannot share the same state directory. Do not remove its lock while another instance is running.

## Connect and scan

Use the Plex server's direct root URL, including port, without a web-app path, token query string, username, or password. Use HTTPS where available; an HTTP connection sends the Plex token over that network without encryption. Redirecting/reverse-proxy login pages are not supported. HTTP 401 usually means the token is invalid; a different server identity requires reconnecting the intended server.

Mount media storage in Finder before mapping Plex locations. Map every root you intend to scan; leave unavailable roots unmapped. Curator does not mount shares or infer credentials. Missing mounts and changed source fingerprints block file operations. Reconnect the share and scan again after resolving the mapping.

FFmpeg and ffprobe are required for video analysis. The tools must be installed and executable; absolute paths in Settings override discovery and an invalid explicit path is never silently replaced. HandBrakeCLI is required for optimization, and Topaz is required only for its upscale tasks. Installing the HandBrake GUI does not establish a usable CLI path. Select a valid installed preset on each optimization task.

Ollama analysis is optional. It expects a local server at `127.0.0.1:11434` and an installed vision model matching Settings. Missing analysis leaves frames available for manual review; it does not authorize metadata writes.

## Topaz model downloads and writable cache

Install/license Topaz and finish downloading the enhancement models before retrying an upscale. A successful GUI preview or export is useful evidence, but Curator's background worker has a separate environment.

Curator reads model metadata from the installed Topaz bundle and uses `~/Library/Caches/Curator/Topaz` for writable model data and Core ML compilation. It creates the cache when needed and never changes application-bundle permissions. Explicit `TVAI_MODEL_DIR` and `TVAI_MODEL_DATA_DIR` environment overrides are preserved; the data directory must be writable by the service account.

If downloads fail, inspect the actual Topaz download result and outbound VPN/filtering settings. A generic unauthenticated model-host HTTP 403 does not by itself establish a vendor outage. On Foundry, the operator reported NordVPN blocked downloads on November 16, 2026. After downloads, a synthetic Proteus 2× frame succeeded with the writable cache; representative real-file output validation remains a separate acceptance check.

## Blocked publication or interruption

Wait for active work to finish before stopping or updating Curator. Interrupted jobs become blocked on restart. Inspect the task's phase, error, publication log, and retained paths before retrying. Do not manually edit the runtime database.

An unpublished validated output can return to review where the app offers that action. Publication preserves originals with an exclusive no-overwrite move rather than an empty backup reservation. If an earlier release left an empty `-old` file after a failed reservation, verify the failure receipt and unchanged source/output before moving only that placeholder into retained recovery storage. Do not treat an arbitrary empty file as safe to delete. Refresh a stale metadata preview when requested. Existing backup names, changed files, or uncertain prior publication require inspection rather than another encode or blind retry.

For a replacement of `film.mkv`, the original is retained as `film-old.mkv`. A failed installation may already have restored it to `film.mkv`; check both paths and the task receipt. Retained originals can appear as additional videos in Plex depending on the scanner. Curator does not clean them up automatically. Joined outputs keep their original source parts.

There is no automatic general rollback UI. To restore manually, stop Curator after active work finishes, identify the original using the task receipt, and preserve the current processed file under a distinct unused name before restoring the original filename. Never overwrite either version or remove an uncertain file. Refresh the item in Plex and rescan Curator afterward. Restoring video bytes does not automatically restore separate Plex metadata edits.

## Getting help

Report the Curator commit, macOS/Python/tool versions, task phase, expected behavior and sanitized error in GitHub Issues. Prefer a small generated test video. Keep tokens, personal media, private paths, settings and the SQLite database out of public reports. Security reports follow [SECURITY.md](../SECURITY.md).

## Repeated upscale or output above the 4K ceiling

Media already at 4K class stops receiving automatic optional-upscale recommendations, including after Plex gives it a new catalog identity. High-bitrate encoding recommendations remain available independently.

For a single dynamic Topaz filter with reviewed 1×, 2× or 4× scaling and automatic width/height, Curator predicts displayed output dimensions before queue approval and again before processing. A plan exceeding the existing 4096-pixel long-edge / 2160-pixel short-edge ceiling is refused with the predicted dimensions. For example, 3840×2160 at 2× would produce 7680×4320. Change and review the settings before retrying; Curator preserves the selected model/filter and retained outputs.

Explicit output sizing and complex filter chains retain their existing post-processing validation; this guard does not invent their geometry. The recovery controls described below separately offer resolution-only output review or a reviewed 4× attempt from the original.

## Below-target upscale recovery

A retained upscale whose only failed check is the existing 1080-class resolution
floor offers **Review below-target output**. Curator independently probes and decodes
it, verifies source/output hashes and records an operator exception for that exact
output and task revision. The strict validation result stays visible. Comparison
review and separate **Accept & publish** are still required; originals are retained.
Duration, aspect, tracks, color, decode and ceiling failures cannot be waived.

**Prepare 4× redo** previews source-relative dimensions, the preserved model/filter
and encoding settings, then prepares a new plan from the original. It does not
queue or start processing. Approve that plan separately. Earlier outputs and attempt
history are retained. Known below-floor or above-ceiling plans are refused before
queue approval or launch; unknown/explicit/chained filters require supported settings
rather than guessed 4× geometry. A 4× scale is not a 4K resolution promise.

These controls use the current processing validator's 1080-class floor and 4K
ceiling. Wiring configurable v2 standards into scans/processing remains #107;
accepting an exception does not change a saved type standard or library override.

## Metadata or artwork after a rename (#70)

Before a rename moves any file, Curator reads the item from Plex again and keeps a private recovery receipt: the current metadata (title, description, studio, tagline, genres, collections, labels, cast with roles and order) and the bytes of each selected artwork kind. Receipts live in the state folder under `rename-receipts/` (folder 0700, files 0600) and are never changed afterwards. If Plex cannot be read, or a selected image cannot be saved, the rename does not start and nothing moves.

Curator still does not force a Plex refresh after renaming. When a later library scan finds the renamed file, Curator compares Plex with the receipt, and only for an exact match: the same Curator asset and library, the destination path, the same item type and an unchanged file fingerprint. Anything else is marked blocked for manual review.

- Fields Plex kept need nothing. The receipt is marked reconciled.
- Fields that now differ become a **proposed restore** on the item's metadata task. Review it in the metadata editor and apply it there; nothing is written to Plex automatically.
- Fields Curator itself changed after the rename are never proposed. Open metadata work on the same item is reported as a conflict and left untouched.
- Replaced or missing artwork is reported, and the original bytes stay in the receipt.
- Cast pictures uploaded into Plex (which a rematch can lose) are kept in the receipt as Plex serves them. Pictures supplied by the Plex agent are kept as references only, because Plex can fetch them again. A picture that cannot be read is recorded and never stops the rename.
- A rename that fully rolls back marks its receipt void. Curator history records each check, with a warning when something needs review.

### Reviewing a rename and restoring what Plex lost (#154)

Open **Rename recovery** from the rename job in History, or **Review rename** on a rename check in Curator history. It shows, for that item, each changed field (before the rename and now), each kept image beside what Plex shows now, and each kept cast picture, with whether the kept copy still verifies. "Now" means the last library scan. Opening a receipt never writes anything.

- **Metadata** opens the proposed restore in the metadata editor, as before.
- **Artwork:** tick the images to put back and choose **Create restore review**. Each becomes an ordinary artwork review waiting in Artwork; nothing is published until you approve it there, and publication again checks the destination and that Plex still shows the image you saw.
- **Cast pictures:** tick the people and choose **Restore selected pictures**, then confirm. Only those pictures change; every other credit, role, order and picture stays as Plex has it. It is refused if the person is no longer credited or the cast changed since the last scan.

Every restore first rechecks the receipt, the item, its library and file fingerprint, and that Plex still matches the renamed file. If Plex has not matched the file yet (not found), the restore waits for Plex's next scan: Curator never forces a refresh or rematches on its own. Failures are shown with what to do next, and the kept copies stay in the receipt.

Renders with synthetic data: [desktop](designs/v2-rename-recovery-20261122/desktop.jpg), [phone](designs/v2-rename-recovery-20261122/phone.jpg).

Rename and shared file-operation queues stay paused until the operator resumes them; this change does not resume them.
