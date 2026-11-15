# Foundry: single-host Curator deployment

This optional deployment keeps the published Mac application architecture: Curator UI,
Python API, SQLite queue and media processing all run on **Foundry**. Your desktop only
needs a browser and an SSH tunnel. The standard `python3 -m curator.web --open`
installation remains unchanged. No Postgres, workers, queue broker, or exposed HTTP
listener is necessary.

## Prerequisites

- macOS on Foundry, Python 3.11+, and the Curator repository checked out in a
  stable location. Moving the checkout invalidates the LaunchAgent's working directory.
- Foundry and desktop can connect over SSH. Enable **Remote Login** for an
  authorized account on Foundry, preferably using SSH keys. Limit access to the
  private network or an existing secure VPN. Do not port-forward SSH or Curator
  from the public internet.
- Plex connectivity from Foundry. Mount the media shares on **Foundry** and verify
  both read and intended write permissions before starting an encode/publish operation.
- Install and license Topaz Video AI and install HandBrakeCLI, FFmpeg and ffprobe
  on Foundry. The HandBrake GUI alone is not equivalent to HandBrakeCLI.
- Do not put Curator's SQLite/state directory on SMB, NFS or another network share.

## 1. Install and configure Curator on Foundry

On Foundry, from the Curator checkout:

```sh
python3 --version
python3 -m curator.web --open
```

In the browser, set the Plex server URL/token and map each Plex storage root to
the corresponding **Foundry** mounted-media path. Configure executable paths
in Settings when needed; the LaunchAgent's PATH can differ from an interactive
Terminal. Confirm that the CLI tools actually run under the same macOS user
that will run the LaunchAgent. Stop Curator when configuration is complete.

For existing Curator users, migrate the state before configuring any new work,
as described below.

## 2. Install per-user background startup

From the stable Curator checkout on Foundry, use the exact Python interpreter
used for successful interactive Curator startup:

```sh
python3 scripts/install-foundry-launchagent.py
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.curator.foundry.plist"
launchctl print gui/$(id -u)/com.curator.foundry
```

The script writes a per-user macOS LaunchAgent, set to restart after failures.
It **does not** start the service, install media tools, modify firewall settings
or expose Curator beyond loopback. Stop a manually running Curator before
loading the agent; only one process can own its state directory. For reinstallation
after editing the generated plist, unload it first:

```sh
launchctl bootout gui/$(id -u)/com.curator.foundry
python3 scripts/install-foundry-launchagent.py --replace
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.curator.foundry.plist"
```

The LaunchAgent runs **after the user logs into macOS**, not at pre-login boot.
Ensure the user session remains active for unattended work; test the behavior
across a reboot and an ordinary login. The default state path is
`~/Library/Application Support/Curator`; logs are in that directory. Do not
run two Curator instances against it.

## 3. Open Curator from your desktop

With SSH access configured to Foundry:

```sh
ssh -N -L 8790:127.0.0.1:8790 foundry
```

Then visit `http://127.0.0.1:8790` **on your desktop**. Keep the tunnel running
while using the browser. Curator's current Origin validation requires the browser's port to match the
server's port. If port 8790 is occupied on the desktop, stop the conflicting
process, or deliberately configure **both** Curator on Foundry and the tunnel
to use the same alternative port.

The current Curator HTTP server explicitly requires localhost Host and Origin
values and a session cookie. The browser speaks to desktop localhost and SSH
forwards to Foundry localhost, so no LAN binding/authentication rewrite is needed.
Never use `ssh -g` or bind the tunnel to `0.0.0.0`. SSH credentials and session
access protect the remote connection.

## 4. Move existing state from the desktop (optional)

1. Stop Curator on the **desktop** and confirm no encode/publish operation is active.
   Stop Curator on Foundry too; never copy a live WAL database.
2. Make a separate backup of the entire desktop
   `~/Library/Application Support/Curator` directory, including SQLite WAL/SHM
   files if present, task receipts, artwork assets, and the private token/key
   files. Treat backups as secrets.
3. Transfer that entire stopped-state directory over SSH, for example from the
   desktop (adjust the real SSH destination and path):
   
   ```sh
   tar -C "$HOME/Library/Application Support" -cf - Curator | \
     ssh foundry 'mkdir -p "$HOME/Library/Application Support" && tar -C "$HOME/Library/Application Support" -xf -'
   ```

4. On Foundry, ensure the state directory is private to its service account.
   Update all Plex-to-local path mappings for Foundry's actual mount paths.
   Existing task output paths and unfinished queue items may still refer to
   desktop locations. **Inspect and reconcile them before running the queue.**
5. Validate a small synthetic/sample file through scan → encode → review →
   publish. Confirm the original is retained and Plex refreshes correctly.
   Only then start any backlog processing.

For a fresh Foundry deployment without valuable existing state, skip the
migration and configure Curator directly.

## Recovery and operational limits

- Curator's current restart behavior blocks interrupted `running` and
  `publishing` tasks for **manual inspection**. It does not blindly resume
  file mutations. This is intentional; verify retained originals and outputs
  before retrying.
- Losing an SSH tunnel disconnects only the browser; the Foundry process and
  already running jobs continue. Stopping the LaunchAgent or logging out can
  interrupt them.
- The service will not automatically mount NAS shares. Verify mounted shares
  and permissions before starting jobs; Curator checks missing and changed
  mappings and rejects unsafe publication.
- Check `launchd.stderr.log`, `launchd.stdout.log`, and the task's publication
  log if startup or publishing fails.
- Back up Curator's *stopped or consistently snapshotted* state along with
  normal Synology media backups. Do not copy a live SQLite file in isolation.

This setup is intentionally a single-host deployment. Changing it to native
LAN listening, a shared database or remote processing workers is **not**
required for Foundry.
