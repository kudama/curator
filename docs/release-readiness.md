# Third-party readiness review — 2026-11-08

## Decision

Suitable for an **early technical preview** after the fixes below. This is not a stable general release or a certification for arbitrary Plex servers, NAS devices, codecs, or clients. A fresh independent Mac/Plex setup and visual walkthrough remain acceptance work.

The review covers the standalone public repository, source installation, public docs, credential boundaries, optional tooling and publication behavior. It does not change the running application or operate on user media.

## Findings corrected

| Priority | Finding | Correction and evidence |
| --- | --- | --- |
| High | Normal Plex API requests could follow an HTTP redirect carrying the Plex token. | API and artwork requests refuse redirects. A socket-free HTTP redirect test confirms the credential-bearing request never reaches the redirect target. Configure the direct Plex server URL. |
| High | A file created at the source path between original preservation and final installation could be overwritten. | Installation and restoration now use the existing exclusive-move/verified-copy workflow. Collision regression preserves the new external file, original backup, retained output and blocked task; no Plex write occurs. |
| Medium | Default FFmpeg/ffprobe discovery assumed a Topaz installation. | Discover standard PATH/Homebrew executables as well as the existing Topaz bundle. Explicit invalid settings still fail instead of silently selecting another program. Tested without a Topaz path. |
| Medium | An older Python or an occupied listener produced an unclear startup failure; the launcher favored one install location. | Explicit Python 3.11 minimum, common Intel/Apple Silicon/Python.org interpreter locations, argument forwarding and actionable listener errors. Listener failure releases the state lock. |
| Medium | Setup text assumed Ubuntu; public setup/recovery instructions were incomplete. | Server-neutral settings text, download/token/tool links, troubleshooting/recovery guidance and issue-report instructions. |

## Verification

- 265 unittest cases pass with `CURATOR_FFMPEG_TESTS=1`; no skips on the review host. Synthetic media exercises probing, sampling, encoding, multipart stream-copy joins, chapter/boundary checks and publication against fake Plex. Software-fixture normalization does not establish native encoder quality.
- A fresh temporary copy passes the same 265 cases with `python -S`, no `PYTHONPATH`, no installed Python packages and generated-video integration enabled. No private runtime data is copied into that fixture.
- Python compilation, all three JavaScript parses, launcher syntax/help, old-Python diagnostic and Git diff checks pass. Public Markdown links to local files resolve.
- Existing tests cover Host/session/origin boundaries, path traversal/mapping, stale approval/source checks, partial writes/readback, collisions, cancellation, and interrupted-task behavior. These fixtures do not replace adversarial security testing.
- Prior release preparation scanned 311 historical application blobs and the public snapshot for selected credential formats, private IPs and personal absolute user paths with no matches. Runtime catalogs, credentials and media are excluded from the public tree. This is pattern scanning, not a complete secret/security audit.

GitHub CI evidence is tracked in the linked review pull request and [issue #1](https://github.com/kudama/curator/issues/1). Local execution used Python 3.14; the repository workflow separately targets Python 3.11 and 3.13. Do not infer matrix success from the local run.

## Remaining acceptance

1. Confirm the GitHub Python matrix and a fresh download/install on an independent Mac. Capture synthetic screenshots and complete a first-run visual walkthrough. This review environment cannot bind a loopback listener; HTTP boundary tests run without sockets.
2. Broaden Plex version/agent/client checks, licensed Topaz/model acceptance, representative encoding quality and real mounted-storage interruption/recovery. Current tests never use a real user's Plex metadata or personal media.
3. Establish a reachable private vulnerability-reporting route in repository settings. `SECURITY.md` describes conditional private reporting; enabling it is not confirmed by the available API.

The app remains local-only and single-user. Its Plex token is stored locally without application-level encryption. No signed/notarized installer, Windows support, multi-user hosting, automatic originals cleanup or general rollback UI is promised. Retained originals may be indexed by Plex; see [recovery guidance](troubleshooting.md).
