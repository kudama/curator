# Seerr arrivals: offline implementation and connection gates

Task #115, proposed contract #114 / PR #130. Implemented 2026-11-22 as a
**supported, unconfigured** integration. No instance, supported deployed version,
account or credential has been selected. Connections fields remain disabled;
there is no HTTP action that enables, signs in or syncs a live connection.
Opening Configuration or the arrivals read-model route performs no provider call.
Imported enable flags cannot activate it. The ordinary config API accepts none
of these credentials. This is not completion or acceptance of live #115.

The isolated client is functional under injected synthetic transports. A real
transport exists only as a separately reviewed future capability; the service’s
offline fixture seam rejects it. Session cookies remain in memory. Credentials
are neither persisted nor returned by state or history. An optional single local
sign-in operation requires an explicit separate capability, off by default;
there is no admin API-key path. Every sync checks the exact expected user and
only REQUEST_VIEW (16384), refusing management/admin/other permissions. Only one
actual 401 can trigger re-sign-in with explicitly supplied ephemeral credentials;
403 or an overprivileged user cannot start a retry loop.

The client allows exact GET status/auth-me/typed request paths and bounded query
shapes. Everything else fails before the transport, including request creation,
approve/decline/retry/delete, settings, arbitrary query/path changes and redirects.
A version must match a separately supplied verified allowlist; the application
currently supplies none. It never silently accepts legacy instance compatibility.

Pagination reads at most 5,000 items per typed stream, twice, retaining ordering
and normalized request IDs/states. Two identical bounded passes are an observed
consistency check, **not a transactional provider snapshot**. Unchanged total
counts alone are insufficient; changed ID sets, duplicate IDs, ordering changes,
missing pages or mismatched passes become Partial. Only a successfully completed
pair can replace the last complete snapshot. Partial/outages retain old data and
its original success timestamp, without exposing a truncated fresh result.
Cached views identify stale data; after 24 hours counts and rows are hidden.

Matching requires approved request status 2 before considering media availability.
Pending/declined/failed/completed-request states never leak into Landed merely
because a shared media object is available. IDs are typed TMDB movie versus TV
series identifiers; no title/year fallback. Movie matches are unique Plex
movie-item identities, with duplicates explicit. Landing time comes from Plex
addedAt, so old requests can appear for new arrivals; older Plex items are Already
in Plex. Chosen standard/legacy kinds and both current/legacy none agents exclude
Other Videos and home-movie/personal-media libraries even when the profile says
commercial. Raw movie/series/episode namespaces remain distinct. Cached item
rating keys must match their current catalog row, and missing/deleted/unobserved
rows never become arrivals. 4K remains excluded.

TV remains unavailable by default. The synthetic matcher can verify a separate
series index and grandparentRatingKey episode relationships, but never compares
a series ID with an episode GUID. The real read-only Plex series/GUID collection
and client acceptance are still gated, along with live movie includeGuids reads.
The Home renderer hook and read-model route are ready for the separately reviewed
Home implementation; no alternative navigation has been invented.

Upstream enums were checked against Seerr commit
[77c977f](https://github.com/seerr-team/seerr/blob/77c977fa0ca905831e1177bf7aa6f00a4a889e14/server/constants/media.ts):
media **6 is BLOCKLISTED; 7 is DELETED**. Request states additionally include
FAILED=4 and COMPLETED=5; these stay excluded until their exact supported semantics
are accepted. This corrects the older proposed contract’s “6 deleted” wording.
Request list ordering/REQUEST_VIEW and permission values were verified against
[request.ts](https://github.com/seerr-team/seerr/blob/77c977fa0ca905831e1177bf7aa6f00a4a889e14/server/routes/request.ts)
and [permissions.ts](https://github.com/seerr-team/seerr/blob/77c977fa0ca905831e1177bf7aa6f00a4a889e14/server/lib/permissions.ts).

Remaining live gates: corrected/accepted contract, chosen direct instance/version,
least-privilege account/security review, whose requests appear, 4K policy, verified
Plex GUID/series reads, reviewed Home integration, and separately authorized
read-only acceptance. No accounts/grants, paid providers, job dispatch, media/Plex
writes, or live Seerr calls were performed. Installation does not enable anything.
