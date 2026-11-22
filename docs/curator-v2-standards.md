# Curator v2 — library standards

Part of [Curator v2](curator-v2.md). The standards model, storage/API and reviewed editor are implemented. Scans, findings and processing do not consume these standards yet; enforcement and completion tracking remain #107. The editor does not approve or start work.

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

## Rules and permissions

Repeated cleanup choices may later be offered as explicit changes to a standard. A standard, or a preference Curator has inferred, never authorizes media changes, purchases or requests. Automation for new arrivals will need its own explicit permission per action.

## Storage and API

- A type standard is a `settings` record `standard:<kind>` (`record_type: library_standard`) with a `revision`. Until one is saved, the built-in default is used at revision 0.
- Library overrides are stored as `standard_overrides` and `standard_revision` on the library record. Reconnecting libraries preserves them.
- `GET /api/standards` returns every type (label, revision, `type_digest`, values, defaults, `customized`) and each library's effective standard, parent kind/revision/digest and overrides, from a coherent snapshot.
- `POST /api/standards {kind, revision, values}` replaces a type standard and requires the current revision.
- `POST /api/library/standard {library, revision, kind, type_revision, type_digest, overrides}` replaces a library's overrides and requires both its current revision and the reviewed inherited identity. Browser requests cannot omit that identity.
- Validation is strict. Unknown dimensions or fields, out-of-range thresholds, non-boolean switches and stale revisions are all refused with a message written for the user.

## Configuration screen (proposed, #105)

The proposed design is in [docs/designs/v2-standards-20261120](designs/v2-standards-20261120/README.md). The operator approved the desktop direction on 2026-11-21; #109 implements it. The UI uses the existing API, except for the library save contract below, which #109 must add:

| UI element | API field / behaviour |
| --- | --- |
| Type page header: revision, Customized / Curator defaults | `GET /api/standards` → `types[kind].revision`, `.customized` |
| Type page: libraries using it, overrides per field | `libraries[id].kind`, `libraries[id].overrides` |
| Dimension switch "Counts toward completion" | `values[dimension].enabled` |
| Metadata required fields / local AI suggestions | `metadata.required` (subset of `METADATA_FIELDS`) / `metadata.local_ai_suggestions` |
| Cast "done when" | `cast.mode`: `credits` / `known_people` |
| Artwork required / poster shape (fixed 2:3) | `artwork.required` (poster, background, logo) / `artwork.poster_ratio` |
| Upscaling resolution target / still suggest when met | `upscaling.target` (`1080`, `2160`) / `upscaling.suggest_when_met` |
| Re-encoding thresholds (empty = global) / Skip space-saving re-encoding suggestions | `encoding.max_mbps_1080`, `encoding.max_mbps_4k` (`null` = global config value) / `encoding.preserve_originals` (legacy name; suggestions only, never retention) |
| Reset form to Curator defaults | `types[kind].defaults`; form only, saved through review |
| Save type standard | `POST /api/standards {kind, revision, values}` (full standard) |
| Library page effective value | `libraries[id].values` (type values merged with overrides) |
| Inherited / Override tag; Use <Type> value | the field is absent from / present in `libraries[id].overrides[dimension]`; reset removes it |
| Save library overrides | `POST /api/library/standard {library, revision, kind, type_revision, type_digest, overrides}` (full override set plus the inherited snapshot that was reviewed; see below) |
| Overrides revision | `libraries[id].revision` (`standard_revision`) |
| No-op | the review finds no difference; no request is sent |
| Stale revision warning | API error "This standard changed in another window; reload before saving" (or the library variant) |
| Inherited standard changed during review | API error "The <Type> standard changed while you were reviewing; reload and review again"; overrides kept, nothing saved |
| Inline field errors | API validation messages, also checked in the browser before review |

### Reviewed library override saves (#109)

The library review shows effective values, which depend on the inherited type standard. The editor makes the reviewed inheritance part of the atomic save; checking only the library's revision would allow a concurrent type change to alter the meaning of reviewed values and resets:

- The request carries `kind` (the Plex type the library was reviewed as), `type_revision` (that type standard's revision shown in the review) and `type_digest` (SHA-256 of the canonical JSON of the type values the review was computed from). `GET /api/standards` returns the digest with each type and library so the client never computes it from its own copy.
- Inside the same store transaction as the override write, the server recomputes the library's current kind, the type's current revision and the digest of its current values. Any difference refuses the save with the "inherited standard changed" error. Overrides are normalized only against the type values that matched.
- The digest also catches built-in defaults that change in a Curator update while a type is still at revision 0, and a library whose Plex type changed (#92).
- A client-side re-fetch before saving is a convenience, not the guarantee. The atomic server check is.
- A type standard save does not need the library snapshots: its review lists the libraries it reaches for information, and the per-field override semantics are unchanged by a concurrent library save.

No-op type and library saves keep the revision and history unchanged. The browser sends no save for an unchanged form. Trusted internal Python callers may omit the new parent arguments for compatibility; the public override route always requires them. Missing or partial browser guards are refused.

The current entry is Settings → Library standards → Manage library standards. It preserves the unsaved Settings form underneath. `openStandardsEditor({kind, library})` is the entry for the Configuration navigation shell. See [synthetic implementation evidence](designs/v2-standards-editor-20261122/README.md).

## Schema versioning

State now carries a `schema_version` table. `curator/migrations.py` lists numbered migrations. Each one runs once, inside a transaction together with its version bump, so a failed migration leaves the previous version in place.

Before the first pending migration touches existing state, the database is copied to `<state>/backups/curator-schema-v<from>-<time>.sqlite3` (mode 0600). A state written by a newer Curator is refused rather than opened.

- Version 1 marks the pre-v2 layout.
- Version 2 records each library's `kind`.
- Version 3 structures history events.
- Version 4 changes saved poster standards/overrides to 2:3 and advances affected revisions. Existing images, styles and immutable job receipts are retained. Unsubmitted legacy landscape poster generation needs a fresh portrait plan; already submitted work can still be recovered.

The per-start repairs in `Service.__init__` are unchanged. They can move into numbered migrations as they are next touched.

## Next

1. Finish independent review and acceptance of the implemented type/override editor #109; navigation shell integration remains #108. The approved design is #105.
2. Scan evaluates the effective standard: findings and thresholds come from it. Add per-library completion and a migration that turns `profile` into overrides.
3. History: see [Curator v2 — history](curator-v2-history.md).
