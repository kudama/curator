# Queue implementation evidence — 2026-11-17

Draft Curator PR #57; application base main 9d7cbc4. This is development evidence using synthetic state, not deployment, Plex or real-media acceptance. Forge local worker failures are recorded in queue-contract.md and Forge #76; no local-worker patch was accepted. This implementation is senior-controller authored.

## Implemented for review

- Authenticated file-queue/order endpoint with exact global waiting snapshot/order fields; state exposes the matching file_queue snapshot and shared pause state. Existing session/origin checks remain enforced.
- Upscaling, Encoding and File operations lanes: one detailed head, compact waiting rows, additional concurrent progress rows, actual configured global limits and pause/start controls. Unavailable file progress is labeled rather than invented.
- Global Start queue/Pause after current, explicit Across all libraries scope and wrench control; separate view filters and plain counted status links. Ready review is reached through the top links, not a second sidebar destination.
- Waiting-only within-lane dragging and select/move alternatives compose a full snapshot while preserving hidden jobs and other kinds. Drag captures its original snapshot before polling. File operations expose reorder only; no unsafe generic removal.
- Temporary plum/pink inspector and matching current-card indication, source facts/saved settings/accurate waiting position, existing safe cancellation and comparison acceptance gates. Escape restores the queue without starting or pausing jobs.
- Inline workspace/editor feedback replaces the fixed bottom-right overlay. Errors require explicit dismissal; later successes retain Undo/actions, and task feedback is scoped to its task. Recent activity is collapsed after current work; notification opt-in is in Settings.

## Checks and observed evidence

- Python: 410 tests passed, three optional tests skipped, including queue regressions and synthetic session/origin API checks. compileall and diff whitespace checks passed.
- JavaScript: 63 tests passed via the embedded Node test runner, including concurrent visibility, publication deduplication, filtered order composition, captured stale drag snapshot, cross-kind rejection, file ordering without removal, review target visibility and inline feedback/Undo. Syntax parsed for app/workbench/queue-board/collections; CI also explicitly checks the new component.
- Real Chrome, isolated localhost preview with a fresh temporary database, no Plex credentials and no real media: checked both themes; moved a waiting task to top and bottom; observed its position update from 1 to 2; removed it back to suggestions; observed inline feedback without an overlay; opened and closed pink details using Escape with queue counts unchanged. No browser warning/error logs were observed. Preview server stopped after checks.
- [Actual board screenshot](implementation-board-check.jpg), [actual waiting inspector screenshot](implementation-panel-check.jpg). These show a synthetic paused queue with placeholder thumbnails; they are implementation evidence, not replacements for the approved design renders.
- Narrow breakpoint acceptance is **not yet verified**: the available Chrome viewport override did not change the observed 1245-pixel viewport. It was reset. Responsive CSS exists, but this is not a visual pass at a narrow width.

## Remaining gates and work

1. Preserve unmapped kinds: when metadata/home/artwork/join/other pending task kinds or unmatched cleanup receipts exist, the existing queue layout remains available rather than dropping jobs or inventing a fourth lane. The proposed Other work presentation still needs its render decision. The Ready link similarly keeps non-video review tasks reachable in the existing queue instead of hiding them in the video-only inbox. This fallback is temporary, not completion of the mapping requirement.
2. Finish narrow-width, large-queue, active/failed/file-operation inspector and polling/focus acceptance. Progress is synthetic-test covered; no real file copy/encode was run.
3. File-operation removal needs reviewed operation-specific owning-state/caller recovery; it is deliberately not advertised by these controls.
4. Comparison screenshot defect Forge #91 is still open. Existing comparison readiness/version/hash gates are preserved; this PR does not claim its intermittent transport cause is diagnosed.
5. Forge worker tool/result compatibility remains unresolved under #76. No permission/routing/model-download changes were made to work around it. Frontend worker handoffs still require pinned permitted excerpts.

Do not mark the queue redesign complete, merge the held experiment #52, deploy this draft, or infer approval for real media/provider operations from these checks. Library/metadata/artwork/generation/archive tickets remain separate work.
