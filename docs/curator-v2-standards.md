# Curator v2 — library standards

Part of [Curator v2](curator-v2.md). This change adds the standards model, its storage and its API. Nothing reads a standard yet: scans, findings and processing behave exactly as before. The Configuration screen and completion tracking follow in later changes.

## One standard per Plex library type

Standards follow Plex's own library types, so a library's standard is decided by what Plex says it is:

| Curator kind | Plex library type | How Curator recognises it |
| --- | --- | --- |
| `movie` | Movies | section type `movie` |
| `show` | TV Shows | section type `show` |
| `other_videos` | Other Videos | section type `movie` with the "none" agent (`tv.plex.agents.none`, or legacy Personal Media `com.plexapp.agents.none`) |

Curator does not list Music or Photos libraries, so they have no standard.

`kind` is recorded on each library when libraries are connected or refreshed, and by the schema migration for existing state. Each library can **override** individual fields of its type's standard. Overrides store only the fields that differ, so a later change to the type standard still reaches every field the library did not override.

## Dimensions

| Dimension | Fields | Movies / TV Shows default | Other Videos default |
| --- | --- | --- | --- |
| Metadata | `required` fields; `local_ai_suggestions` | summary, year, genres; off | summary, originally available date; on |
| Cast | `mode`: `credits` or `known_people` | **off** (credits if turned on) | known people |
| Artwork | `required` (poster, background, logo); `poster_ratio` (2:3) | **off** (poster, 2:3 if turned on) | poster; 2:3 |
| Upscaling | `target` (1080 or 2160); `suggest_when_met` | 1080; on | 1080; on |
| Re-encoding | `max_mbps_1080`, `max_mbps_4k` (empty = global threshold); `preserve_originals` | global; off | global; on |

Every dimension also has `enabled`. A library is complete when it meets the standard for each enabled dimension. Completion does not require every possible transformation.

Cast and artwork are off for Movies and TV Shows. Plex's online agents supply credits, cast photos and artwork for those libraries, and Plex shows dynamic backgrounds, so Curator does not count them as unfinished. A library can turn either on through an override. Other Videos have no online source, so cast and artwork stay on for them.

Otherwise, the defaults record what is done today. Encoding thresholds default to the existing global settings. Optional upscale suggestions stay on. All posters use 2:3, including personal media and collections (operator decision, 2026-11-19). Backgrounds stay 16:9; square art stays 1:1; logos retain their proportions. Local AI suggestions remain an Other Videos default.

## Relationship to the existing home/commercial profile

Each library still has its `profile`, and today that profile drives home-media suggestions. This change does not alter it, with one exception: a newly connected Other Videos library now starts as `home`. Existing libraries keep the profile the operator chose. When the scan starts reading standards, `profile` will be replaced by the type standard plus overrides. A library whose profile disagrees with its type (for example a Movies library marked `home`) keeps its current behaviour: a migration will write a library override that matches its old profile (confirmed by the operator).

## Agent changes and the chosen standard type (proposed, #92)

**Problem.** Today `kind` is *inferred* from Plex and recomputed on every connect and location refresh (`rules.library_kind`: a `movie` section with a "none" agent is Other Videos). The inference breaks on agent changes:

- A personal-media library moved to the **Plex NFO Movie** agent, with the Plex Video Files scanner, becomes `movie`. It then silently switches to the Movies standard: cast and artwork stop counting, and local AI suggestions stop.
- Plex has announced it will remove legacy agents (including `com.plexapp.agents.none`) and offers **custom metadata providers** (agent chains such as Local Media → NFO → Plex Movie). Agent identity is therefore not a stable signal of intent.

Sources: [Plex: Using NFO metadata files](https://support.plex.tv/articles/using-nfo-metadata-files-with-plex/), [Plex: custom metadata providers](https://forums.plex.tv/t/announcement-custom-metadata-providers/934384). The exact NFO and custom-provider agent identifiers are **unverified**; forum examples show `tv.plex.agents.nfo.series`.

**Proposal: separate what Plex reports from what the operator chose.**

| Field | Meaning | Changes when |
| --- | --- | --- |
| `observed_kind` | What Plex reports now: `library_kind()` plus a scanner hint | Every connect or refresh (as `kind` does today) |
| `standard_kind` | The standard type the library follows | **Only** by an explicit operator change, or once at first connect |

1. **First connect.** `standard_kind` defaults to `observed_kind`. One addition: a `movie` section using the **Plex Video Files Scanner** is suggested as Other Videos, whatever its agent. Curator adds `scanner` to its read-only `/library/sections` read. An NFO library with the Plex Movie scanner stays Movies, so not every NFO movie library becomes personal media.
2. **Reconnect or refresh** updates `observed_kind` only. If it now differs from `standard_kind`, Configuration shows a notice ("Plex now reports this library as Movies. It still follows the Other Videos standard.") and Curator history records one event. Nothing changes automatically.
3. **Changing the standard type** is an explicit Configuration action. Its review shows the effective-standard difference field by field; overrides are kept and shown against the new type. It bumps `standard_revision` and records history, like any other standard save.
4. **The effective standard** uses `standard_kind`. Everything that today reads `kind` for standards reads `standard_kind`.
5. **Schema migration** (next number):
   - `standard_kind = other_videos` where `profile == home`; otherwise the current `kind`
   - `observed_kind` = the current `kind`
   - `profile` is unchanged
   - the usual pre-migration backup applies

   This keeps personal-media requirements for libraries the operator already marked as home media.

Out of scope: switching agents, recreating libraries, editing Plex's database, refreshing real media, and converting profiles beyond the migration above.

**Fixtures:**
- [`fixtures/plex-sections/sections.json`](fixtures/plex-sections/sections.json): synthetic section payloads (ordinary movie and TV, current and legacy none agents, NFO personal, NFO commercial, NFO series, custom provider).
- [`fixtures/plex-sections/expected.json`](fixtures/plex-sections/expected.json): today's and the proposed classification, reconnect cases and schema-upgrade cases.

The "today" column was checked against `rules.library_kind` at v2 `146d6ede`.

**Decisions for the operator:**
- **K1.** Confirm the scanner hint (Plex Video Files Scanner suggests Other Videos at first connect).
- **K2.** Allow a read-only `GET /library/sections` on the real server to confirm the NFO and custom agent identifiers and scanners before implementation.
- **K3.** Approve the migration rule above.

## Rules and permissions

Repeated cleanup choices may later be offered as explicit changes to a standard. A standard, or a preference Curator has inferred, never authorizes media changes, purchases or requests. Automation for new arrivals will need its own explicit permission per action.

## Storage and API

- A type standard is a `settings` record `standard:<kind>` (`record_type: library_standard`) with a `revision`. Until one is saved, the built-in default is used at revision 0.
- Library overrides are stored as `standard_overrides` and `standard_revision` on the library record. Reconnecting libraries preserves them.
- `GET /api/standards` returns every type (label, revision, values, defaults, `customized`) and each library's effective standard.
- `POST /api/standards {kind, revision, values}` replaces a type standard and requires the current revision.
- `POST /api/library/standard {library, revision, overrides}` replaces a library's overrides and requires the current revision.
- Validation is strict. Unknown dimensions or fields, out-of-range thresholds, non-boolean switches and stale revisions are all refused with a message written for the user.

## Schema versioning

State now carries a `schema_version` table. `curator/migrations.py` lists numbered migrations. Each one runs once, inside a transaction together with its version bump, so a failed migration leaves the previous version in place.

Before the first pending migration touches existing state, the database is copied to `<state>/backups/curator-schema-v<from>-<time>.sqlite3` (mode 0600). A state written by a newer Curator is refused rather than opened.

- Version 1 marks the pre-v2 layout.
- Version 2 records each library's `kind`.
- Version 3 structures history events.
- Version 4 changes saved poster standards/overrides to 2:3 and advances affected revisions. Existing images, styles and immutable job receipts are retained. Unsubmitted legacy landscape poster generation needs a fresh portrait plan; already submitted work can still be recovered.

The per-start repairs in `Service.__init__` are unchanged. They can move into numbered migrations as they are next touched.

## Next

1. Configuration screen for type standards and library overrides (prototype first).
2. Scan evaluates the effective standard: findings and thresholds come from it. Add per-library completion and a migration that turns `profile` into overrides.
3. History: see [Curator v2 — history](curator-v2-history.md).
