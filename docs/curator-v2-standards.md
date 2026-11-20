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
| Cast | `mode`: `credits` or `known_people` | credits | known people |
| Artwork | `required` (poster, background, logo); `poster_ratio` (2:3 or 16:9) | poster and background; 2:3 | poster; 16:9 |
| Upscaling | `target` (1080 or 2160); `suggest_when_met` | 1080; on | 1080; on |
| Re-encoding | `max_mbps_1080`, `max_mbps_4k` (empty = global threshold); `preserve_originals` | global; off | global; on |

Every dimension also has `enabled`. A library is complete when it meets the standard for each enabled dimension. Completion does not require every possible transformation.

The defaults record what is done today. Encoding thresholds default to the existing global settings. Optional upscale suggestions stay on. The home-media choices (16:9 posters and local AI suggestions) are the Other Videos defaults.

## Relationship to the existing home/commercial profile

Each library still has its `profile`, and today that profile drives artwork shape and home-media suggestions. This change does not alter it, with one exception: a newly connected Other Videos library now starts as `home`. Existing libraries keep the profile the operator chose. When the scan starts reading standards, `profile` will be replaced by the type standard plus overrides. A library whose profile disagrees with its type (for example a Movies library marked `home`) will then keep its current behaviour through a library override written by a migration.

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

The per-start repairs in `Service.__init__` are unchanged. They can move into numbered migrations as they are next touched.

## Next

1. Configuration screen for type standards and library overrides (prototype first).
2. Scan evaluates the effective standard: findings and thresholds come from it. Add per-library completion and a migration that turns `profile` into overrides.
3. History: extend the existing per-library History screen into Job history and Curator history (see the v2 brief).
