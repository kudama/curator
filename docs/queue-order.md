# Queue grouping and order

The Queue screen groups by Status (default) or Task type. Grouping changes presentation; each waiting card shows its actual queue position. Drag the arrow handle onto another waiting card to place it before that job. Running/publishing jobs cannot be dragged or removed through bulk controls.

Select waiting jobs individually, by group or across the current library. Move selected to top/bottom preserves their relative order. Remove selected and Empty waiting queue require count confirmation, return waiting tasks to suggestions with their settings retained and approval cleared and keep media, outputs, task history and running jobs. Empty applies to all waiting jobs in the selected library, including jobs hidden by a filter.

Order is saved in private settings without a schema migration. Newly queued tasks append after saved waiting tasks. The runner reads the latest order before each claim; reordering during processing affects the next waiting jobs. Exact ordered ID/version snapshots reject stale views, cross-library IDs and jobs that have started. A failed request is not automatically retried.

Upgrade only while idle. Back up the database, preserve queued approvals, restart explicitly and refresh the page. New controls are capability-gated on older backends. No reorder/removal should be used as a live acceptance test without operator intent.

## Removal semantics in0.3.1

Remove from queue, selected removal and empty waiting queue return tasks to recommendations. They do not start work. Cancelling running work remains cancellation/history. A one-time upgrade repairs legacy cancelled tasks only when their latest audit event explicitly records single/bulk queue removal. Deleted tasks, other cancellations, completed work and ambiguous history are untouched. Plans, presets and outputs are retained.
