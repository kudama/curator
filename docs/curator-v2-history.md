# Curator v2 — history

Part of [Curator v2](curator-v2.md). This builds on the existing History screen and the per-task event trail; it does not replace them. Until v2's navigation exists, History stays where it is in the sidebar.

## Job history (the existing History screen, extended)

Job history is still built in the browser from what the workbench already loads: finished, failed, cancelled, rejected and blocked tasks, saved review-group receipts and backup-cleanup receipts. The existing status filter is unchanged. New:

- **Library:** This library (as before) or All libraries.
- **When:** any time, or the last 24 hours, 7 days or 30 days.
- **Who queued it:** tasks queued from now on record `queued_by`.
- **Timeline:** each job has a Timeline. Opening it loads that job's event trail from `GET /api/history/task?id=…`, with time, action and initiator. Only plain values are returned. Nested records such as previous task versions stay in the database, and strings are redacted.

## Curator history (new)

A second view on the same screen, "Curator events", records events about Curator itself:

| Event | Level |
| --- | --- |
| Curator started / stopped / restarting, restart requested | info |
| Local state upgraded to a new schema (names the backup) | info |
| Configuration changed: lists the changed setting **names**, never values | info |
| Library settings changed; library standard or overrides changed | info |
| Libraries refreshed from Plex; scan started / finished (file count) | info |
| Plex connection failed (once per run of failures) / restored | warning / info |
| Scan failed | error |
| Any error Curator logs | error |

Logged errors are redacted and shown without a traceback. The full traceback stays in the private `logs/curator.log`. Each event can show technical details beneath it. Filters: library, period and level. Pages hold 100 events, with "Load older events". The newest 5,000 Curator events are kept.

## Initiators

Every event records who started it where Curator knows: `operator` (any request from the browser), `curator` (Curator itself: startup, shutdown, upgrades), and `rule` / `ai`, which are reserved for rule-based automation and AI-assisted actions once they exist. A scan keeps the initiator of whoever started it. Events recorded before this change have no initiator.

## Storage

Schema migration 3 adds `category` (`job` or `curator`), `library`, `initiator` and `level` to the existing `events` table, plus indexes on `(task, id)` and `(category, id)`. Existing events become job events, and their library is filled in from their task where the task still exists.

- Job events are written with the caller's transaction, as before.
- Curator events tied to a state change commit or roll back with that change.
- Logged errors are written so that they survive a rollback and never wait for another thread's transaction. If the store is busy, they are written as soon as the current transaction ends.

## Recovery from job history

Each job in History shows the next supported step for its state, using only actions that already exist. **View** opens the existing job inspector and never acts by itself. Only two actions can be taken from the History row, and neither one publishes:

| State | What History offers |
| --- | --- |
| Applied or resolved | Nothing to recover |
| Retained-original cleanup pending | Guidance: view the job; restoring happens there |
| Rejected | Explanation: rejected results stay closed |
| Publication started (`published`) | Guidance: check the publication log and Plex verification in the inspector; never reprocess |
| Rename started | Guidance: restore the original filenames from the inspector |
| Join with a retained output | Guidance: refresh the preview and return to review from the inspector |
| Blocked upscale/encode with a validated, unpublished output | **Return output to review** (existing `resume_review`) |
| Retained output that failed validation | Guidance: inspect it before choosing to process again |
| Artwork, paid generation, portraits | Guidance: use artwork review (a fresh quote for paid generation) |
| Folder metadata | Guidance: a fresh preview is required |
| Inspection finding | Guidance: scan the library again |
| Failed/blocked/cancelled with its source missing from the catalog | Explanation: scan the library first |
| Failed or blocked, nothing written (`safe_failed_retry`) | **Retry** (existing `recovery/retry-failed`): rechecks the source and settings and queues the job; it never starts the queue |
| Cancelled, or failed/blocked otherwise | Guidance: view the job and queue it again through its existing review |

Before either action, History refreshes state and refuses if the job's version, status or recovery path has changed since the row was shown. The server then re-checks the version, and the source fingerprint or output file, through the same code the inspector uses. Requests from the browser are recorded with the operator as initiator. Filters stay as they were, and the list keeps its scroll position after an action and after closing the inspector.

## Not yet

- Rule and AI initiators, until those features exist.
- Home's "work accomplished" summary, which will link into this screen with filters applied.
