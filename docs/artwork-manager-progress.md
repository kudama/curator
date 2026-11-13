# Artwork Manager implementation evidence

2026-11-13 (America/Los_Angeles). Incremental implementation; issues #3–#6 remain open. No deployment, production Plex changes, authenticated Mage calls or paid generations performed.

## Implemented in this slice

- File-level Metadata Manager / Artwork Manager entry points and views reuse the same task/editor. Switching preserves pending DOM inputs, file selections and the catalog selection. Saves affect the active manager; discard protection covers pending changes in either view.
- Existing ratio defaults retained; manual prompt ratio override added. Imports preview with `object-fit: contain`. No implicit image transformation.
- Shared cover now uses the existing folder preview / approve / queue / verified image-readback flow, including direct/recursive scope, stale-source checks and no-op skipping. Physical folders are explicitly described as unsupported artwork records.
- Existing local branding preset registry expanded from four/five entries to one through fifty. Create, duplicate, rename, delete, edit optional negative/model/ratio/resolution defaults, and save current prompt as a new style. Existing preset definitions and old task records remain intact.
- Explicit optional Mage discovery uses documented `GET /v1/architectures` and `GET /v1/account`. Mango 3 is selected only when the live catalog advertises it; no fallback to Mango 4. Optional balance failure does not break manual work. No provider POST generation/upload endpoint exists in this slice.
- API credential is separate from public settings/state, owner-only local file, no redirects or raw provider errors. macOS Keychain was considered: current stdlib-only app has no Keychain abstraction, so this slice uses the specification's restrictive-file option; Keychain migration remains open.
- Folder portrait preview snapshots an explicitly selected saved profile and changes matching names only; other credits and nonmatching titles stay intact. Reject stale profile revisions, conflicting shared-cast replacement and portrait-based automatic folder defaults. Existing profile upload/editor remains usable.

## Verified

- 278 Python fixture tests pass; three optional media integrations skip on this host.
- Python compilation; all three UI script syntax checks; clean whitespace check.
- Synthetic browser: direct manager entry, pending title survives switching, active-manager save state, hidden-draft discard warning, existing styles, duplicate/rename/save style. Fake Plex only; missing fake collection routes limit picker acceptance in this preview.

## Remaining work, not claimed complete

- #3: durable individual artwork drafts/review tasks across restart, independent folder manager views, unique per-title batch artwork, persistent ratio overrides and explicit crop/pad derivatives; broader browser regression coverage. Existing single-item import/publish remains its explicit-save workflow.
- #4: resolve and display all optional style defaults in generation plans with immutable style/settings snapshots, per-title folder prompts, description field and successful-generation save-as. Optional fields are currently stored for future generation planning; they are not sent to Mage.
- #5: paid async generation, reference upload consent, model-specific validation, reliable selected-config price estimate/quote and batch cap, durable request/idempotency recovery, bounded retries/cancellation, local result retention and accounting. These are not implemented. Discovery alone is not an adapter acceptance result.
- #6: portrait tools fully separated from credit editing, explicit item subset selection, stronger identity disambiguation than a name match, native Plex cast transport/display/readback validation on an authorized disposable library. This slice is a name-matched preview foundation, not proof of identity transport or durable native Plex rendering. Retain existing manual fallback.

## Mage documentation checked

Read official documentation on 2026-11-13:

- [Mango schema](https://docs.mage.space/api/models/mango): `POST /v1/mango/generate`; Mango 3 is `mango-v3`, supports 1K/2K, documented ratios, `image` / `additional_images`; no negative-prompt field listed.
- [Architectures](https://docs.mage.space/api/endpoints/list-architectures): live schemas/options and architecture-default Gems price.
- [Account](https://docs.mage.space/api/endpoints/get-account): `GET /v1/account`, `gems.balance`.
- [Billing](https://docs.mage.space/api/billing): settings affect price; exact charge returned after acceptance. Cancellation keeps the charge; auto top-up can charge the payment card. No selected-config quote endpoint found in reviewed documentation. Do not treat catalog-default Gems as a Mango 3 quote or probe prices by submitting a generation.
- [Python SDK](https://docs.mage.space/api/sdks/python): persisted idempotency key and request identity are required for future safe recovery; timeout does not mean provider cancellation.

Project boards could not be read: current CLI authentication lacks `read:project`. Live repository issues and specification were inspected; no permission expansion attempted.

## Follow-up implementation — 2026-11-13

Supersedes the remaining-code list above where described below. PR #7 merged as `17406940d9bd618183e93149ba3a274b795a64cd`. User confirmed Mango 2, 3 and 4 are all acceptable; Mango 3 remains the starting default, with explicit model overrides validated against live options.

- Durable artwork tasks retain imported original, transformed candidate, prior Plex image, destination identity, ratio/settings and immutable style snapshot. They enter Review without publishing. Existing background publication verifies destination, before-image hash and selected-image readback; stale, missing or corrupt inputs block safely. No mounted source video is required for artwork-only review. Originals/candidates stay available for manual recovery/download.
- Local contain/pad and center-crop previews preserve proportions, with explicit target-ratio overrides stored in the task. No transformation is implicit.
- Folder managers now share scope/navigation but separate their inputs and preview payloads. Saving defaults preserves the inactive manager's saved defaults. Unique imports and per-title style plans use explicit title checkboxes; no-op images are skipped.
- Preset descriptions and optional defaults resolve into saved plans; destination ratios and explicit overrides take precedence. Folder plans have distinct title/summary context. Save-as from a saved/generated plan preserves resolved prompt/model/ratio/resolution/negative instructions. Deleted/renamed presets do not mutate old tasks.
- Mage jobs use the existing queue/task store, not a second engine. A short-lived one-use price receipt and explicit outbound-prompt/Gems consent precede queueing. The selected configuration must match the live catalog's priced defaults. Price/settings are rechecked before the first paid attempt; increases block. Request body, credential identity, idempotency key, attempted boundary, request ID and billing persist. Transient request retries are bounded; restart recovery is explicit. A known request is polled without resubmission; an uncertain submit reuses its original body/key. Cancellation does not imply a refund. Completed results download privately before entering Artwork Review; generation never publishes to Plex.
- Multiple candidates have distinct task/request identities, explicit total-cost consent, retained outputs and sibling comparison. Model-specific options are validated live. Result downloads refuse redirects, non-HTTPS/unverified hosts and credential forwarding.
- Reference images can be staged locally and previewed; they remain blocked from submission when the provider has no verifiable price for the reference configuration. No media is uploaded during scans, planning or model discovery. Implicit `@handle` references are also refused under default-only pricing.
- Local portrait management creates reusable identities from an explicitly selected existing credit and replaces portraits without Plex writes. Target plans specify each title and credit index, retain originals/candidates and reject stale profiles or mismatched identities. Native portrait publication is explicitly blocked, including the prior folder-portrait path; local image download/manual fallback remains available. Credit names/roles/order remain in Metadata Manager; per-file portrait acquisition lives in Artwork Manager. The legacy shared-folder cast editor remains available.

### Validation and remaining external acceptance

305 Python tests pass (three optional media integrations skipped), plus compilation, all three UI syntax checks and whitespace checks. Synthetic browser verified image import, contain/pad conversion, durable Review with settings/original/candidate, independent folder managers retaining recursive scope, and exact-title per-item plan creation. No real Mage authentication, paid requests, production media writes or deployed-app restart performed.

**#5 remains limited by provider pricing/asset-host validation:** reviewed docs publish architecture-default cost, not a quote for arbitrary Mango 2/3/4 settings or references. The app cannot safely infer those prices. Live account/provider acceptance and actual result-host compatibility remain unverified. Do not mark full reference-generation acceptance complete on fixture evidence alone.

**#6 native transport remains blocked with manual fallback:** no disposable Plex server/version/agent was identified for authorized verification. No Mac-local URL is presented as a working Ubuntu cast transport. This matches the issue's explicit blocked/manual-fallback alternative; it does not claim durable native portrait display.
