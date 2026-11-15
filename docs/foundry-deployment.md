# Foundry: single-host Curator deployment

Status: **implementation in PR #9 (2026-11-15); not yet deployed or accepted on Foundry**.
Coding review is tracked under #10/#11; real deployment acceptance remains #12.

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
- The operator explicitly chose **no source-subnet restrictions** on 2026-11-15.
  Any client with a network route to the bound private address/port can use Curator.
  Do not claim VLAN placement or application Host checks isolate other clients.
  No public interface binding or Internet port forwarding is part of this deployment.
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
- The UI is plain HTTP without user authentication or source-subnet filtering.
  Every reachable client can act; browser Host/Origin checks are not client
  authorization. This is the explicit operator decision for this deployment.
- No domain login now; Synology Directory Server remains a future option,
  not an implementation dependency.

## Configure the implemented listener

The default command still binds only `127.0.0.1`. `--host` accepts an explicit
loopback or RFC1918 IPv4 address; DNS names, wildcard, public, link-local and
IPv6 binds are refused. `--expected-host` adds a bare browser hostname and may
be repeated. The bound address is always an accepted Host; `localhost` is added
automatically only for the default `127.0.0.1` bind. Authorities include the
actual listening port. A mutating request must have exactly one matching Host
and Origin plus the existing session cookie and `X-Curator-Request` header.
Duplicate Host/Origin headers and requests across two configured aliases are
rejected. These browser checks do not authenticate users on the permitted network.

After verifying the actual interface, DNS and network reachability under #12, an
operator can run this example with the real private address substituted:

```sh
python3 -m curator.web --host 192.168.1.20 --expected-host foundry
```

Then open `http://foundry:8790`. No subnet allowlist is installed or claimed.
An accepted hostname is a browser safety setting, not a firewall rule.

For a reviewed installation, the LaunchAgent generator accepts the same flags:

```sh
python3 scripts/install-foundry-launchagent.py \
  --host 192.168.1.20 --expected-host foundry
```

It generates a per-user plist and prints activation commands; it does not load a
service or install media tools. The default remains explicit loopback. Existing
plists are refused unless the operator explicitly chooses `--replace`; symlinked
plists are always refused. Preserve the existing plist before choosing replacement.
State must remain on local disk, outside the source checkout and NAS shares;
the generator does not establish that a volume is local. Stop an existing Curator
instance and reconcile pending work before loading a replacement. The service
starts after GUI login; no pre-login/headless-boot acceptance is claimed.

## Coding validation

2026-11-15: the integrated network/launcher changes passed 321 local tests
(three optional integrations skipped). New cases cover loopback defaults,
explicit private binds, actual bound ports, Host/Origin mismatch and duplication,
preserved cookies/header checks, successful same-origin writes and CLI validation
before state creation, plus an actual local loopback bind. Launcher tests also
cover repeated hostnames, plist round trips and existing-definition preservation.
These results do not establish Foundry firewall reachability, mounts,
state migration, video tools, real media safety or login recovery. No Curator
service was installed or started during this coding review.

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
- The service binds only the selected private interface, with no public
  wildcard bind. No source-subnet restriction or application login is claimed;
  verify and record the actual reachable clients and operator-selected exposure.
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

## Restart from the browser

With the generated LaunchAgent installed, open **Settings → Curator service → Restart Curator**. Save edits first: the page reconnects and reloads after the service starts again. The server refuses a restart during processing, publishing, library scans, file availability checks, or another data-changing request. Accepted requests drain before the database closes. Queued tasks and review decisions remain stored; restarting does not start the queue.

The managed service exits with status 75 after a requested restart; launchd's existing unsuccessful-exit policy relaunches it. A manually started server has no UI restart capability. Existing installations must regenerate and reload their LaunchAgent to enable this control; updating source alone does not change loaded arguments. Preserve the old plist before replacement and wait for an idle service before refreshing it.

This is a per-user LaunchAgent: Curator starts **after the configured user logs in**, not before login. RunAtLoad and relaunch behavior do not establish unattended reboot acceptance. A next-login/reboot check remains a separate deployment check.
