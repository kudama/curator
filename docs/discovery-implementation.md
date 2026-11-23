# Local movie discovery (#113)

This implementation uses the conservative first-delivery source set from the revised
#112 contract: saved Plex movie metadata and explicit local feedback. It does not
connect an external ratings/trends/social provider, read household history, export
viewing history, make a request/purchase or change Plex. Home attaches the independent
`renderDiscoveryPanel(container, {library, limit, onOpen, onUpdated, api})` hook.
The embedding navigation owns `onOpen(pick)` and must preserve its existing draft guards.

## Facts and ranking

One pick represents one verified server/library/Plex movie item. Multipart media and
multiple editions under that item collapse to one pick; separate library copies remain
separate. TV episodes are never presented as series. Other Videos/home-profile libraries,
missing files and invalid/mismatched movie identities are excluded.

New picks require a known nonfuture arrival within 30 days. Picked-for-you also includes
older movies. Positive scanned `viewCount` excludes a movie. Missing viewing state is
labelled unavailable, never “unwatched.” Current token-account fields come only from
already scanned metadata; no play-history export or other account is queried.

A present `Rating` array takes precedence over scalar copies. One valid critic and
audience value is accepted, each on the Plex 0–10 scale; their equal mean is scaled by
10. Picked-for-you gains 10 once for genres shared with explicit More-like-this feedback.
The rank score is rounded half up once; it is not a claimed probability or provider
percentage. Unrated movies remain eligible after rated ones. Ties use arrival, title,
library and exact asset identity. Each explanation carries its actual saved observation
date; no provider refresh date is invented. Observations older than 24 hours, future or
missing dates and a known Plex outage are labelled stale/unavailable.

GET recomputes from local state without network or writes, satisfying the hourly
recomputation ceiling without retaining historical pick snapshots. The only scan change
is `includeGuids=1` on existing catalogue reads, so external identity is observed from
Plex without any external provider call.

## Feedback, identity and retention

More like this, Not for me, Hide and Clear write only a separate local settings record
and a Curator history event. Updates require the displayed feedback revision and, except
for clearing, a displayed movie identity token. A stale catalogue/rematch cannot apply a
vote to another movie. Preference settings have their own optimistic revision.

Feedback stays scoped to the exact original item/copy. On disappearance it can apply to
one current same-type, same-server movie with a matching typed external ID. Multiple
copies, wrong media types and reused Plex keys do not transfer feedback. Reattachment
is audited after a successful scan. Detached records default to 90 days, configurable
from 1–365 days. They stop affecting picks when expired and are purged by successful-scan
maintenance, even if a late rematch appears. No external source receives this data.
The preferences dialog lists retained/hidden/detached feedback and allows explicit Clear.

## API

- `GET /api/discovery?row=new|picked&library=all|<id>&limit=1..50`
- `GET /api/discovery/feedback` (local feedback list and current revision)
- `POST /api/discovery/feedback`: `{asset, feedback, revision, asset_version}`;
  `feedback` is `more`, `not_for_me`, `hide` or `clear`; `asset_version` is unnecessary
  when clearing an existing/detached vote.
- `GET /api/discovery/settings`
- `POST /api/discovery/settings`: `{revision, changes: {enabled, detached_days}}`

All APIs reuse session/Host/Origin/request-header checks. Browsing starts no scan,
processing queue, generation, request or Plex write. External and TV capabilities are
shown as unavailable, not represented by fabricated catalogue facts.

## Validation and acceptance

Synthetic tests cover rating precedence/rounding, missing signals, deterministic ranks,
feedback conflicts and stale identity tokens, multipart/copy scope, typed-ID collisions,
rematch ambiguity, reused Plex keys, expiry, source outage, settings and protected APIs.
Browser checks exercise desktop 1440px and true phone 390px in all three themes, exact
navigation identity, local feedback/Undo and preferences/off state without provider calls.
[Review renders](designs/v2-discovery-20261122/README.md) contain synthetic titles only.
This is engineering evidence, not operator visual acceptance or live-Plex acceptance.
Home integration is coordinated separately under #110. Plex rows are a separate #116
preview/publication feature; discovery itself cannot publish collections or rows.
