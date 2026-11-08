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

## Blocked publication or interruption

Wait for active work to finish before stopping or updating Curator. Interrupted jobs become blocked on restart. Inspect the task's phase, error, publication log, and retained paths before retrying. Do not manually edit the runtime database.

An unpublished validated output can return to review where the app offers that action. Refresh a stale metadata preview when requested. Existing backup names, changed files, or uncertain prior publication require inspection rather than another encode or blind retry.

For a replacement of `film.mkv`, the original is retained as `film-old.mkv`. A failed installation may already have restored it to `film.mkv`; check both paths and the task receipt. Retained originals can appear as additional videos in Plex depending on the scanner. Curator does not clean them up automatically. Joined outputs keep their original source parts.

There is no automatic general rollback UI. To restore manually, stop Curator after active work finishes, identify the original using the task receipt, and preserve the current processed file under a distinct unused name before restoring the original filename. Never overwrite either version or remove an uncertain file. Refresh the item in Plex and rescan Curator afterward. Restoring video bytes does not automatically restore separate Plex metadata edits.

## Getting help

Report the Curator commit, macOS/Python/tool versions, task phase, expected behavior and sanitized error in GitHub Issues. Prefer a small generated test video. Keep tokens, personal media, private paths, settings and the SQLite database out of public reports. Security reports follow [SECURITY.md](../SECURITY.md).
