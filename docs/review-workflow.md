# Reviewing a processed video

Open **Review & Publish** for a result marked **Ready to publish**. Curator prepares
the original/output comparison automatically. **Accept & publish** becomes
available after all comparison images load, and starts publication without a
second confirmation. The original-retention, source/version and publication
verification checks still apply.

If preparation or an image fails, use **Retry comparison**. Closing the panel or
opening another task prevents an older comparison from populating that panel.
Encoding presets stay in processing setup rather than completed-result review.

The file overview shows each completed processing task as **Ready to publish**
and does not automatically select another processing suggestion for that file.
Explicit existing selections remain available.

Multipart joins retain their separate boundary-comparison and confirmation
workflow. Batch acceptance retains its count confirmation. Universal queues,
bulk rejection/reset and continuous review are tracked separately.

## Comparison preparation checks — 2026-11-17

Preparation requires all four original and all four processed screenshots before
the server reports ready. A partial extraction now identifies the incomplete
side and leaves the task awaiting review with publication readiness cleared.
The browser still independently waits for every required image to load.

Concurrent preparation requests for one task share an operation lock. Before
certifying readiness, Curator rechecks the current task status, version and
source/output identity, and updates that current record. A late request cannot
restore an old awaiting-review record over a publish, reset, deletion or new
output. Preparation does not publish or automatically retry a job.

Synthetic validation covers complete/partial extraction on either side, changed
task status/version/output/deletion, and concurrent preparation. This fixes
confirmed source defects; it does not establish the cause of the operator's
intermittent screenshot failure. Prior successful image requests do not rule out
connection or decoding failures. No real media or deployed service was changed
for this validation. Runtime diagnosis/recovery acceptance remains Forge #91.
