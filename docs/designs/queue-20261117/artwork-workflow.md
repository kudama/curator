# Artwork workspace — approved direction, 2026-11-17

**Latest governing scope:** [Consolidated feature lock](feature-lock.md), including later clarifications. It supersedes conflicting earlier wording below.
Status: approved for ticketing only. **No implementation, worker dispatch, merge, deployment, paid generation, service restart or real media/Plex writes until explicitly authorized.** Supplements [library workflows](library-workflow.md) and [queue design](README.md). These are written requirements and synthetic render references, not implemented-feature claims.

## Approved renders and precedence

- [Collection artwork](artwork-collection.png).
- [One media item](artwork-media-item.png).
- [Multiple selected media items](artwork-batch.png).

Written scope/ratio rules govern incidental generated-image geometry, sample data and build labels. These approve media/collection editor and multi-selection direction; the dedicated People portrait view and opened folder/shared-background view remain to be rendered/approved before implementing those screens. Do not repeat approval of unchanged approved screens. New substantive deviations need visual review. No running application code was changed to capture this design.

## Targets and asset ownership

Use a clear target switcher: **Media items, Folders, Collections, People**, with plain text links and active indication. Keep selected target identity/library visible in the pink/plum temporary editor. Scope, selection, drafts and actions must not be confused with global queue controls. File management and Metadata remain distinct workflows.

| Asset | Owner | Required shape |
| --- | --- | --- |
| Cover | One media item | Explicit 2:3 or 16:9 |
| Background | One media item or explicitly selected group/folder contents | 16:9 |
| Poster | One collection itself | 2:3 |
| Collection background | One collection itself | 16:9 |
| Square art | One media item or collection; mobile presentation | 1:1 |
| Logo | Media title, collection or explicitly reusable brand asset | Transparent PNG, original/intended proportions; not forced square |
| Cast portrait | One cast person, referenced by credits | Always 1:1 |

Use home-movie cover default 16:9 and movie/TV cover default 2:3 as configurable starting defaults, not a claim that Plex enforces them. Explicit per-item cover selection wins. Collection posters stay 2:3; backgrounds and square/portrait ratios remain as above. Preview with contain/crop while preserving proportions; never stretch. Cropping an existing image into a new type is an explicit operation producing a separate draft asset, not an implicit destructive conversion.

Logos mean isolated title lettering or brand mark with alpha transparency, as in the operator's Heretic example, not a full rectangular poster. The checkerboard belongs to preview UI and must never be baked into the PNG. Preserve alpha through import/crop/storage/publication. A renderer/provider producing opaque images is not a verified transparent-logo path.

## Single target and collections

Media editor shows Cover, Background, Square art and Logo, with correct format, current/candidate preview and actions such as Replace, Crop where meaningful, and Generate/Create logo. A draft-change label distinguishes changes from untouched assets. The whole footer remains visible with Cancel and Preview changes. Editing an item does not affect a folder or collection implicitly.

Collection editor shows Poster, Background, Square art and Logo for the **collection identity itself**. Editing collection art never updates member media, collection membership, smart-collection rules or metadata. Use stable library/server/collection identities, not a title match. Verify native target/destination capability rather than infer it from a UI tile or media endpoint.

Cast names, roles and order stay in Metadata. Manage portraits opens People for the relevant person identities and preserves unsaved metadata/artwork. Person-owned portraits are not one independent image per media credit; applying shared portrait updates to credits needs explicit identity-aware scope and existing safety gates. Coordinate Forge #98 rather than duplicate its handoff work. Native Plex portrait publication is currently guarded as unverified in source; preserve manual fallback until independently verified under separately authorized scope.

## Multiple selection and backgrounds

Select all or multiple items → Edit selected artwork → type-specific batch editor. Covers remain individual to each item, with filename, per-item 2:3/16:9 format, current/candidate preview and replacement/generation entry. Square art and logos similarly retain per-target ownership. Batch selection does not mean copy one cover to every item.

Backgrounds offers a deliberate **Use one image for selected items** option as well as individual artwork. Folder/group mode enumerates the exact affected items, recursive boundaries, exclusions/no-ops and intended images before approval. A folder grouping is not automatically a publishable Plex artwork target: if unsupported, show explicit selected-item scope/fallback rather than fabricate native folder art. Changing shared image or folder defaults never silently rewrites existing member artwork or later descendants.

No artwork changes from selection/navigation/upload choice alone. Only changed targets proceed to preview; untouched types/items stay unchanged. Preserve drafts when switching type/target or closing with explicit dirty-state handling. Do not couple a metadata save to artwork publication.

## Review, generation and durable processing

Use choose/import/crop or optional generation → compare/preview exact target changes → approve and queue → explicit existing review/publication/verification lifecycle. Preserve per-item/batch receipts, source/target versions and current-image checks, original/recovery artifacts, no-op handling, partial results and no startup replay. No direct Plex database edits or source-video changes. File writes/copy/deletion use existing bounded queue, shared max four, and safe noninterruptible commit behavior.

Generation links are setup entry points, not spending approval. Reuse existing Curator #5 guards: disclose outbound references, show selected model/settings/request count and cost/uncertainty, obtain explicit consent, retain provider identity/candidates locally and review generated results. Shared style may produce separate per-item results; batch selection or scan never triggers automatic generation/publication. No new provider, assumed account API or unsupported transparency guarantee is authorized here.

## Known source context and future checks

Planning baseline is main 9d7cbc4; re-read live main, specs, task ownership and current grants before dispatch. Existing artwork kinds, aspect overrides, imports, collection catalog, presets and guarded portrait workflow already exist and must be reused where correct. Current backend resolve_style defaults logo generation to 1:1 while the UI treats logos as original proportions: reconcile this against the approved alpha/proportion rule, not by globally changing all ratios. Curator #5 remains provider/SDK/cost acceptance, not a duplicate redesign ticket.

Future synthetic validation: media/collection/person/folder identity and scope, default/override ratios, actual square/2:3/16:9 pixel geometry, PNG alpha and checkerboard exclusion, crop/original retention, multi-item distinct covers versus shared backgrounds, mixed/no-op/stale/unsupported targets, partial errors, consent/duplicate-request guards, drafts/handoff/keyboard/both themes/narrow layouts and final visual match. Tests from earlier exploratory PR #52 do not establish acceptance here. Unverified native transport remains explicitly unavailable/manual, not successful publication.
