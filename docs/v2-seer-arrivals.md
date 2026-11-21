# Curator v2 — Seer arrivals contract (proposed)

Issue #114. **Status: proposed contract, awaiting operator decisions and senior security review.** Implementation is #115. This document defines a **read-only** integration that shows, on Home, Seer requests that have landed in Plex. It creates no accounts, stores no credentials, and grants no permission to request, approve or fulfil anything.

## 1. Which service and API

As of 2026, Overseerr and Jellyseerr have merged into **Seerr** (seerr-team). The Overseerr repository is frozen and Jellyseerr's repository became Seerr's. Sources: [Seerr](https://seerr.dev/), and the [merge discussion](https://github.com/seerr-team/seerr/discussions/2028).

The contract targets the **Seerr API v1** as described in its OpenAPI file, [`seerr-api.yml`](https://raw.githubusercontent.com/seerr-team/seerr/develop/seerr-api.yml) on `develop`, read 2026-11-20. The paths are relative to `{base}/api/v1`. A frozen Overseerr instance exposes the same v1 paths. It is supported only once its `/status` version is verified against the fixtures below.

**Not yet verified:** which instance the operator runs (Seerr or a legacy Overseerr/Jellyseerr), its version, and its URL. That is decision D1.

## 2. Authentication and read permission

What the spec shows:

- **Two schemes:** an `X-Api-Key` header, or a `connect.sid` session cookie obtained from `/auth/local`, `/auth/plex` or `/auth/jellyfin`.
- **One key:** the API key is the single **main settings** key (`MainSettings.apiKey`, regenerated through `POST /settings/main/regenerate`). The spec has no per-user keys, no scopes and no read-only key.
- **Seeing everyone's requests needs management rights:** `GET /request` "returns all requests if the user has the `ADMIN` or `MANAGE_REQUESTS` permissions. Otherwise, only the logged-in user's requests are returned." `MANAGE_REQUESTS` also allows approving and declining.

**Consequence: Seerr offers no credential that can only read all requests.** Read-only is therefore a property Curator must enforce itself, not one Seerr provides. Credential options for decision D2:

| Option | What Curator holds | Effect |
| --- | --- | --- |
| **A. Main API key** (proposed) | The admin `X-Api-Key` | Simplest; sees all requests. If leaked, the key controls Seerr. Curator enforces a GET-only allowlist (section 7) and treats the key as a secret, like the Plex token. |
| B. Dedicated Seerr user with `MANAGE_REQUESTS` | That user's password, used for a cookie session | Narrower than admin, but it can still approve and decline. Sessions need renewing, and Curator has to keep a password. |
| C. Dedicated user without management rights | Same as B | Sees only that user's own requests, so it is not useful for a household Home. |
| D. Seerr webhook into Curator (no Seerr credential) | Nothing for Seerr. Curator accepts an inbound POST. | The spec does not document the webhook payload (`jsonPayload` is an operator template), and inbound POST is a new attack surface for Curator. Needs its own security review. Not proposed. |

Whichever option is chosen, adding it needs the operator's decision and the senior controller's security review before #115 starts. This document grants nothing.

## 3. Endpoints Curator may call

Only these, only with `GET`:

| Call | Use |
| --- | --- |
| `GET /status` | Reachability and `version` (public, no credential). Used by the connection test and the compatibility check. |
| `GET /request?filter=all&sort=modified&sortDirection=desc&take=50&skip=N&mediaType=all` | Requests and their linked `media` (`MediaInfo`), paged by `pageInfo` |

Nothing else. In particular, Curator never calls `POST /request`, `/request/{id}/approve`, `/request/{id}/decline`, `DELETE`, any `/settings/...` path (including key regeneration and notification settings), or any `/auth/...` path apart from option B's sign-in.

## 4. Fields used

From each `MediaRequest`: `id`, `status`, `is4k`, `createdAt`, `updatedAt`, `requestedBy` (display name only, and only if D4 allows it), and `media`.

From `media` (`MediaInfo`): `id`, `tmdbId`, `tvdbId` (nullable), `status`, `updatedAt`. The request's `mediaType` filter tells movies and series apart.

The spec does **not** document `ratingKey`, `mediaAddedAt`, `status4k`, `imdbId` or seasons for these schemas, so Curator must not depend on them. If a running instance does return them, they may be used as *hints* only, never as the match.

**Enums** (verbatim from the spec):
- Request status: 1 pending approval, 2 approved, 3 declined.
- Media status: 1 unknown, 2 pending, 3 processing, 4 partially available, 5 available, 6 deleted.

## 5. States Curator shows

Three independent sources combine: the Seerr request status, the Seerr media status, and **Curator's own Plex catalog**.

| Curator state | Condition | Shown on Home |
| --- | --- | --- |
| Requested | request 1 | No (later: an optional "waiting" count) |
| On its way | request 2 and media 2 or 3 | No |
| Declined | request 3 | Never |
| Available in Seerr, not yet in Curator's catalog | media 4 or 5, but no Plex match in Curator's last scan | "Available, not yet scanned", with the last scan time |
| **Landed** | media 5 (movie) or 4/5 (series), **and** exactly one Plex match in a Movies or TV Shows library | **Yes**: "Requests that landed", linking to the item in Library Manager |
| Partly landed (series) | media 4, with one Plex match | Yes, labelled "Some episodes in Plex". Season detail only if the API verifiably provides it. |
| Ambiguous | media 4 or 5, more than one Plex match | Yes, as "In Plex (2 copies)", listing both. Never guessed. |
| Removed | media 6, or a previous match is gone from Plex | No; dropped from the landed list |

Seerr's own "available" alone never counts as landed. Curator's catalog is the authority for "present in Plex".

## 6. Matching rules

1. **Match only on stable external IDs:**
   - movies: `tmdbId` against the Plex item's `tmdb://` GUID
   - series: `tvdbId` against `tvdb://`, otherwise `tmdbId` against `tmdb://`
   - **Never** match on title or year.
2. **Plex IDs come from Curator's own scan.** Curator does not read Plex GUIDs today. #115 must add the read-only `includeGuids=1` to its existing Plex library reads, store each item's external IDs and `addedAt`, and change nothing else.
3. **Only Movies and TV Shows libraries are considered.** Other Videos, personal-media agents and items without external GUIDs are never matched.
4. **Requests for 4K** (`is4k`) are excluded until D3 decides how to treat them.
5. **Landing time** is Plex's `addedAt` for the matched item, and must be on or after the request's `createdAt`; an older item means the request was already satisfied and is shown as "Already in Plex". Home's "last 7 days" window uses the landing time.

## 7. Client rules for #115

- **GET-only allowlist.** The Seerr client accepts only `GET` to the two paths in section 3. Any other method or path raises **before** a network call. Tests prove this, including for redirects.
- **The credential is a secret:**
  - stored in Curator's configuration like the Plex token, never returned by `state()`
  - registered with `logs.register_secret` so logs and history redact it
  - never placed in URLs
  - history records "Seer key changed", never the value
- **Freshness:**
  - sync at most every 15 minutes, and when Home opens if the last sync is older than 5 minutes
  - page by `modified` descending, and stop once results are older than the display window
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
| Partial | some pages fail | Show what loaded, and say it may be incomplete |

Each transition is recorded once in Curator history as a connection event, like Plex failures and restores.

## 9. Settings #115 needs

- `seer_url` (http or https, LAN or loopback)
- the credential for option A or B
- `seer_enabled`

**Connection test:** `GET /status`, then `GET /request?take=1`. It reports the version, and whether all users' requests are visible.

Nothing else. No user sync, no quotas, no notification settings.

## 10. Fixtures (#115 tests)

Synthetic JSON shaped as in the spec:
- movie request: pending approval; approved and processing; available with exactly one Plex match (landed); available with no Plex match; available with two Plex matches (ambiguous); declined
- series request: partially available with a match; available with matches on `tvdbId` or only on `tmdbId`
- a 4K request
- deleted media (6)
- an item in Plex before the request was made ("Already in Plex")
- two pages of results
- responses: 401, 500, timeout
- malformed request with no `media`
- a `/status` with an unsupported version
- a redirect to a different host (must not be followed with the credential)

## 11. Decisions for the operator

- **D1** Which Seer instance (Seerr or legacy Overseerr/Jellyseerr), its version and its URL.
- **D2** Credential option A (proposed), B, or none yet. Senior security review is also required.
- **D3** Show 4K requests separately, merge them with HD, or exclude them (proposed: exclude for now).
- **D4** Whose requests appear on Home: everyone's (household), or only yours. Show the requester's display name or not (proposed: everyone's, no names).
- **D5** Whether Home should also show "On its way" (approved, not yet available) counts. Proposed: not now.

## Out of scope

Creating, approving, declining, retrying or deleting requests; changing Seerr settings or keys; webhooks; issue reporting; user import; downloads (Radarr/Sonarr); and any Plex write. Each would need its own issue, permission and approval.
