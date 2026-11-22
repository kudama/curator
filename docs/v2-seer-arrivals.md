# Curator v2 — Seer arrivals contract (proposed)

Issue #114. **Status: proposed contract, revised 2026-11-22 for Codex review (verified against Seerr source); awaiting operator decisions and senior security review.** Implementation is #115. This document defines a **read-only** integration that shows, on Home, Seer requests that have landed in Plex. It creates no accounts, stores no credentials, and grants no permission to request, approve or fulfil anything.

## 1. Which service and API

As of 2026, Overseerr and Jellyseerr have merged into **Seerr** (seerr-team). The Overseerr repository is frozen and Jellyseerr's repository became Seerr's. Sources: [Seerr](https://seerr.dev/), and the [merge discussion](https://github.com/seerr-team/seerr/discussions/2028).

The contract targets the **Seerr API v1** as described in its OpenAPI file, [`seerr-api.yml`](https://raw.githubusercontent.com/seerr-team/seerr/develop/seerr-api.yml) on `develop`, read 2026-11-20. The paths are relative to `{base}/api/v1`. A frozen Overseerr instance exposes the same v1 paths. It is supported only once its `/status` version is verified against the fixtures below.

**Not yet verified:** which instance the operator runs (Seerr or a legacy Overseerr/Jellyseerr), its version, and its URL. That is decision D1.

## 2. Authentication and read permission

Verified against Seerr source at commit [`77c977f`](https://github.com/seerr-team/seerr/blob/77c977fa0ca905831e1177bf7aa6f00a4a889e14) (2026-11-22), not only the OpenAPI summary:

- **Seeing everyone's requests needs `MANAGE_REQUESTS` *or* `REQUEST_VIEW`.** `GET /request` keeps every user's requests when the caller has either permission (`hasPermission([MANAGE_REQUESTS, REQUEST_VIEW], {type: 'or'})`) and otherwise limits the list to the caller's own requests ([request list](https://github.com/seerr-team/seerr/blob/77c977fa0ca905831e1177bf7aa6f00a4a889e14/server/routes/request.ts#L150)). `REQUEST_VIEW` (16384) is a separate permission from `MANAGE_REQUESTS` (16) ([permissions](https://github.com/seerr-team/seerr/blob/77c977fa0ca905831e1177bf7aa6f00a4a889e14/server/lib/permissions.ts#L16)). Approve, decline and retry still require `MANAGE_REQUESTS`. So a dedicated user with only `REQUEST_VIEW` can read every request and cannot change any.
- **The API key always acts as an administrator.** `X-Api-Key` is the single main-settings key. With it, a request acts as user 1 (the original administrator), or as *any* user named in an `X-API-User` header ([auth middleware](https://github.com/seerr-team/seerr/blob/77c977fa0ca905831e1177bf7aa6f00a4a889e14/server/middleware/auth.ts)). Holding the key is equivalent to holding admin, whichever user Curator chooses to act as.
- **A non-admin user signs in with a session.** `POST /auth/local` (or `/auth/plex`, `/auth/jellyfin`) returns a `connect.sid` session cookie. Sessions last 30 days by default.

The OpenAPI text says all requests need `ADMIN` or `MANAGE_REQUESTS`; the code is authoritative and also accepts `REQUEST_VIEW`. The operator's instance and version must still be checked against this (D1) before relying on it.

Credential options for decision D2:

| Option | What Curator holds | Effect |
| --- | --- | --- |
| **A. Dedicated view-only user** (proposed) | Email and password of a local Seerr user that has **only** `REQUEST_VIEW`, used to keep a session cookie | Least privilege: sees every request and cannot approve, decline, retry, delete or change settings. Curator must store a password, sign in, and renew the session before it expires. A leaked password exposes request visibility only. |
| B. Main API key | The admin `X-Api-Key` | Simplest; never expires. A leaked key controls Seerr. `X-API-User` could narrow Curator's own calls to a view-only user but not what the key itself can do, so it adds no protection and Curator does not send it. Curator would still enforce a GET-only allowlist. |
| C. Dedicated user with `MANAGE_REQUESTS` | That user's session | No advantage over A, and it can approve and decline. Not proposed. |
| D. Seerr webhook into Curator (no Seerr credential) | Nothing for Seerr. Curator accepts an inbound POST. | The webhook payload is an operator template, and inbound POST is a new attack surface for Curator. Needs its own security review. Not proposed. |

Whichever option is chosen, creating the Seerr user, setting its permissions and giving Curator the credential all need the operator's decision and the senior controller's security review before #115 starts. Nothing here creates, provisions or approves access.

## 3. Endpoints Curator may call

Only these, only with `GET`, plus option A's sign-in:

| Call | Use |
| --- | --- |
| `GET /status` | Reachability and `version` (public, no credential). Used by the connection test and the compatibility check. |
| `GET /request?filter=all&mediaType=movie&sort=added&sortDirection=desc&take=100&skip=N` | The **movie** request stream, paged by `pageInfo` |
| `GET /request?filter=all&mediaType=tv&sort=added&sortDirection=desc&take=100&skip=N` | The **TV** request stream, paged by `pageInfo` |
| `POST /auth/local` | Option A only: sign in as the view-only user. Curator sends the credential in the body, keeps only the session cookie in memory, and never calls any other `/auth` path except `GET /auth/me` to confirm the session's user and permissions |

Nothing else. In particular, Curator never calls `POST /request`, `/request/{id}/approve`, `/request/{id}/decline`, `/request/{id}/retry`, `DELETE`, any `/settings/...` path (including key regeneration and notification settings), and never sends `X-API-User`.

**Two typed streams, never `mediaType=all`.** TMDB numeric IDs are separate namespaces for movies and TV, so a bare `tmdbId` cannot say which it is. Curator fetches movies and TV separately and keeps the stream's type with every request. Each request's own `type` field (`movie` or `tv`, present on the request entity) and its `media.mediaType` must agree with the stream; any disagreement marks the response incompatible and nothing from it is matched.

**Page to completion; never stop by age.** Seerr's `sort=modified` orders by the *request's* `updatedAt`, but arrivals are defined by Plex's `addedAt` ([ordering](https://github.com/seerr-team/seerr/blob/77c977fa0ca905831e1177bf7aa6f00a4a889e14/server/routes/request.ts#L116)). An old approved request can land today, so stopping at an age cut-off would silently drop it. Each sync reads both streams to the end and replaces the previous snapshot atomically (household request lists are small). Offset paging is not atomic: a request deleted and another created during a sync can leave the totals unchanged while a row shifts across a page boundary and is skipped. Matching totals therefore prove nothing, and Curator does not claim a complete read from them. Instead, each stream is read **twice in a row** (`sort=added`, which orders by `createdAt` with `id` as a tie-break). Curator accepts the stream only when both passes return the **same ordered list of request ids** with no duplicates. If they differ, it retries both passes once. If they still differ, the stream is not consistent: Curator keeps the last complete snapshot and shows Partial. The read is still not a database snapshot; the second pass only shows the list was stable while Curator read it. Safety bound: at most 5,000 requests per stream; above that the sync stops, keeps the last complete snapshot, and shows the Partial state. A faster incremental sync needs a proven-safe strategy and its own review; none is proposed.

## 4. Fields used

From each `MediaRequest`: `id`, `type`, `status`, `is4k`, `createdAt`, `updatedAt`, `requestedBy` (display name only, and only if D4 allows it), and `media`.

From `media` (`MediaInfo`): `id`, `mediaType`, `tmdbId`, `tvdbId` (nullable), `status`, `updatedAt`. The stream's type, the request's `type` and `media.mediaType` must all agree (section 3).

**Status values**, verified in source ([`server/constants/media.ts`](https://github.com/seerr-team/seerr/blob/77c977fa0ca905831e1177bf7aa6f00a4a889e14/server/constants/media.ts)) rather than the OpenAPI summary:
- Request status: 1 PENDING, 2 APPROVED, 3 DECLINED, 4 FAILED, 5 COMPLETED.
- Media status: 1 UNKNOWN, 2 PENDING, 3 PROCESSING, 4 PARTIALLY_AVAILABLE, 5 AVAILABLE, 6 BLOCKLISTED, 7 DELETED.

**Seerr moves requests to COMPLETED itself** ([`MediaSubscriber`](https://github.com/seerr-team/seerr/blob/77c977fa0ca905831e1177bf7aa6f00a4a889e14/server/subscriber/MediaSubscriber.ts)):
- approved or failed movie requests become COMPLETED when their media becomes AVAILABLE or DELETED
- TV requests become COMPLETED once every requested season is available or deleted
- pending requests whose media becomes available (for example, through someone else's request) are marked COMPLETED without being approved

So a request that has landed is normally **COMPLETED (5)**, not APPROVED (2). COMPLETED means "Seerr considers this request fulfilled or no longer needed"; it says nothing about Curator's catalog, which is still checked.

Any other value, or a response missing these fields, makes the response incompatible (section 8).

## 5. States Curator shows

Three independent sources combine: the Seerr request status, the Seerr media status, and **Curator's own Plex catalog**.

| Curator state | Condition | Shown on Home |
| --- | --- | --- |
| Requested | request 1 (pending), whatever the media status | No (later: an optional "waiting" count) |
| On its way | request 2 (approved) and media 1, 2 or 3 | No |
| Request failed | request 4 | No (Seerr may later complete it; it is then treated as completed) |
| Declined | request 3, whatever the media status | Never, even if the title is in Plex |
| Available in Seerr, not yet in Curator's catalog | request 2 or 5, media 4 or 5, but no Plex match in Curator's last scan | "Available, not yet scanned", with the last scan time |
| **Landed** | request 2 or 5, media 5 (movie) or 4/5 (series), **and** exactly one Plex match in a Movies or TV Shows library | **Yes**: "Requests that landed", linking to the item in Library Manager |
| Partly landed (series) | request 2 or 5, media 4, with one Plex match | Yes, labelled "Some episodes in Plex". Season detail only if the API verifiably provides it. |
| Ambiguous | request 2 or 5, media 4 or 5, more than one Plex match | Yes, as "In Plex (2 copies)", listing both. Never guessed. |
| Removed | media 6 (blocklisted) or 7 (deleted), whatever the request status, or a previous match is gone from Plex | No; dropped from the landed list |

**Precedence:** media 6 or 7 is checked first and always means Removed. Otherwise the request status decides. Only an approved (2) or completed (5) request can become Available, Landed, Partly landed or Ambiguous. A request still pending (1), declined (3) or failed (4) never appears among landed requests, even when its media is available. When Seerr itself completes a pending request because the title became available, that completion is Seerr's decision that the request is fulfilled, and it counts like any other completed request. Seerr's own "available" alone never counts as landed. Curator's catalog is the authority for "present in Plex".

## 6. Matching rules

1. **Match only on typed, stable external IDs**, never on title or year:
   - movie stream: `tmdbId` against a **movie** item's `tmdb://` GUID in a Movies library
   - TV stream: `tvdbId` against a **series'** `tvdb://` GUID, otherwise `tmdbId` against the series' `tmdb://`, in a TV Shows library
   - A movie ID is never compared with a series ID, even when the numbers are equal.
2. **Plex IDs come from Curator's own scans.**
   - **Movies:** Curator's movie assets are Plex movie items. #115 adds the read-only `includeGuids=1` to the existing movie-library read and stores each item's external IDs and `addedAt`.
   - **TV:** Curator's TV assets are **episodes** (the scan reads `type=4`), and an episode's external IDs identify the episode, not the series. A series TMDB/TVDB ID is never matched against an episode. #115 adds one read-only **series index** per TV library, `GET /library/sections/{key}/all?type=2&includeGuids=1`, storing each series' `ratingKey`, external IDs and `addedAt`. Episodes link to their series by `grandparentRatingKey`. The landing time for a series is the latest `addedAt` among its episodes added on or after the request's `createdAt`, and "Some episodes in Plex" means at least one such episode exists.
   - **TV gate:** the series index and its episode link are standard Plex fields but have not yet been verified against the operator's server here. Until #115's fixtures and one approved read-only check confirm them, TV arrivals stay unavailable and Home says "TV requests are not matched yet." Movies do not wait for TV.
3. **Only Movies and TV Shows libraries are considered.** Other Videos, personal-media agents and items without external GUIDs are never matched.
4. **Requests for 4K** (`is4k`) are excluded until D3 decides how to treat them.
5. **Landing time** is Plex's `addedAt` (for TV, as in rule 2), and must be on or after the request's `createdAt`; an older item means the request was already satisfied and is shown as "Already in Plex". Home's "last 7 days" window uses the landing time, never the request's own timestamps.

## 7. Client rules for #115

- **GET-only allowlist.** The Seerr client accepts only `GET` to the paths in section 3, plus option A's single `POST /auth/local`. Any other method or path raises **before** a network call. Tests prove this, including for redirects.
- **The credential is a secret:**
  - stored in Curator's configuration like the Plex token, never returned by `state()`
  - option A: the password is used only for `POST /auth/local`; the session cookie is kept in memory, renewed before expiry, and re-obtained after a 401 at most once per sync; `GET /auth/me` must show the expected user with `REQUEST_VIEW` and **without** `ADMIN` or `MANAGE_REQUESTS`, otherwise Curator refuses to sync ("This Seer user has more access than Curator needs")
  - registered with `logs.register_secret` so logs and history redact it
  - never placed in URLs
  - history records "Seer key changed", never the value
- **Freshness:**
  - sync at most every 15 minutes, and when Home opens if the last sync is older than 5 minutes
  - read both typed streams to completion, twice, and swap in the new snapshot only when both streams' passes agree (section 3)
  - record the last successful sync time and show it ("Updated 14:02")
- **Failure:** keep the last good result and mark it stale. After 24 hours of failure, hide the counts and show "Seer not reachable since …".
- **No writes anywhere:** no Seerr writes, Plex writes or job creation. Matching only changes what Home displays.

## 8. Unavailable states

| State | Trigger | Home text |
| --- | --- | --- |
| Not configured | no URL or credential | "Seer is not connected." with a link to Configuration → Connections |
| Unreachable | timeout, DNS or connection error, 5xx | "Seer could not be reached; showing the update from …" (stale rules apply) |
| Not authorized | 401 or 403 | "Seer refused Curator's credential. Check the key in Configuration." No retry loop. |
| Incompatible | `/status` version below the verified minimum, or a response missing required fields | "This Seer version is not supported yet." Nothing is matched. |
| Partial | a page fails, the two passes disagree (section 3), or a stream exceeds 5,000 requests | Keep showing the **last complete snapshot** with its time and "Some requests could not be read just now". A truncated or unverified fresh read is never shown as complete or mixed into the snapshot. With no complete snapshot yet, show only the message. |

Each transition is recorded once in Curator history as a connection event, like Plex failures and restores.

## 9. Settings #115 needs

- `seer_url` (http or https, LAN or loopback)
- the credential for option A or B
- `seer_enabled`

**Connection test:** `GET /status`; for option A, sign in and check `GET /auth/me` permissions as above; then `GET /request?mediaType=movie&take=1` and `?mediaType=tv&take=1`. It reports the version, the signed-in user's permissions, and whether all users' requests are visible.

Nothing else. No user sync, no quotas, no notification settings.

## 10. Fixtures (#115 tests)

Synthetic JSON shaped as in the spec:
- movie request: pending approval; approved and processing; available with exactly one Plex match (landed); available with no Plex match; available with two Plex matches (ambiguous); declined
- series request: partially available with a match; available with matches on `tvdbId` or only on `tmdbId`
- a 4K request
- deleted media (6)
- an item in Plex before the request was made ("Already in Plex")
- two pages of results
- **typed namespaces:** a movie request and a TV request with the **same numeric `tmdbId`**, a Plex movie and a Plex series that share that number; each request lands only on its own type
- a response whose request `type` or `media.mediaType` disagrees with its stream (incompatible, nothing matched)
- **request precedence:** a pending, a declined and a failed request whose media is available and in Plex; none appears as landed
- **completed requests:** a COMPLETED movie request with AVAILABLE media and one Plex match (Landed, the normal case); a request Seerr completed from pending; a COMPLETED request with DELETED (7) or BLOCKLISTED (6) media (Removed); an unknown status value (incompatible)
- **unstable paging:** pass one and pass two differ (a deletion plus an insertion with equal totals); the stream is retried, then Partial keeps the previous complete snapshot
- **old request, new arrival:** a request created and last modified months ago whose movie was added to Plex today; it appears in "last 7 days" and is not cut off by paging
- **TV unit:** a series request matched through the series index, with episodes linked by `grandparentRatingKey`; an episode whose own GUID equals the series' TMDB number is **not** matched; season-only additions after the request
- option A: `/auth/me` showing `MANAGE_REQUESTS` or `ADMIN` (refused), session expiry and one re-sign-in
- responses: 401, 500, timeout
- malformed request with no `media`
- a `/status` with an unsupported version
- a redirect to a different host (must not be followed with the credential)

## 11. Decisions for the operator

- **D1** Which Seer instance (Seerr or legacy Overseerr/Jellyseerr), its version and its URL.
- **D2** Credential option A (dedicated `REQUEST_VIEW`-only user, proposed), B (main API key), or none yet. Creating that user is the operator's action, not Curator's. Senior security review is also required.
- **D3** Show 4K requests separately, merge them with HD, or exclude them (proposed: exclude for now).
- **D4** Whose requests appear on Home: everyone's (household), or only yours. Show the requester's display name or not (proposed: everyone's, no names).
- **D5** Whether Home should also show "On its way" (approved, not yet available) counts. Proposed: not now.

## Out of scope

Creating, approving, declining, retrying or deleting requests; changing Seerr settings or keys; webhooks; issue reporting; user import; downloads (Radarr/Sonarr); and any Plex write. Each would need its own issue, permission and approval.
