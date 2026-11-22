# Home summary implementation

Implementation for #110, following the approved #104 Home direction. All names,
counts and images in these [desktop](desktop.png) and [phone](phone.png) captures
are synthetic. These are the real Home component and authenticated read-only API,
mounted in a synthetic application fixture. Full navigation-shell integration is
#108/#162 and must be verified on the combined tree, not inferred from these renders.

## Contract

`GET /api/home?library=all|<id>&view=full|compact&limit=1..30` reads a coherent local
snapshot. It never contacts a provider/Plex, starts a scan, creates work or changes
settings. The compact projection is the existing server-side Homebase collector's
boundary (#119); it contains no catalogue titles, library names, paths, settings,
source IDs or credentials. Existing session and origin protections are unchanged.

Both views return schema_version 1, generated_at, observed_at (nullable ISO time),
stale, scope, counts, work, health and local hash links. Counts include running,
waiting, publishing, combined ready/attention and missing required fields. Combined
Ready and Attention link to Home's separate destinations, not a video-only inbox
or a queue that cannot show every kind of outcome.

The full view adds separate result/metadata/per-library artwork decisions, exact
attention destinations, recent unique Plex items, per-library/dimension health and
integration availability. Ratings/requests are not fabricated when modules or
connections are unavailable. Discovery and Seerr render through their independent
read-only hooks after integration. Refresh failures keep dated last-good content.

Health uses effective standards (#107). Optional work and disabled dimensions do
not reduce completion. Missing/unknown dimensions link to actual Library Manager
filters; future/unavailable observations are unknown and never presented as fresh.
Empty/unassessed libraries never get a made-up 100% score. Counts describe files;
arrivals deduplicate media parts by library and Plex item, without merging copies
from different libraries.

## Work observations

Successful task transitions and independent file-operation completions write an
outcome event atomically with their state change. Later task requeues cannot erase
or redate these observations. Publication/file-task bookkeeping wrappers never
count as a second completed job. Unknown original initiators stay unknown.

Earlier completion dates are not inferred from mutable legacy records. A coverage
marker describes when durable observation began; the UI names partial history
coverage. Queries cover seven days and at most 5,000 outcome rows; truncation is
explicit. Video byte reduction uses recorded verified source/output sizes. Retained
originals mean this is not a claim of reclaimed disk space. Unknown sizes remain
unknown. Cleanup and partial-export receipts remain visible as decisions even when
their enclosing file job finished.

## Verification

- 14 focused backend tests: scoped identity, all review routes, required/disabled
  dimensions, read-only transactions, compact privacy, durable outcome dedup,
  cleanup/partial-export attention, future dates and unknown/stale observations.
- Independent backend review found three issues at 1c3afcd; corrections and
  independent reproductions passed at 9ac09b2. Full UI/Claude review is separate.
- 12 real Chromium checks on the component: API-backed sections and links,
  actual dimension matching, no mutations, failed-refresh retention and keyboard.
- Six Classic/Cyberpunk/Plex layouts at 1440/390 px: no horizontal page/link
  overflow. Existing Settings and inspectors are not modified by Home.
- Current full Python/JS/style evidence is recorded on the PR; this document is
  not deployment, real-client, provider or full v2 acceptance (#120).
