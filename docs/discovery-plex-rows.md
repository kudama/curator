# Reviewed Curator rows in Plex (#116)

Implemented 2026-11-22 as a dependent slice of local discovery #113. Independent
review and operator/Plex-client acceptance remain separate from implementation.

Settings → Discovery → **Curator rows in Plex** opens local state only. Choose a
Movies library, New and worth watching or Picked by Curator, a collection title,
1–20 movies and the exact Library recommended / own Home / shared Home visibility.
All destinations are off by default. **Preview exact changes** performs read-only
Plex capability and identity checks, then shows the before/after membership and
visibility. **Approve and publish** is a separate explicit action. Editing options
invalidates approval immediately. Controls and dismissal are locked during requests.

This slice supports verified Movies only. TV needs series indexing; home-movie
libraries are excluded using the effective standard kind. No collection is adopted
by title. A new name collision blocks publication. Once created, its server,
section and collection ID plus last verified exact membership define ownership.
Externally modified membership/visibility blocks overwriting; resolve it in Plex
before a fresh preview. Collection renaming/deletion and Plex's row ranking/order
are outside this flow. Disabling every destination preserves the collection and
its membership. Nothing auto-refreshes or publishes from browsing, feedback or scans.

## Protocol and recovery

Protected endpoints:

- `GET /api/discovery/rows?library=ID`: local ownership and recent receipts only.
- `POST /api/discovery/rows/preview`: exact library, row, title, visibility, limit,
  ownership revision. Read-only Plex checks; local immutable plan saved.
- `POST /api/discovery/rows/apply`: plan ID, exact review token, `approved: true`.
- `POST /api/discovery/rows/inspect`: receipt's plan ID, optional explicit
  `accept_current: true` acknowledgement of freshly inspected state locally.

Apply serializes per library, checks ownership/feedback/settings revisions and
asset snapshots, freshly verifies movie type/section and matching typed GUIDs,
then compares exact current collection membership/visibility to the reviewed
before-state. Verified duplicate apply returns its existing receipt without writes.
A durable applying receipt precedes each external operation; creation ID is
checkpointed before membership readback. Only the existing collection adapter and
managed collection hub endpoints are used; no provider, source-media, image or Plex
metadata-field writes occur.

Unknown/failed external outcomes stop at `needs_inspection`, including after a
process restart. They never auto-retry or auto-roll back. Inspect reads exact known
IDs; explicit acknowledgement records the observed partial state locally, preserving
all Plex data. If creation returned no ID, a matching title is **never** adopted.
Resolve it manually in Plex. A complete catalogue read showing the title absent can
then be explicitly acknowledged locally, permitting a fresh preview. No collection
or unrelated hub is deleted, moved or reordered.

Capabilities require actual matching server identity, Plex Pass, known writable
library state and a complete parseable managed-hub response with all three flags.
Unknown/missing fields fail closed; version strings are not used as proof. These
checks do not prove a particular Plex client's Home display: that remains an
operator acceptance check, with no live writes performed during development.

Primary protocol references, checked 2026-11-22:

- [Plex: publishing collections](https://support.plex.tv/articles/publishing-collections/)
- [PlexAPI ManagedHub source](https://python-plexapi.readthedocs.io/en/stable/_modules/plexapi/library.html)
- [PlexAPI collection source](https://python-plexapi.readthedocs.io/en/stable/_modules/plexapi/collection.html)
- [PlexAPI server capability fields](https://python-plexapi.readthedocs.io/en/stable/_modules/plexapi/server.html)

## Synthetic evidence

Ten backend fixtures use the real existing Plex collection adapter with an in-memory
request transport. They cover exact creation/update/hide, no unrelated row/order
changes, no-preview writes, GUID/capability/revision/title guards, duplicate apply,
partial failure inspection, unknown create ID and restart recovery. Two JS tests
cover explicit preview/approval, immediate input invalidation and pending locks.
Real browser checks cover desktop1440/phone390 in Classic, Cyberpunk and Plex themes,
zero horizontal dialog overflow, local-only initial read, explicit preview, dirty
invalidation and one approved fake-Plex publication with refreshed receipt. Six
synthetic screenshots are in `docs/designs/v2-discovery-rows-20261122/`.

Forge controller supplied bounded failure-case suggestions; identity/revision,
unknown-outcome and unrelated-row cases were checked against implementation.
Its suggestions are supporting analysis, not independent approval.
