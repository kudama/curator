# Foundry: single-host Curator deployment

Status: **agreed deployment design (2026-11-15); not yet implemented or deployed**.
Implementation tracked under Curator PR #9 and related issues.

## Intended result

- Curator runs on **Foundry** (macOS): Python HTTP UI/API, SQLite task and
  catalog state, processing queue, HandBrakeCLI/FFmpeg/ffprobe/Topaz executables.
- From a desktop or other permitted private-network client, open
  **`http://foundry:8790`** directly in a normal browser. **No SSH tunnel,
  separate frontend, proxy, Docker, PostgreSQL, queue broker or worker service.**
- Curator is **unauthenticated by design for this deployment**. Do not add a
  login or Synology Directory Server integration at this stage. This is an
  explicit trust decision: anyone who can reach this port can read Curator state
  and trigger actions, including media modifications and publication.
- Limit reachability with the Foundry host firewall and network controls
  to trusted private clients. Do not expose Curator to the public internet.
  **Do not assume that placing Foundry on VLAN 20 alone restricts clients**
  across VLANs. Confirm the actual allowed desktop subnet(s) before deploying.
- Public Curator remains localhost-only by default; private-network listening
  must be a clearly opt-in, explicit interface binding.
- Use only the intended Foundry network interface/address, **not `0.0.0.0`**.
  Actual Foundry IP and hostname resolution must be confirmed at deployment.

## Application changes required

1. Add a `--host` (or equivalent bind-address) option to Curator's Python
   server, defaulting to `127.0.0.1`. Listen on an explicit Foundry LAN address
   only when selected. No binding to all interfaces by default.
2. Preserve existing cookie, same-origin, CSRF-header, Host, and browser
   security checks. Generalize the exact Host and Origin checks for the
   configured address and port (including the expected `foundry` hostname).
   Reject unrelated/forged Host/Origin values. Session cookies must remain
   `HttpOnly` and `SameSite=Strict`; the cookie alone is **not authentication**.
   Remote browser access must not accidentally enable cross-origin mutation.
3. Add regression tests for localhost default, opt-in LAN host access,
   rejected Host/Origin mutations, API reads and reviewed writes, and port
   matching. Use synthetic fixture state; no live Plex or media changes.
4. Keep the existing per-user macOS LaunchAgent, but make its configured
   bind address explicit and documented. Service starts after user login,
   keeps Curator running when the desktop browser closes, and logs startup
   failures. Do not claim pre-login, headless boot reliability from a user
   LaunchAgent.
5. Retain SQLite on **Foundry local disk**, with one Curator process owning
   the state. Keep processing, review, and publishing on the same host.
   Preserve restart behavior that blocks uncertain interrupted jobs rather
   than automatically replaying potentially destructive work.

## Foundry setup and operator boundaries

- The operator installs/licenses **Topaz Video AI** and installs **HandBrakeCLI**.
  Verify FFmpeg/ffprobe and the exact CLI executable paths. The application must
  not attempt to install or license tools.
- Mount the Synology media roots on Foundry and map Plex's media paths to the
  Foundry mount paths in Curator. Verify readable source paths, write/rename
  permissions for approved publication, available disk space, and behavior if
  the share disappears during a job.
- Plex connectivity and credentials are configured on Foundry. Do not commit
  tokens, media metadata, live task receipts or runtime catalogs.
- Because the UI is plain HTTP without user authentication, do not access it
  over untrusted Wi-Fi, a routed guest network, or an untrusted VPN. The
  network access controls are part of deployment acceptance, not optional
  hardening for a later release.
- No domain login now; Synology Directory Server remains a future option,
  not an implementation dependency.

## Migrate existing Curator state

1. Stop all Curator instances and let outstanding file operations finish.
2. Back up the **entire** local `~/Library/Application Support/Curator`
   directory (SQLite/WAL, settings, receipts, generated art and credentials).
   Keep the backup private; do not copy the database while it is live.
3. Transfer the stopped-state directory to the same private local path on
   Foundry via a secure mechanism. Preserve owner permissions.
4. Reconcile Plex root mappings, existing task source/output paths and
   pending queue items for **Foundry** before processing or publishing.
   Block unresolved desktop-only paths; never blindly resume file writes.
5. Verify a small representative scan → encode → review → publish sequence,
   including original retention, checksum/readback and Plex refresh.
   Validate browser reconnect and interrupted-job recovery.

## Acceptance criteria

- On a fresh standalone Mac, the default invocation is still available only
  at `127.0.0.1:8790`. Unauthorized Host/Origin combinations remain rejected.
- With an explicitly configured Foundry bind address and permitted network
  path, `http://foundry:8790` loads and approved browser actions succeed
  from the desktop **without a tunnel or sign-in**.
- A client outside the approved network cannot reach TCP/8790; no public
  interface is exposed. Verify actual firewall policy, not just documentation.
- Closing the desktop browser does not stop a processing job. Restart and
  interrupted-publish behavior remain safe and observable.
- Curator cannot write to missing/unmounted media roots or silently overwrite
  originals; an interrupted publication is inspected before retry.
- The documented LaunchAgent, state migration and startup/recovery behavior
  are tested against Foundry before declaring deployment complete.

## Explicitly out of scope

- PostgreSQL, Redis, RabbitMQ, Celery, containerizing Curator, distributed
  workers, video-tool installation, Synology LDAP/Directory login, general
  Internet exposure, changing the local Mac install default.
