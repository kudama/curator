# Curator queue UI — approved design, 2026-11-17

**Latest governing scope:** [Consolidated feature lock](feature-lock.md), including later clarifications. It supersedes conflicting earlier wording below.
Status: design approved for ticketing. **Implementation, worker dispatch, merge and deployment are on hold until Mike explicitly authorizes execution.** This packet contains documentation and synthetic renders only. No code changes are authorized by this packet.

Execution update, 2026-11-17: Mike subsequently authorized development with Forge. The hold text is historical; the latest feature lock governs scope. The implementation is being reviewed in draft PR #57. See [implementation evidence and remaining gates](implementation-check.md); it is not deployed acceptance.

## Approved references and precedence

- [Three-column queue](queue-three-columns.png): the main screen direction.
- [Pink job detail panel](queue-pink-job-details.png): the final detail treatment, with the queue visible.
- [Waiting-job details](waiting-job-detail-reference.png): content and queue-management reference only. Its earlier horizontal list/sidebar treatment is superseded by the two renders above. Waiting details must use the final pink treatment too.

The written requirements below take precedence over incidental generated-image content. Synthetic counts, durations, filenames, thumbnails, build labels and ETA examples are illustrative, not production facts. The renders do not introduce player controls, a new scheduler, permissions or automatic operations.

## Main queue

1. Desktop workspace: three vertical operation lanes, **Upscaling**, **Encoding**, **File operations**, across libraries. No permanent empty inspector.
2. Each lane header shows running count, configured global concurrency limit, and accessible pause/resume control. Safe pause drains current work. File operations retain the shared maximum of four.
3. Only the head job gets the detailed square-ish card with thumbnail, filename, library, state, actual progress and measured ETA when available. Never invent progress or ETA. If idle, show the next waiting job as next, not running.
4. Additional concurrent running jobs remain visible as compact progress rows above waiting work. Never hide the second encoding job when concurrency is two.
5. Waiting jobs are compact ordered rows with filename, library, selection checkbox and drag handle. Only waiting jobs can be reordered. Selection and opening details are separate actions.
6. The global action is **Start queue** while startable, **Pause after current** while active, with **Across all libraries** visibly attached. The library/search controls affect viewing only and sit separately from this action. A wrench opens processing limits with tooltip, accessible name and keyboard support.
7. Above lanes: plain text status links with counts and a clear active indicator: All jobs, Processing, Waiting, Ready to review, Needs attention. No row of outlined status buttons. Do not retain a redundant Ready for review sidebar item; keep Queue, History, Settings.
8. No Group by control in the fixed three-lane view. Library filter and Search jobs remain. Show the real all-library scope of run/pause and processing limits even when filtering.
9. Recent activity is a collapsed, compact disclosure after current work. Historical failed receipts must not masquerade as current failures or lead to an unrelated attention view. Browser notification opt-in belongs in Settings, with a clear unsupported-connection explanation when applicable.
10. At narrow widths preserve all jobs/actions with a responsive layout; do not squeeze text unreadably or create horizontal overflow. Provide keyboard alternatives to dragging.

## Queue management

- Drag a waiting job within its operation lane to reorder it. Do not permit dragging across operation types or moving active jobs.
- Selecting waiting jobs reveals contextual text actions Move to top, Move to bottom, Remove from queue; preserve selected relative order and unrelated jobs.
- Removal returns work to actionable suggestions, preserves saved settings/media/outputs, and does not mean cancellation or deletion.
- Retain bulk acceptance/rejection in Ready to review: one explicit danger/count/scope warning for bulk accept, individual acceptance without extra confirmation, rejection resets rather than cancels. Start reviewing continues the existing comparison/next workflow.
- Global persisted order, per-kind queues, library filters and queued file-operation records must be reconciled before implementation. File operations currently have distinct FIFO records: do not draw a functioning drag handle without a safe implemented reorder contract. Do not replay publication/deletion through retries or reordering.
- Preserve visibility and access for existing metadata/home/artwork/join/other work. Forge must propose and obtain approval for any mapping not covered by the three named lanes, rather than hiding jobs or silently adding a fourth lane.

## Temporary task details

- Open a selected job in a temporary right panel. Keep queue context visible; close restores full three-column view and scroll/selection. Opening/closing never changes job state or pauses processing.
- Dark pink/plum background, pink border/heading accents matching the C logo, light readable body text. Matching pink outline identifies the selected underlying job. Main queue remains cyan. Do not communicate selection only through color.
- Waiting: source facts, saved settings, accurate queue position, Move to top/bottom, Remove from queue with its consequence explained. No false live settings or invented ETA.
- Running: actual progress/remaining estimate, saved settings, collapsed processing log, and cancel only where supported/safe. Never offer move controls on running jobs or interrupt a publication commit. Do not imply cancel rolls back an external write.
- Failed/blocked: specific cause and existing safe recovery action. Ready for review: source/output comparison and existing explicit acceptance/reset flow. Do not treat Details as approval.
- Close/Escape/focus handling and narrow-screen presentation must remain usable without losing state or concealing primary controls.

## Feedback and comparison loading

- Remove the bottom-right overlay toast throughout Curator: it obscures queue actions. Use inline feedback beside the affected job/control, announced accessibly. Persistent errors require explicit resolution; do not turn errors into disappearing success notices. Preserve Undo for reversible task removal and distinguish background publication from completion.
- The reported comparison screenshot failure remains a defect to diagnose, not a confirmed fix. During prior diagnosis preparation and eight image GETs returned 200, and a synthetic browser loaded all eight; intermittent network issues were observed. Retain source/version/hash checks, publish gating until all required images load, visible loading/error/retry state and protection against stale responses after navigation. No auto-publish or media mutation during validation.

## Engineering handoff and hold

Production/source baseline at planning: Curator 0.5.0, `9d7cbc4edaa69bfa3063ba38d3c6362960952a28`. Re-read main, issue status and runtime before any later execution. Existing unmerged PR #52 (`8506c5a4a21bc39b7d987e2c5411f4794b69ebff`) is earlier exploratory work, **not the approved three-lane design**; do not merge or deploy it as-is.

Forge owns architecture/state mapping, bounded local-worker source preparation, integration and independent review. Workers receive source-pinned, explicitly selected files or traceable committed Markdown excerpts when frontend source types are unsupported. Existing grants/limits remain unchanged. Controller success is not correctness evidence. No coding, worker submission, real-media actions, deployment, service restart or permission expansion under this ticketing authorization.

Future acceptance requires synthetic empty/large/mixed-library queues, concurrent jobs, reorder/filter/stale-state cases, waiting/running/failed/review detail states, inline errors/Undo, real-browser visual checks in both themes and narrow widths, and regression checks of existing safe queue/review behavior. Tests claimed for PR #52 do not establish acceptance of this approved design.
