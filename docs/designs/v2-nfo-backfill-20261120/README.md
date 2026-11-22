# NFO and artwork backfill — proposed workflow, 2026-11-20

Design for issue #106. **Status: operator approved the displayed export review direction on 2026-11-21 ("this looks good") and confirmed export uses current saved metadata and artwork; review corrections below are pending exact-head cross-review.** It is the operator-facing workflow for the spec in PR #89 (`docs/nfo-generation-spec.md`, NFO-01 to NFO-07), which remains the technical reference and is reviewed there. This package is a static prototype with synthetic data. It is not served by Curator, exports nothing and writes no files. #90 (NFO export) and #91 (image sidecars) implement it after approval.

Baseline: v2 `146d6ede13fe28befe76bcf9c8c4f57c32061ffa`. Open `prototype.html`; `#s=` picks a scenario: `scope`, `preview`, `detail`, `approved`, `approve`, `queued`, `receipt`. Every count, footer, confirmation, queue card and receipt is computed from the scenario's policy and update approval, so they cannot disagree. All names, paths and counts are synthetic.

## Renders

| Render | Shows | Spec |
| --- | --- | --- |
| [scope.png](scope.png) | **Generate NFO files** in Library Manager → File management. Scope (selected files, folder, whole library), **Create missing files only** as the default, NFO and every available supported image | NFO-01, NFO-04, NFO-06 |
| [preview.png](preview.png) | **Create missing files only** (default): the Curator-written NFO is shown as Kept, not as an update. Summary counts; every item's exact video path, NFO destination and each image (poster, background, square, logo) as Create / Unchanged / Missing / Kept / Blocked with its source, format and reason; a partial-package warning | NFO-03, NFO-06 |
| [detail.png](detail.png) | **Also propose updates**, with the update **not approved**: field diff, unknown elements preserved, previous file retained; the update is marked "left out" and is excluded from the counts and the Approve button; cast portability (a private portrait reference is omitted and the portrait stays in Plex) | NFO-02, NFO-04 |
| [approved.png](approved.png) | The same plan with the update **approved**: it is counted and included | NFO-02, NFO-05 |
| [approve.png](approve.png) | For the approved plan, the confirmation says exactly what will be written and skipped, that nothing is overwritten without approval, that Plex is not refreshed, and that it runs only when the queue is started | NFO-05 |
| [queued.png](queued.png) | The export waits as **one job** containing the approved items in the existing **File operations** lane, with its limit, pause and recovery. Other queue types have no jobs, so they are hidden | NFO-05 |
| [receipt.png](receipt.png) | Job history receipt: initiator, per-kind outcomes, verified hashes, a failed image with a revalidating retry, "partial package, not a complete backup", "Plex was not refreshed" | NFO-07 |
| [phone-preview.png](phone-preview.png) | The preview at 390 px | — |

## Workflow decisions

1. **Entry.** A **Generate NFO files** action in the existing File management toolbar acts on the current selection. There is no new tab or health page. The panel is the existing inspector position, so the list stays visible.
2. **Three steps: Scope → Preview → Approve.** Planning only reads files and the Plex selection. Nothing is written before approval.
3. **Create missing is the default.** Existing NFO and image files are kept. Updates are offered only for **Curator-written** NFOs, each as a diff with its own approval checkbox; unapproved updates are left out of the queued job. Files written by other tools are never updated from here.
4. **Every supported image is shown, with Plex names.** Each kind (poster, background, square, logo) is listed whether it is created, unchanged, kept, missing or blocked. Missing kinds are reported, never generated. Formats follow the real bytes (a PNG poster is `poster.png`).
5. **Path association is visible.** Each item shows its exact video, NFO and image paths. **Shared folders** are blocked rather than written with generic names that would apply to other videos. **Multi-part** movies are skipped, as the Plex NFO agent does not support them.
6. **Partial packages are named as such.** Any plan with blocked, missing or failed items says "partial package, not a complete backup", in the preview and in the receipt.
7. **Cast stays as it is.** The export writes existing names, roles and order. A portrait reference that is not portable (a private Curator image, or a URL with a token) is omitted, and the portrait in Plex is untouched.
8. **Existing machinery.** Approval queues one job in the existing File operations lane: the same limit, pause, recovery and "never starts the queue" behaviour. The receipt is a Job history entry; changing export settings is a Curator history event.
9. **Staleness.** If a file, the Plex selection, saved Curator metadata or artwork, or the configuration changes between preview and writing, that item is planned again for review instead of being written.
10. **Sources are current and visible (operator, 2026-11-21).** The NFO is written from current Plex metadata, including edits saved in Curator. Each image is the current Plex selection, or artwork explicitly saved or retained in Curator where appropriate (for example a logo Plex has no selection for), and the plan shows which for every file. An older retained draft is never used in place of the current selection; when one exists, the plan says it is not used.
11. **Policy and approval agree with the manifest.** The footer names the selected policy. Under create-missing, Curator-written NFOs are Kept. Under propose-updates, each update needs its own approval; an unapproved update is excluded from the counts, the Approve button, the confirmation, the queued job and the receipt.
12. **No Plex side effects.** No refresh, agent switch, library change or artwork publication. Refreshing Plex stays a separate, separately approved action.

## Questions for the operator

- For a large library, should the preview open with a per-status summary and expand only blocked and update items (proposed), or list every item?
- Should "Retry failed" in the receipt re-plan only the failed files (proposed), or the whole item?
- Should shared-folder items offer basename-prefixed artwork names (`Video Name-poster.jpg`) in this first delivery, or stay blocked until the association rules are validated (proposed: blocked)?

## Boundaries

Design only: no export, agent switch, refresh or real file writes. No new dependencies. The technical rules (XML, identifiers, staging, safety) are in PR #89 and are not changed here.
