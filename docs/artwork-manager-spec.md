# Curator — Artwork Manager and Mage integration

Status: **Approved product direction; specification only, not implemented**
Recorded: 2026-11-13 (America/Los_Angeles)
Owner: Curator standalone application (`kudama/curator`)
Parent product request: [personal-ai-platform #9](https://github.com/kudama/personal-ai-platform/issues/9)

## Intent

Make Artwork Manager a first-class, independent workspace separate from Metadata Manager. Preserve selection, library/folder scope, local storage and the existing reviewed publishing lifecycle. Add optional direct Mage image generation without making Curator require Mage, a cloud account, or any additional runtime.

The current Curator snapshot already supports manual artwork editing/import, cast/profile pictures, folder-scoped editing and manual Mage prompt preparation; this specification expands those capabilities rather than replacing them.

## 1. UI and ownership

- Provide distinct **Artwork Manager** and **Metadata Manager** workspaces/actions in the existing local Mac workbench; keep the selected library, item(s), folder and recursive/direct scope when switching.
- Metadata Manager owns title, description, dates, cast identity/name/role/order, genres, labels, collections and other descriptive fields.
- Artwork Manager owns image acquisition, generation, replacement, previews and assignment for video posters/thumbnails, backgrounds, logos/square art, collections/folders where supported, and cast/person portraits.
- Both managers must use the same catalog, task history and underlying approved review/publishing services. Do not create a second task engine or duplicate cast identities.
- Existing manual upload/import and Mage prompt-copy workflow remain available when credentials or external generation are absent.

## 2. Artwork types and defaults

| Target | Default ratio | Notes |
| --- | --- | --- |
| Personal/home media primary cover | **16:9** | Plex home-video landscape presentation; allow override |
| Movie/TV traditional poster | **2:3** | Portrait |
| Background/fanart | **16:9** | Landscape |
| Square/folder/logo artwork | **1:1** | Only when supported by the target |
| Collection primary poster | **2:3** | Allow override for target display |
| Cast/person portrait | **Portrait** | Exact required dimensions/ratio depend on tested Plex transport |

Do not distort generated images: request a target-supported ratio, or preview an explicit crop/pad transformation. Preserve source originals and store local derivatives independently. Library profile and target type select defaults; user overrides persist in a saved generation task.

## 3. Scope and folder operations

Support direct or recursive folder selection with a preflight showing exact affected items and whether an operation would be a no-op. Actions:

1. Apply **one shared image** to selected titles.
2. **Generate unique art per title** using each item's context and chosen references.
3. Apply **one style preset** to all selected titles while generating independent artwork.
4. Manage folder/collection art only when a supported Plex target exists; do not assume physical folders have editable Plex artwork records.
5. Apply relevant cast portraits to selected folder titles **only for matching cast identities**, with explicit before/after preview.
6. Remember folder defaults and effective inherited settings; show whether a parent default or explicit override applies.

Always preview the target set, existing image, candidate replacement, and intended Plex destination. Skip unchanged/no-op tasks rather than moving them into Review. Bulk actions must never overwrite unselected media.

## 4. Artwork editor and reference material

- Choose existing image, upload an external image, import from local file, or generate with Mage.
- For video items, offer manually selected representative frames, plus existing/imported reference images; extracted frames remain local unless the user explicitly submits a generation.
- Provide editable title/description/context, freeform prompt and style preset; expose the resolved prompt before submission.
- Generate multiple candidate images as individually accountable requests, preview side-by-side, regenerate or discard, and select one.
- Optional text/title overlay: either request model typography or compose a local overlay, with independent preview.
- For people, select an existing reusable cast identity; support uploaded image or portrait generation. Changes to a shared portrait must list affected Plex items and require approval, not silently rewrite all credits.

## 5. Style presets

Reuse existing Curator visual style presets where represented in current code/state; inspect their implementation before schema changes. Do **not** create a competing preset library.

- Make existing presets (including Dark & Gritty and Bright if present) available in Artwork Manager.
- Create, edit, duplicate, rename, delete and select presets from the artwork workflow. Allow **Save current prompt/settings as preset**.
- A preset contains name, description, positive/style instructions, optional negative instructions, and optionally preferred model, ratio and resolution defaults.
- Target type and explicit user settings override preset defaults; show the final resolved values and prompt before submission.
- Presets are reusable for individual assets and folder-wide per-item generation; preserve current presets through upgrades and handle deleted or renamed presets in historical job receipts.
- Store preset definitions locally and allow portable export/import later only if justified; do not introduce a cloud preset backend.

## 6. Mage integration

Use Mage REST API from Curator's local Python backend behind an optional provider adapter, not a mandatory MCP runtime. The UI must remain useful without Mage. Official provider docs:
- https://www.mage.space/developers
- https://www.mage.space/developers/models/mango
- https://www.mage.space/developers/mcp

- User-configured API key, locally stored with restrictive permissions; never ship keys to browser JavaScript, logs, exported presets or public repositories. Existing local settings hold Plex token without encryption; assess OS keychain as the simplest preferable secret store before implementing.
- Model selection must be user-editable and dynamically validated against supported provider model options. **Default Mango 3 (`mango-v3`)**, not Mage's provider default Mango 4. Expose other available Mango variants without assuming all accept identical parameters.
- Provider endpoint for Mango family is documented as `POST https://api.mage.space/v1/mango/generate` with `model_id`, plus model-specific generation fields. Validate exact schema, image references, ratios, resolution and negative-prompt support at implementation time.
- Provide live/account Gems balance **if an authenticated REST account method or supported SDK method exists**. Mage documents `get_account` in MCP; do not assume that method exists at a specific REST URL without verifying it. Treat balance as optional when inaccessible.
- Quote estimated Gems cost before confirmation using a documented provider quote method where supported. Show actual billed Gems from completed response; warn before N candidate requests or a folder batch. No automatic spending on scans.
- Submit asynchronously, persist provider request identity, poll for completion, surface progress/status, allow cancellation where supported, and use idempotency keys for safe retries. Do not mistake failed cancellation for a refund or retry uncertain jobs without checking provider state.
- Rate-limit/concurrency handling, bounded retries with backoff, offline state and clear actionable errors. Keep the UI responsive while jobs run.
- Download selected generated assets to Curator's local state, with request/provider/model/prompt/settings/cost provenance, before provider links expire. Never rely on Mage as permanent storage.
- Home-video frames/cast photos and prompts may be private; clearly indicate which files will leave the Mac and require user-triggered submission. No uploads during catalog scans or local analysis.
- Generations do not publish automatically; candidates pass through explicit selection, Review and verified Plex Publish.

## 7. Shared lifecycle and safety

Use current Curator review/approval mechanism: select target(s) → choose/edit artwork → optional generation or import → compare existing/new → approve → publish → verify in Plex → Completed.

Keep Processing, Review and Publishing as distinct durable task states as already implemented, and preserve cancel, remove, retry and status/progress functionality. Preserve selected assets and pending work on navigation or restart. On failure to update a cast image/metadata record, show partial status and a recoverable receipt. Read back published artwork where Plex permits; do not infer successful display from a metadata update alone. Do not write Plex's database directly or replace source videos.

## 8. Delivery slices and acceptance

**A. Workspace split:** Artwork and Metadata actions are independent with persistent selection, existing editing/import and folder previews intact. Verify no regression against current automated suite.

**B. Target ratios and folder art:** Home-video 16:9 primary artwork defaults, portrait 2:3 commercial/collection posters, 16:9 backgrounds, 1:1 square; correct explicit override, unique/shared/per-title batch behavior, no-op handling and unsupported-folder behavior.

**C. Style presets:** Existing styles reused, editable/creatable/duplicable, current prompt saved as preset, folder-wide style applied to unique per-title results, old receipts stable.

**D. Mage adapter:** Mango 3 model default, optional credentials and provider, quoted cost, explicit submission, candidates and reference frames, safe polling/retries, cancellation, result retention, state recovery and cost accounting. Test HTTP with synthetic fixtures before authorized live account tests. Balance display only if verified REST/SDK capability.

**E. Cast artwork:** Identity-aware shared portrait library, explicit target set, folder-wide application to matching identities, tested upload/display/readback against selected native Plex version/agent. Plex cast-image transport is a known verification dependency.

## Explicit non-goals

No automatic AI generation during scanning; no silent Plex publication; no bulk alteration of all content on a folder/portrait edit; no hosted/cloud Curator requirement; no provider-specific logic in the core workflow; no new job engine; no assumption that every Plex library/agent exposes folder artwork as an editable target.

## Dependencies / open technical validation

- Inspect current source for preset schema, artwork routes, task state, folder defaults and cast-profile handling before editing.
- Verify Mage authenticated balance REST/SDK endpoint, cost quotation mechanism, exact Mango 3 request schema, resolutions and provider asset upload handling.
- Verify Plex cast portrait publishing/serving on a disposable test library; preserve manual fallback when unsupported.
- Run existing `unittest` suite, Python compilation and JS syntax checks; add target-specific integration fixtures.
- This document approves feature direction **only**. It is not deployment permission or a claim of implemented behavior.
