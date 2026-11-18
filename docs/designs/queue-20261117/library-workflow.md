# Library task workflows — approved direction, 2026-11-17

**Latest governing scope:** [Consolidated feature lock](feature-lock.md), including later clarifications. It supersedes conflicting earlier wording below.
Status: approved for ticketing. **No coding, worker dispatch, merge or rollout until Mike explicitly authorizes execution.** This is a documentation-only supplement to the [queue design](README.md), tracked by Curator #54.

## Render references and approval scope

- [Grouped library and bulk metadata](library-bulk-metadata.png).
- [Metadata with Cast and Artwork handoff](library-metadata-cast.png): latest form direction.

Text requirements govern generated mockup details. Checked example fields/cast show an example choice, not initial defaults. Synthetic filenames, counts, missing-field hints, names, roles and build labels are illustrative. These renders approve the grouped-library and bulk-metadata direction; they do not approve unseen dedicated File management or portrait-editing screens. Show any remaining screen or substantive deviation before implementation. Planning approval does not release the execution hold.

## Library selection and entry

Separate Metadata from Artwork tasks. Clicking a task in its group opens its relevant editor directly; no intermediate file overview and second Review click. Selection checkboxes stay independent. Do not auto-select unrelated work or lose existing approvals/history. Missing description and missing artwork are distinct findings; repeated scans must not duplicate work.

Select all in Metadata must lead to **Edit selected metadata → Preview changes → Approve and queue** in that view, including selection across folders. Do not point to an absent Edit folder action. Apply only explicitly chosen fields, keep untouched fields/values, show exact affected files and before/after changes, and retain eligibility/version and partial-failure handling. Generic field labels do not justify applying one title/description or cast to every file by default.

## Categories and Collections

- Use the name **Categories**, preserving Plex's existing genre mapping. Collections remain a separate field.
- Both pickers support search, multiple selections and an explicit `Create “name”` choice for a nonmatching name. New entries are clearly represented in the draft/preview, with removal/cancel and duplicate normalization behavior.
- Typing or selecting Create edits the local draft only. New values become Plex data only through an explicitly approved queued job when it executes. Do not send an upstream creation/write during typing, search, dropdown selection or preview.
- Bulk list operations state add/replace/clear semantics before approval; do not silently erase per-file entries or duplicate existing names. Validate empty/whitespace/duplicate inputs consistently with current APIs.
- Remove Labels from ordinary editor controls without clearing stored Plex labels, label-driven smart collections, saved defaults or existing approved plans. No taxonomy/data migration or new provider required.

## Cast ownership and image ownership

- **Metadata owns names, roles and cast order**. Support selecting existing people, adding a person, changing roles, reordering and removing draft credits using existing identity/credit mechanisms.
- Bulk Cast is **unchecked by default** and requires an explicit `Apply this cast to all N files` choice. Show that the same names/roles/order will apply and preview the consequence for each selected file. Leaving it unchecked preserves each file's cast. Specify add/replace/clear behavior; never interpret an untouched empty editor as a clear operation.
- **Artwork owns cast portraits**, cover and background images. Metadata has a `Manage portraits` link with an explanation that it opens Artwork for those people. Do not embed portrait-upload controls in Metadata or mix portrait writes into metadata queueing.
- The handoff preserves selected file/person identities and unsaved edits. Opening Artwork, returning, or canceling must not silently save/discard metadata or queue provider/media actions. Preview and explicitly approve any shared portrait scope rather than accidentally updating unrelated people/files.
- Preserve existing portrait/provider identity, consent, cost and publication safety. Missing portraits must not automatically trigger generation or paid requests. The actual portrait workspace still needs a render before implementation.

## Navigation and presentation

File management is a dedicated navigation entry near Queue; remove File tools from metadata forms. Reuse supported file operations with explicit review rather than add operations implicitly. The dedicated File management screen still needs a render.

Use the established pink/plum temporary editor, readable body text, clear multi-file scope and a visible footer. No bottom-right popup overlays: scoped inline feedback, persistent errors and reliable Undo follow Forge #90. Categories/Collections support new-value creation through their dropdowns; this behavior is required even though the static renders show closed pickers.

## Future validation and source handoff

Before execution re-read live source, tickets and grants; use exact-source bounded handoffs. Test synthetic missing-metadata/image/both, repeated scans, old queued/history plans, filtered/large/multi-folder selection, direct editor routing, create-existing/new picker values with zero upstream calls before approved execution, stale previews/partial failures, label preservation, cast opt-in/ordering/identities and unsaved handoff round trips. Verify both themes, keyboard/narrow layouts, inline errors and final visual match. Prior exploratory PR #52 checks are not acceptance of this design.
