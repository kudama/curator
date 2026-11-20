# Curator V2 — library NFO generation

Feature specification · 2026-11-19 (America/Los_Angeles)

## Purpose and confirmed starting point

Generate durable, portable NFO sidecars from the metadata the operator has already curated, for one item, selected items, a folder or an entire library. Avoid repeating manual work when Plex rescans or a library is rebuilt.

The operator confirmed that current cast names and portraits work. After selecting the Plex NFO agent, the supplied web screenshot also shows portrait artwork, year/categories, cast and related collection content. Preserve that working metadata and cast pipeline. This feature adds an export path; it does not require regenerating cast, replacing portraits or changing how existing Plex writes work. Actual NFO export/import fidelity remains to be demonstrated separately from the observed presentation improvement.

## Feature list

| ID | Feature | Acceptance |
| --- | --- | --- |
| NFO-01 | Library and selected export | Plan one item, selected items, a folder or a whole library with exact identities, destinations and counts. Support filters such as missing NFO, changed metadata and previous failures. |
| NFO-02 | Export existing curated values | Use a fresh, reviewed metadata snapshot and explicit field precedence. Preserve current cast names, roles, order and working portrait references; do not generate new descriptions, identities or artwork. |
| NFO-03 | Preview changes | Show which files will be created, unchanged, updated, skipped or blocked, with readable field differences and missing/unsupported fields. Planning performs no filesystem or Plex writes. |
| NFO-04 | Safe writes | Default to creating missing NFOs. Require explicit reviewed updates for existing files; retain previous contents, verify versions/hashes and commit completed files atomically. Never silently overwrite another tool's NFO. |
| NFO-05 | Durable batch jobs | Use the existing bounded file-operation queue, safe pause and recovery model. Show progress and per-item outcomes; retry only failed, revalidated targets. |
| NFO-06 | Configuration and history | Define export policy per library, show effective settings, and record who exported what and the verified result. Automatic updating is a separate opt-in policy. |

## Entry points and flow

In Library Manager, offer **Generate NFO files** for the selected scope. In the separately designed Configuration area, expose NFO defaults within library metadata/export settings. Do not add another top-level tab or health page.

1. Select the scope and export policy. Default: **Create missing files**; existing files are preserved.
2. Read current item identity, metadata, mapping and existing sidecars. Preserve known operator edits; unresolved Plex-versus-Curator differences require review rather than arbitrary source precedence.
3. Preview exact paths and field changes, with before/after comparison for existing NFOs. A library preview can summarize large sets and expand individual items.
4. Explicitly approve the plan and queue it. Existing approvals/settings are captured with the job; later configuration changes do not rewrite them.
5. Track Created / Updated / Unchanged / Skipped / Failed results in Job history. Configuration changes belong in Curator history.

A successful export means the sidecars were written and verified. **Refreshing Plex is a separate action**, with its own identity/metadata-preservation checks. Exporting never switches an agent, migrates a library, starts a metadata refresh or publishes new artwork automatically.

## Output and field coverage

Use UTF-8 XML and the supported Plex/Kodi NFO vocabulary. Escape XML safely; preserve Unicode and multiline text. Produce deterministic output so unchanged data does not cause repeated rewrites.

First slice: movie-style records, including supported personal-media libraries. Use matching `<video filename>.nfo` destinations where the target layout supports them; allow `movie.nfo` only when it unambiguously belongs to a single movie. Check multi-edition/shared-folder layouts and case-insensitive collisions before writing. Do not move or rename media to obtain a supported layout.

Export known, supported fields: title/original title, description, tagline, release date, studio, genres, verified external identifiers, ratings with their source/scale, director/writer credits, and cast. Actor entries retain names, roles, order and valid portrait references. Never invent dates, ratings, online IDs or cast roles to fill gaps.

Collections, labels/tags, artwork variants and unsupported fields require explicit mapping. Plex's documented collection representation is not proof that every existing multi-collection relationship or custom field will round-trip. Preserve unmapped data in Curator and identify omissions; never label a partial export as a complete backup.

Series/episode support is a later bounded slice using `tvshow.nfo` and filename-matched episode sidecars, with validated show/season/episode identities. Do not serialize TV assets as movie records. Plex documents limitations for multipart media and NFO metadata for extras; detect these instead of guessing a working structure. Trailer files retain their separate supported naming/publication workflow.

## Preserve working cast and artwork

The existing cast/portrait behavior is the baseline. Reuse the metadata already present; do not introduce face recognition, portrait generation, a new people database or a replacement cast-publication mechanism for NFO export.

Plex documents actor portrait references as image URLs. Export an existing working reference only if it is appropriate for durable use and does not contain credentials or temporary access tokens. A currently displayed/cached portrait is not, by itself, proof that its reference can be re-imported from an NFO.

If a reference cannot be safely represented, identify that limitation in the plan and preserve the existing Plex/Curator portrait. Do not clear or replace it. The operator can export supported text fields with an explicit omission, or defer that item; resolving image-reference portability is separate from redesigning cast handling.

Reference existing approved artwork. If exporting artwork files is selected, show those additional destinations and retain originals. Distinguish exporting NFO text from copying artwork bytes. Do not assume a Curator-local path is accessible to Plex, expose private image hosting, embed credentials, create public links or trigger paid generation.

## Identity, preservation and compatibility

- Capture library, item/edition identity, mapping, metadata revision and existing file fingerprint/hash in the plan. Recheck before committing; changed or unavailable targets need a new preview.
- Preserve existing NFO identifiers. For media with no catalog ID, retain a stable Curator identity in export receipts; validate any proposed Plex custom-ID representation before relying on it. Never fabricate a TMDB/IMDb match or derive enduring identity only from a mutable title/path.
- Consistent NFO identifiers can support later rescans; switching an existing library to a different agent can still change identity. Export alone does not guarantee watch-history, rating-key or metadata preservation across an agent conversion. Existing issue #70 remains separate.
- Updating an NFO owned by another tool requires explicit conflict review and a retained original. Preserve unknown elements when safely editing an existing file, or require an explicit replacement choice; never silently discard them. Parse untrusted XML without external entities/network resolution.
- Stage writes on the destination filesystem, verify completed content, and use the existing no-overwrite/verified file-operation safeguards. Missing mounts, permission errors, competing writes and restart retain recoverable per-item receipts. No automatic replay after restart.
- Agent changes must not silently alter the intended standards. The current V2 standards model recognizes Other Videos through the legacy/none agent; an NFO-agent change needs a classification compatibility check and preservation of the selected profile/overrides. Record this as integration work, not an instruction to change the already working cast or library settings.
- Verify agent/scanner/server/client capabilities through actual configuration before standardizing recommendations. The operator's successful presentation change is evidence for that library, not universal import certification.

## Configuration and automation

Proposed settings: enable export for this library, create-missing versus reviewed-update policy, naming/layout preference, included supported fields, optional approved artwork export, retained-version limits and an optional later “update NFO after approved metadata changes” rule. Align any schema changes with the existing versioned standards model; do not silently add an enabled health requirement to every library.

A configuration preference is not permission to overwrite files or refresh Plex. First release is explicit selected/library export. Automatic maintenance requires separately enabled scope and the same conflict/recovery rules. Never purge old sidecars or backup versions merely because the export succeeds.

## Acceptance and delivery

1. Export synthetic metadata with Unicode/XML characters, sparse fields, multiple cast members, roles/order and existing portrait references; verify deterministic XML and supported tag mappings.
2. Prove supported metadata survives an NFO readback in a separately authorized disposable Plex library, including cast/portrait behavior on web and mobile. Report exact omissions; no claim of universal full-fidelity recovery.
3. Cover exact file association for movies, editions and shared folders; ambiguous/multipart/unsupported layouts are skipped or blocked visibly.
4. Cover create-missing, unchanged files, explicitly approved updates, third-party/unknown XML, case collisions, source/configuration changes, unavailable mounts, partial batches, cancellation and restart. Originals and working cast/artwork remain intact.
5. Prove selection, preview and NFO writing make no Plex mutations or agent changes; refresh requires separate approval and identity checks.
6. Confirm no credentials/private tokens appear in NFOs or logs, and unsafe XML cannot read files or contact external services.
7. Show actionable progress and per-item outcomes across themes/narrow layouts; histories identify initiator and verified disposition.

Delivery order: **movie/personal-media create-missing export → reviewed updates/recovery → optional artwork-reference packaging → validated TV support → opt-in maintenance**. This specification records planned functionality; no NFO generation, live-library export, agent migration or provider operation has been implemented by this document.

References: [Plex NFO format and limitations](https://support.plex.tv/articles/using-nfo-metadata-files-with-plex/), [local movie artwork](https://support.plex.tv/articles/200220677-local-media-assets-movies/), [V2 standards](curator-v2-standards.md), [V2 history](curator-v2-history.md), [preservation issue #70](https://github.com/kudama/curator/issues/70).
