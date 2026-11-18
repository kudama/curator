# Refresh recovery and stable queue — 2026-11-18

Mike authorized Forge #114 and the join-triggered queue layout correction.
The local Forge controller reported `controller_unavailable`; these changes
were authored and reviewed by the senior controller, with no accepted worker job.

## Behavior

The three queue lanes remain visible when a join, rename, grouping task or
unowned cleanup receipt exists. File preparation appears in File operations,
using its existing per-kind execution limits and global task waiting order.
Admitted copy/delete jobs still use their own file-operation IDs/order and
maximum-four limit. Ownership by `payload.task` or `payload.receipt` prevents
counting the same in-progress operation twice. Other task types retain their
existing type-specific cards/controls below the board instead of replacing it.
This corrects the layout fallback; it adds no new processing or approval action.

Background updates use one recoverable connection status, single-flight reads,
a 25-second read deadline, and retries from 8 seconds up to 60 seconds after
failure; normal polling resumes four seconds after a successful cycle. Explicit
user-action errors and Undo remain separate. Mutations are never retried.
Concurrent action changes invalidate an in-flight response before applying it;
explicit refresh requests during a read cause a trailing read.

`/api/state/updates` sends the initial full state followed by changed asset/task
records and changed top-level fields. Removal and ordering changes are explicit.
An eight-entry in-memory fingerprint cache holds no record bodies; unknown or
expired cursors, including after restart, get a full reset. Existing `/api/state`
clients remain supported. No schema, provider, permissions or dependency change.
Full state is still assembled on the server; this reduces transfer size rather
than claiming all server-side catalog work is eliminated.

Client disconnects during responses no longer cause a second failed error reply.
Other errors retain their existing handling. The underlying intermittent Foundry
connection cause has not been established by this change.

## Verification

- 418 Python tests run, three optional skips; all remaining tests passed.
- 80 JavaScript tests passed; all six frontend modules passed syntax checks.
- Coverage includes repeated failure/recovery/backoff, single-flight/trailing
  reads, mutation races, timeout, incremental merge/removal/order, cursor expiry,
  client disconnects, join moves in the correct order domain, publication
  deduplication and unowned interrupted cleanup visibility.
- Synthetic browser: three columns remain with a queued join; unrelated metadata
  remains visible below. Controlled repeated 503s produced one connection status
  and zero alert notices; recovery cleared the status while preserving an unsaved
  settings value. No synthetic media operation or settings save was submitted.
- A 5,000-task / 1,600-asset fixture measured 13,587,734 bytes initially,
  125 bytes unchanged and 2,220 bytes with one changed task. These are synthetic
  transfer sizes, not production measurements after deployment.
- Production checks during development intermittently refused HTTP connections
  and SSH timed out before any deployment/restart. Do not infer a process crash
  or a resolved transport cause from those observations.

Deployment requires the existing idle-service check and full rollback snapshot.
No active job may be cancelled, replayed or interrupted to install this change.
