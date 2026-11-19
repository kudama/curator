# Curator — feature lock, 2026-11-17

Execution update, 2026-11-17: Mike authorized development with Forge after the specification lock. The earlier execution hold below is historical. Approved scope may now be developed and reviewed; unrendered-screen approval gates remain. This does not authorize deployment, production service changes, real media/Plex writes or paid generation. See [queue implementation contract](queue-contract.md) for the first bounded handoff.

This is the consolidated operator-approved feature direction and latest wording for the queue, library and artwork workflows. It links the detailed acceptance packets and supersedes earlier conflicting drafts. **This instruction locks specifications/tickets, not execution. No code, worker dispatch, merge, deployment, service restart, generation/spend or real media/Plex actions until Mike explicitly authorizes execution.**

## Source of truth and render precedence

- [Queue and pink inspector](README.md), Curator #53, Forge #86–#92.
- [Library/Metadata/Cast](library-workflow.md), Curator #54, Forge #93–#99.
- [Artwork targets/editors/batch](artwork-workflow.md), Curator #55, Forge #100–#105, existing portrait handoff #98.
- [Simple generation panel](artwork-generate-simple.png), Forge #106 and cost/budget work. This is the final visible generation direction. The earlier dense prompt/settings/budget/checkbox render is rejected and must not be used for implementation.

Written scope, data and geometry requirements govern incidental generated-image details. Sample images/names/counts/Gems/ETAs/build labels are illustrative, not runtime evidence. Current application baseline last verified earlier in this session: Curator 0.5.0/9d7cbc4; verify actual source/deployment before any later work. PR #52 is an unmerged held experiment, not the approved UI. Documentation-only branch is not a deployed release.

## 1. Queue and review

- Universal cross-library queue with shared per-type limits, three vertical lanes: Upscaling, Encoding, File operations. File copy/delete/publication/cleanup uses a shared maximum four. Preserve existing other task kinds visibly through the reviewed state mapping; do not silently hide them or invent a fourth lane.
- One detailed square-ish head card per lane; compact ordered waiting rows below. Every additional concurrent running job still has visible progress. Show actual state/progress and measured ETA when available.
- Start queue / Pause after current with explicit Across all libraries scope, separate from view-only Library/Search. Wrench opens limits. Plain text counted status links; no redundant Ready for review sidebar item. Navigation includes Queue, File management, History, Settings. Fixed lanes need no Group by dropdown.
- Drag/reorder only waiting jobs within their operation type. Provide keyboard/select alternatives and contextual Move to top/bottom/Remove links. Removal returns tasks to suggestions, preserving settings/media/outputs rather than canceling. File-operation FIFO needs a safe reviewed mutation contract before UI advertises reordering.
- Temporary pink/plum right inspector matching C logo, pink selected-job outline, readable text, close/Escape restores lane view and position. Waiting: saved settings/order/actions. Running: progress/log/safe cancel only. Failed: cause/recovery. Opening Details never mutates, pauses, approves or publishes.
- Review opens comparison automatically, hides completed-job preset setup, and single Accept & publish has no extra popup. All required samples must load before acceptance; retain version/source/output/hash/retention gates. Diagnose the reported image failure rather than call it fixed from later successful requests.
- Ready to review supports continuous accept/reject/skip/keyboard/resume and bulk decisions. Bulk accept has one explicit risk/count/scope warning. Reject resets to actionable work, not canceled. Existing remembered defaults/readiness/safe retries/recovery/summaries remain intact.
- Current jobs take priority; recent activity collapsed below them. Notifications are optional in Settings. Remove bottom-right overlay toasts app-wide: scoped inline feedback, persistent errors and reliable Undo without obscuring actions.

## 2. Library and metadata

- Group by task has distinct Metadata and Artwork groups. A grouped row opens the relevant editor directly, without file overview plus another Review click. Checkboxes remain independent; no unrelated task auto-selection.
- Metadata Select all → Edit selected metadata → exact before/after preview → approve and queue. This works across folders; do not reference unavailable Edit folder. Only checked/explicitly changed fields apply; no incomplete/no-op queueing or accidental shared titles/descriptions.
- Rename user-facing Tags/genres to Categories, keep Plex genre mapping. Categories and Collections search/multiselect and explicitly Create new draft values. Typing/Create/preview never writes Plex; changes occur only when approved queued work executes. State bulk add/replace/clear semantics.
- Remove Labels controls without clearing existing labels, smart collections, defaults or approved plans. Keep Collections separate. Separate File management near Queue; no rename/join/File tools inside metadata editors.
- Metadata owns cast names, roles and order. Shared bulk Cast is unchecked by default and explicitly applies to all N selected files with preview. Untouched/unchecked cast preserves each file's credits.
- Artwork owns portraits. Manage portraits opens People for identified people and preserves unsaved context; no silent save/discard/provider action. Cast portraits are person-owned, not independent copies per media credit.

## 3. Artwork types, targets and batch scope

| Artwork | Owner | Format |
| --- | --- | --- |
| Cover | Each media item | 2:3 or 16:9 explicit choice |
| Background | Each item or explicitly shared item/folder group | 16:9 |
| Collection poster | Collection itself | 2:3 |
| Collection background | Collection itself | 16:9 |
| Square art | Item or collection; mobile use | 1:1 |
| Logo | Title/collection/brand | True-alpha PNG, intended proportions, not forced square |
| Cast portrait | One cast person | Always 1:1 |

Home-movie 16:9 and movie/TV 2:3 covers are overridable defaults, not asserted Plex restrictions. Target links Media items/Folders/Collections/People are distinct from asset types. Collection art never changes member art, membership or smart rules. Folder/shared-background flows enumerate exact affected items/recursion; no silent fan-out to current/future descendants or unsupported native folder artwork.

Media/collection editor has type-correct previews and Replace/Crop/Generate/Create logo entry. Keep separate assets/originals; never stretch images. Unsaved change is a status badge, not a button: one badge per changed asset; no changes means Preview changes disabled. Preview compares current versus draft; approve only changed targets. No automatic publication.

Multi-select opens a batch editor with each file's own cover/ratio/candidate; selection does not copy one cover to all. Backgrounds has explicit one-shared-image versus individual options. Square art/logos retain target ownership. Keep mixed/no-op/stale/partial results and selection across polling truthful.

## 4. Style guides and simple generation

- Reuse existing Branding presets as reusable style-guide templates. Initial named directions: gritty cinematic/dark photorealism, Grindhouse, Anime; guides remain editable/creatable/duplicable rather than hard-coded styles.
- Resolve guide text + artwork-type rules + actual item/collection/person/title context into a visible/editable prompt. Freeze guide/version/resolved prompt/context/settings in approved request provenance; later guide edits do not change queued jobs.
- Format, model, resolution and references are structured request settings, not enforced by saying 2:3 in prompt text. Official Mango fields include prompt, model_id, aspect_ratio, resolution, seed, image and additional_images; check actual model-specific schema/options before use. Do not assume a named provider style parameter, universal negative_prompt support or a transparent-background control.
- Entry: Artwork → select target → Generate under the relevant artwork type. Target and format carry through. Cancel/X returns to the artwork editor with drafts preserved. Opening generation does not submit.
- First view is deliberately small: title/target, Style dropdown, chosen Reference with Change, collapsed Advanced, cost and Within budget status, one priced Generate N options action and Cancel. Put prompt/model/resolution/reference details/candidate count/budget breakdown under Advanced; editing guide definitions is a separate manageable flow, not a dense default panel.
- No extra spending checkbox or second approve popup. The explicitly priced Generate action is the consent event, enabled only for the current estimated configuration and allowed budget. Actual outbound references must remain discoverable and identified before that action.
- Reference is the operator-chosen video frame, uploaded reference or existing artwork, not a random undisclosed still. Existing sampler positions 15%, 40%, 65%, 85% can supply initial candidates; Change opens selection. Show exactly what will go to Mage.
- Get request-specific cost estimate and account balance before generation, check/reserve budget, then explicit Generate. Changed model/size/reference/count invalidates the estimate and requires refresh. Keep setup/estimate, paid generation, candidate review and publication as separate stages.

## 5. Mage quotes and Gems budgets

Mage's documented MCP estimate_cost prices a request before generation without charging; get_account provides balance. A general equivalent standalone REST quote endpoint was not confirmed. REST catalog gems is the default-config price, not a quote for arbitrary settings. Inspect/verify a supported MCP integration (or a documented equivalent) rather than estimate all requests from the catalog default. No live/account/provider call occurred to validate this design.

- Per-batch Gems allowance and optional monthly Curator limit; do not invent the operator's amounts/default caps. Show current request total, candidate/request count, available balance and budget impact, with detail in Advanced/Settings.
- Atomically reserve allowances for approved queued/in-flight generations so concurrent batches cannot spend the same allocation. Reconcile actual charges, confirmed refunds and reservations; record provenance/idempotency and prevent duplicate paid submissions.
- Hold requests exceeding limits or lacking a usable current estimate. Never silently enable/top-up an account, change the configured model, retry uncertain charged work or increase budget. Account balance can change through other Mage clients: a Curator budget is not an account-wide provider guarantee.
- Distinguish estimate from binding maximum. Strict hard-cap behavior requires a dependable ceiling; an estimated price cannot be represented as provider-enforced. Cancellation/failure must not imply a refund without confirmation.
- Selecting templates/references, scanning, previewing or opening screens never authorizes paid generation. If quoting requires an upload, identify that data transfer and obtain the applicable explicit reference-sharing consent; do not hide an upload before approval behind a quote button.

Public documentation checked in this session: [Mango fields](https://docs.mage.space/api/models/mango), [MCP estimate_cost/get_account](https://docs.mage.space/api/mcp), [REST billing](https://docs.mage.space/api/billing), [architecture schema/default pricing](https://docs.mage.space/api/endpoints/list-architectures). Documented capability is not a tested connection or binding spend cap.

## 6. Transparent logo production

Provide two reviewed paths: styled exact-title text rendered locally on a transparent canvas using chosen font/style; or Mage-rendered lettering/logo on a flat contrasting background, followed by local ImageMagick background cleanup. Preserve original plus processed result. ImageMagick can manipulate alpha/remove a color but does not guarantee clean semantic subject extraction: inspect edges/halos/letter holes and avoid erasing logo colors.

Preview on checkerboard and light/dark backgrounds, preserve intended proportions and real PNG alpha, trim/pad without stretching, allow adjust/retry/discard/import fallback. Never bake checkerboard into the image or call an opaque returned PNG transparent. ImageMagick dependency/configuration and processing limits must be reviewed before installation/use; no install/processing authorized now. [Official options](https://imagemagick.org/command-line-options/) describe alpha, transparent/fuzz, text and trim operations.

## 7. Download, archive, review and Plex publication

Generate → download every returned candidate into Curator-managed storage promptly → review local copies → upload approved artwork to the supported Plex target → verify. Do not defer download until review or rely on expiring provider URLs. Preserve all generated candidates, including unchosen ones, and originals alongside cropped/alpha-cleaned derivatives.

The operator chose exactly these archive roots:

```text
Curator Artwork/
  Movies/
    Posters/
    Backgrounds/
    Logos/
    Squares/
  Collections/
    Posters/
    Backgrounds/
    Logos/
    Squares/
  Cast/
    [Person name].png
    [Person name]--[candidate/version].png
```

Within Movies/Collections artwork types, group by stable target identity plus readable title and generation/version, not colliding title-only filenames. Cast is one flat top-level folder, with square portrait files named by person and candidate/version when needed; no per-person subfolders. Preserve stable person identity in the index/manifest and use readable collision-safe suffixes for same-name people or versions; avoid duplicate records from repeated credits. Movies is the agreed top-level name for the media-side archive; confirm any future TV/home subdivision rather than silently rename the root. Preserve original/candidate/selected/processed relationships plus prompt/guide/model/settings/reference provenance/cost, target IDs and timestamps. Do not place secrets in sidecars/public repos.

Settings must provide one **Artwork archive path** for the top-level root on suitable local/NAS storage. The configured root contains Movies, Collections and the single flat Cast folder. Show the chosen path, validate access on explicit save/check, preserve it across restart, and report an unavailable path inline. Path changes must not silently move/delete/relink existing archives; any migration needs explicit preview/approval. The operator has not selected an actual mount/path. A Plex share can host a dedicated archive outside folders Plex scans as media; this archive is distinct from publication. Handle missing mounts, access failures, collision/partial writes and recovery explicitly. No automatic archive deletion or retention purge is approved. Importing the existing desktop image folder is a separate explicit, non-destructive mapping/dedup/preview operation; do not move/delete originals or publish imports automatically.

## 8. Remaining gates and acceptance

Feature direction is locked; dedicated File management, People/portrait, opened folder/shared-background, style-guide management and budget-settings views still need renders before their implementations. The latest simple generation layout supersedes the rejected busy view. No repeated approval is needed for unchanged already-approved screens; substantial deviations need review.

Before later execution, reconcile live issues/main/current grants, source-pin bounded work, preserve existing presets/tasks/receipts and isolate shared-file ownership. Senior Forge reviews local proposals and independently verifies behavior; worker success is not correctness. No automatic dispatch from Ready/Blocked labels. Current explicit operator hold remains.

Final synthetic acceptance covers empty/large/mixed-library queues, all concurrent workers, stale/filtered reorder, review/bulk reset/hash retention, direct metadata and bulk field/cast opt-in, category/collection creation with no early writes, accurate artwork ratios/alpha/scope, drafts and dirty handoff, quote invalidation/reservations/reconciliation/retry, local-logo edges, immediate download/restart/missing archive mount and target readback, both themes/keyboard/narrow layouts, inline feedback/Undo and approved visual match. Real Plex/provider/native-portrait/host recovery acceptance and deployment remain separately authorized; unsupported capability stays explicit/manual.

## Queue amendment — 2026-11-18

Operator requests a fourth Artwork generation column, alongside Upscaling, Encoding and File operations. Keep all running generation options visible with title, artwork type, model and option index/count. The existing typed concurrency limit applies to Mage (1–8); independent generation options may share a staged source while video source reservations remain protected. Each option keeps its own provider request/approval/billing/candidate identity. Generate approves the displayed quote, starts the Mage queue and navigates to its status; it does not leave a second Generate action or require another Run click. Completed candidates stay available for separate artwork review. No automatic publication or additional unapproved generation is authorized.

Small layout fixes in the same delivery: use Collapse all groups for both library grouping modes; use a fixed-width Generate action with status on a separate row. Existing batch-review navigation inconsistencies are identified but unchanged by this amendment.


## Library and queue correction — 2026-11-18

Approved: add Metadata as the fifth queue column, including local **AI assist** (formerly Home-movie analysis) and folder metadata. Hide columns without matching waiting, active, review or attention work; surviving columns stay compact (at most 360 CSS pixels each), aligned to the left, and shrink to fit narrower screens. Hiding empty columns must not stretch a single queue or its head card across the page. Processing limits remain reachable for hidden queues. Preserve per-type concurrency and ordering, including all parallel Mage options and file-operation preparation.

Remove the three manager shortcuts from the file suggestions overview; task-specific Review actions and deliberate editor handoffs remain. Pending saved video review groups appear under Ready to review; receipts without reviewable results appear in History. Failed preparation offers an explicit new preparation attempt using current task versions; never retry publication or generation automatically.

A rename completes after the filesystem moves and verification succeed. Do not force a Plex scan or require immediate Plex identity/metadata/artwork readback. Keep exclusive destinations, source fingerprints, sidecar receipts, rollback and automatic-trash protection. Preserve the stable asset identity while Plex still reports an earlier path, then reconcile it on a later scheduled Plex refresh. Old blocked renames are not retried automatically.


## Waiting queue disclosure — 2026-11-18

Keep every active job visible. Each queue column initially shows its first five waiting jobs, counting a waiting head card among those five. Put additional waiting jobs in a collapsed container with Show N more / Show fewer. Expansion is independent per column and survives background refreshes for the current browser session. File copy/delete and file preparation share the File operations column’s five-item allowance; Metadata and AI assist share Metadata’s allowance. Attention and ready-to-review results are never hidden by this disclosure. Keep total waiting counts and explicit Select all N selection scope; expanding retains the complete drag-and-drop and bulk ordering behavior.

Queue run/pause and selection/order controls, including metadata subtypes and file preparation, belong directly below the column heading and above every job card. Waiting counts remain beside the waiting list.

Renaming must retain unsubmitted non-file suggestions as suggestions, preserving drafts. Only approved or path-dependent unfinished plans are invalidated. Deleted tasks and provider receipts remain untouched. Repair existing rename-only blocked suggestions only when the latest audit record proves their previous recommendation state, unchanged draft and exact version transition; never queue, publish or submit a generation as part of this repair.


## Reference prompt wording — 2026-11-18

For reference-based family and pet artwork, use the exact automatic template `re-imagine this image in style guidance X`, replacing X with the selected style guide’s details. Do not append filename, summary, background or typography directives to this reference template. Attach the selected image through the existing provider image field; keep aspect ratio and resolution in their API settings. Refresh automatic wording when a reference or style changes, restore the existing text-only template when No reference is chosen, and preserve manually edited prompts. Apply only to new plans, leaving saved requests, quotes and provider receipts unchanged.


## Over-budget quote feedback — 2026-11-18

Check cost must report the estimated total Gems and number of options even when the batch exceeds its budget, together with the applicable budget and Gems over budget. Reservation/submission failures likewise report the estimate and remaining monthly allowance. Existing rejection gates remain in force: no generation approval, reservation or paid submission occurs from a failed cost check.

Artwork previews must fetch the current selected Plex images on reopening. If a verified Curator rename is pending and the old Plex key returns 404, resolve only a unique exact destination in the same verified library after checking the unchanged local fingerprint. Refresh the cached Plex identity/artwork and invalidate old thumbnails, preserving Curator asset/task IDs and all approvals. Refuse ambiguous or changed sources. This refresh never uploads, selects or replaces artwork in Plex.


## Artwork approval handoff — 2026-11-18

After Approve & queue accepts every artwork change, close that preview panel immediately, before background refresh. Keep it open for failed or partially failed queueing, and do not close a different panel opened while requests were in flight. No additional success popup is needed.
