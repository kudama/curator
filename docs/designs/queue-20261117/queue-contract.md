# Queue implementation contract — 2026-11-17

Senior review for Forge #86; approved direction remains feature-lock.md and its renders. Development is authorized. This contract adds no new operator screen. Application baseline: main 9d7cbc4; approved specification 868cac9. Worker snapshot a0b8b4704b8333336f9eda303ab387f0d9b43d7a has identical selected application sources. No production state is used in tests.

## Identity and presentation

| Lane or state | Authoritative identity | Order and controls |
| --- | --- | --- |
| Upscaling | task.id, kind=upscale | Existing global task order; waiting-only mutation |
| Encoding | task.id, kind=optimize | Existing global task order; waiting-only mutation |
| File operations | file_operation record.id | Shared I/O admission, maximum four; waiting-only order contract below |
| Ready to review | finished task.id/version | Separate counted review entry; comparison readiness gates acceptance |
| Failed or interrupted | task.id or file-operation id | Inspect cause; no automatic retry or startup replay |

File-operation payload.task references its owning task; payload.receipt references a cleanup receipt. The file-operation ID is the row identity during I/O, with the task/receipt retained as its navigation target. A publishing task with an admitted file operation must not also appear or count as a second active job. After terminal I/O, the task's current state governs review/history. Multiple genuinely distinct operations remain distinct rows.

One head card per lane does not mean one running job: every concurrently running operation retains visible progress. Unknown progress is shown as such; do not fabricate percentages or ETAs. Running records are never draggable. Opening Details is read-only and preserves order, pause, selection and scroll.

## Existing guarantees to retain

task_queues.py owns global per-kind limits and pause. Lowering a limit drains current work; it does not kill workers. queue_workflows.py owns global waiting order and exact id/version snapshots. A filtered task reorder replaces only those slots in the full global permutation; hidden tasks retain their positions. Source exclusion, approval/version checks and noninterruptible publication remain in their existing owners.

FileQueueWorkflows currently persists each operation before starting admission, selects the first waiting record, and marks waiting/running records interrupted at restart. Existing synchronous callers wait for completion and must continue doing so. No order mutation may start, stop, retry or execute a job.

## Minimal file-order backend slice

1. Persist only an ordered list of file-operation IDs in settings under file-queue-order:global. Existing records without this setting retain created order; newly admitted IDs append after explicitly ordered waiting IDs. Stale IDs are harmless and pruned when replacing order.
2. file_jobs() must expose waiting records in the same order used by admission, so display and execution cannot disagree. Running records remain independently visible and cannot be selected by the mutation.
3. file_queue_snapshot() returns the exact globally ordered waiting set as id/updated pairs. change_file_queue_order(expected, order) accepts only that current snapshot and a duplicate-free permutation of all current waiting IDs. Validate shapes before mutation. Use the existing service lock plus one store transaction for check-and-write, shared with admission.
4. Arrival, admission, restart recovery or any waiting-record update invalidates an old relevant snapshot. Completion of an already running operation need not invalidate an unchanged waiting set. A stale request rejects atomically and requires refresh; no partial movement. Ordering does not alter payload, timestamps, task status, approvals or media.
5. The initial backend API is global and reorder-only. A later HTTP/UI adapter must merge a filtered within-type move into that complete order before submitting; it must reject cross-type dragging. Do not advertise filtered scope or removal until the adapter exists and is tested.
6. Do not add file-operation removal here. A waiting publish, cleanup, repair or restore can have a waiting caller or an owning state transition. Returning those to suggestions requires operation-specific rollback semantics, reviewed separately. Never use task cancellation as a substitute.

Checks: persistence and FIFO fallback; exact permutation validation; stale arrival/admission/update rejection without mutation; shared admission follows reordered waiting jobs; active record remains untouched; restart still holds work; concurrency and pause/max-four regression suite. Synthetic records only.

## Other task kinds and design gate

Metadata, folder metadata, home-video, playlist, generation, join, rename and group work must remain visible and actionable. Three approved lanes do not authorize dropping these jobs or mapping every task to Encoding. Proposal for a later render: a compact Other work disclosure beneath the three lanes, with actual type/count/state and existing detail actions. This is a proposal, not approved UI; obtain a render decision before implementing that addition. Independent backend work and approved three-lane components can proceed without this decision.

## Worker readiness and evidence

- Native analyst task 227552c5f38344719f5ac913a4afc756 read the selected file ranges but failed result validation; no patch accepted.
- Compatibility analyst task e6b303f09d2740c0bad0883412d16925 failed tool_denied; no patch accepted and no permissions expanded.
- Native implementer task 54b47e78614c4698a66e55a9d460bdfc failed sources_not_read without a source-read audit. No patch accepted. These failures are recorded on Forge #76; stop retries of the same handoff. The initial backend implementation is senior-controller authored, not attributed to a successful local worker.
- Selected file_queue.py SHA256: 2f4ec496aa3d9f32018766f4b8a6e1cc042c2030c4c1c09d1a10f58518ba9256. task_queues.py: bd1a4ce6c4389a90e89e9a65ea58c6ff621a8f409d57b30f40bd7d901d84e2e7. queue_workflows.py: 7b96324911b91e69dffaaa3b9aab37f5004d8f448108174b3260cfdf655ebed4.
- Existing test_file_queue.py: four synthetic tests passed before changes. This proves the local baseline, not deployed acceptance or worker readiness.
- Initial implementation adds four focused tests; all 35 queue regression tests passed after the change (file, task-type, universal, controls and order suites). HTTP/UI integration and operation-specific removal remain outstanding.
- Keep one local-model job at a time during the separate Foundry model download. Do not alter that download, routing, permissions, limits or the production Curator service.

Frontend workers need committed Markdown excerpts with original path, immutable revision/hash and exact line mapping because current read grants do not include JavaScript/CSS/HTML. This contract does not expand grants. PR #52 remains an unaccepted exploratory design; do not merge it as the approved screen.

PR #52 review: alignment fixes, comparison timeout/error handling and inspector-open layout hooks may inform focused later changes. Its horizontal/grouped queue, toolbar layout and incidental screen behavior are superseded by the approved three-lane render. Comparison transport changes require their own diagnosis/tests under #91, rather than cherry-picking the whole experiment. No code was copied from that PR into this backend slice.
