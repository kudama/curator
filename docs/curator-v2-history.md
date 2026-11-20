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

## Not yet

- Recovery actions inside job history. The existing View and task controls remain the way to retry or recover.
- Rule and AI initiators, until those features exist.
- Home's "work accomplished" summary, which will link into this screen with filters applied.
