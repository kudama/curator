# Curator v2 — discovery contract (proposed)

Issue #112. **Status: proposed, revised 2026-11-22 for Codex review; awaiting operator decisions.** Implementation is #113 (in-library picks); #116 publishes Plex recommendation rows later. This contract adds no signup, subscription, paid call, credential or watch-history export.

## 1. Signal inventory

| Signal | Source | Access today | Notes |
| --- | --- | --- | --- |
| **Library recency** | Plex `addedAt` on library items | Curator's existing Plex token. `addedAt` is already in the raw Plex item the scan stores; nothing new is read for it. | The most reliable signal; already part of Home's "New in Plex" |
| **Critic and audience ratings** | Plex metadata: `rating`/`ratingImage`, `audienceRating`/`audienceRatingImage`, and the `Rating` array (`image`, `type`, `value`) supplied by the library's agent | Existing Plex reads | Plex already shows IMDb, Rotten Tomatoes and TMDB scores in its own UI. They are only as fresh as Plex's last metadata refresh. Exactly which entries a library returns varies by agent and settings, so #113 confirms the shape with one approved read-only check before relying on them. |
| **Your own viewing state** | Plex `viewCount`, `lastViewedAt`, `viewOffset` for the token's account | Existing Plex reads | Only the account Curator's token belongs to. Used only to skip watched items and surface half-finished ones. |
| Household viewing activity | Plex play history, or Tautulli | **Deferred** | Other people's viewing is private data. It needs D3 and separate access. |
| **Your feedback** | Curator: "More like this", "Not for me", "Hide" | New local records | Stays in Curator's local state. Never sent anywhere. |
| Popularity / trends | TMDB `trending` | **Deferred (D2).** Needs a free TMDB developer key: a signup, non-commercial terms and attribution ([terms](https://themoviedb.org:443/api-terms-of-use), [FAQ](https://developer.themoviedb.org/docs/faq)) | Useful for "worth watching", but a new account and terms |
| Streaming top lists | Netflix Top 10 pages; FlixPatrol (paid API); JustWatch (partner API) | **Deferred.** Paid or partner access, or terms not established. | The brief records that nothing was selected or bought. Nothing is assumed here. |
| Social popularity | — | **Deferred** | No authorized source has been identified |

## 2. Smallest useful first delivery (#113)

**Discovery uses only what Curator can already read, plus your own feedback.** No new provider, account or credential.

Sources: library recency, Plex critic and audience ratings, your viewing state, your feedback.

Two rows, both of **titles already in your Movies libraries** (Other Videos are excluded; TV is gated, below):

1. **New and worth watching.** Items added in the last 30 days that you have not watched, ranked by rating.
2. **Picked for you.** Unwatched or half-finished items, ranked by rating, nudged by your feedback (more like what you marked "More like this", by shared genre), with "Not for me" and hidden items removed.

**What #113 reads, and owns.** No Seerr credential or integration is needed. #113 owns one minimal read-only Plex change: add `includeGuids=1` to the existing movie-library read in `Plex.items` and store each item's external IDs, which identity and feedback (section 4) need. `addedAt`, ratings and view state are already in the raw item the scan stores. If #115 lands first with the same change, #113 reuses it; neither depends on the other, and the change is reviewed once wherever it lands.

**TV is gated (D4).** Curator's TV assets today are **episodes**: the scan reads show libraries with `type=4` and creates one asset per media file part. Recommending a series needs series-level records, which Curator does not have. The first slice therefore covers **Movies only**. TV joins only when D4 includes it **and** a read-only series index exists (`/library/sections/{key}/all?type=2&includeGuids=1`, episodes linked by `grandparentRatingKey`, the same index #114's contract defines for arrivals). A TV pick would then be a series, opening Library Manager filtered to that series' episodes. Recommending individual episodes is not proposed. The show-shaped fixtures are kept apart in `plex-series-gated.json` and are **not** acceptance for the first slice.

**Requestable titles** (things not in your library) are **not** in the first delivery. They need an external source (D2), and any request goes through Seer under #114's rules, which keep request creation out of Curator.

## 3. Ranking and explanations

Ranking is simple, deterministic and explained. There is no opaque model.

- **Which rating values:** if the item has a `Rating` array, use **only** its entries (`type: critic` and `type: audience`, at most one of each; Plex repeats some of them as the scalar `rating`/`audienceRating`, and those copies are ignored so nothing is counted twice). Otherwise use the scalars `rating` (critic) and `audienceRating` (audience). Any other entry types are ignored.
- **Score:** each value is on Plex's 0–10 scale and is multiplied by 10. The score is the mean of the critic and audience values present (weighted equally), plus any feedback bonus, then **rounded half up** to a whole number once, at the end (77.5 + 10 = 87.5 → 88). Items with no rating have no score and are ranked after rated ones, by recency; they still qualify for both rows.
- **Display:** the "why" line shows each value rounded half up ("Critics 82%").
- **Feedback:**
  - "More like this" adds 10 for items sharing a genre with a liked item
  - "Not for me" removes the item
  - "Hide" removes it from discovery but keeps it in the library
- **Ties** break by most recently added, then by title.
- **Days** in "Added N days ago" are elapsed time rounded up to whole days at the computation time.

Every pick carries a **"Why this"** line built from its signals, for example: "Added 3 days ago · Critics 82%, audience 70% · Not watched yet". Each signal shows its **source and when Curator observed it**: "Ratings observed from Plex, 2026-11-20". Plex does not report when an agent last refreshed ratings, so Curator never claims a refresh date.

## 4. Provenance, freshness and identity

- Each signal record keeps `source` (`plex.added`, `plex.rating`, `plex.view`, `curator.feedback`) and `observed_at` (when Curator read it). There is no rating-refresh date unless Plex actually provides one.
- **Freshness:** picks are recomputed after each library scan and at most hourly. Ratings are never fetched from anywhere other than Plex.
- **Identity:**
  - Picks reference Curator assets by `asset` id, and therefore by Plex `rating_key`. Curator's own renames keep the asset id across a Plex rematch (#70).
  - Feedback is stored against the asset **and** a typed identity: the media type (`movie`, later `show`) together with the item's external IDs (`tmdb://`, `tvdb://`, `imdb://` from the GUID read above). TMDB numbers are separate namespaces for movies and TV, so an ID is never compared across types.
  - **Scope:** feedback applies to the asset it was given on. Other copies of the same title (for example a 4K copy in another Movies library) are not affected.
  - **Reattachment:** if an asset disappears, its feedback is kept for 90 days. It is reattached only when **exactly one** current asset of the **same media type** carries one of its external IDs. With two or more candidates it is ambiguous and stays detached, and "Hide" or "Not for me" never transfers to unrelated media. Reattachment is recorded in Curator history.

## 5. API and UI contract (#113)

`GET /api/discovery?row=new|picked&library=<id>|all&limit=20` returns:

```json
{"row": "new", "generated_at": "2026-11-20T21:00:00Z", "stale": false,
 "items": [{"asset": "a1", "library": "lib-films", "title": "Sample Film 31", "kind": "in_library",
   "score": 76, "why": [{"signal": "added", "text": "Added 3 days ago", "source": "plex.added", "observed_at": "..."},
                         {"signal": "rating", "text": "Critics 82%, audience 70%", "source": "plex.rating", "observed_at": "..."},
                         {"signal": "unwatched", "text": "Not watched yet", "source": "plex.view", "observed_at": "..."}]}]}
```

`POST /api/discovery/feedback {asset, feedback: "more"|"not_for_me"|"hide"|"clear"}` records local feedback only. It is reversible, recorded in Curator history as yours, and changes nothing in Plex.

**UI** (Home's "Worth watching", see #104):
- Each pick opens the item in Library Manager.
- The "Why this" line is always visible.
- Feedback buttons sit on each pick.
- An empty row says why: "Nothing new in 30 days", "Nothing unwatched to pick from", "Discovery is off". Missing ratings never empty a row: unrated items still qualify and their "why" line says "No rating in Plex".

`kind` is `in_library` in the first delivery. `requestable` is reserved for a later, separately approved source. A requestable item would never be returned without its source, and would never carry a request action from Curator.

## 6. Fixtures

[`docs/fixtures/discovery/`](fixtures/discovery/) holds synthetic, offline examples:
- `plex-items.json`: Plex-shaped **movie** items with `addedAt`, ratings, view state and GUIDs, covering rated, unrated, watched, half-watched and Other Videos cases; an item with both scalar ratings and a `Rating` array (only the array counts); and two copies of one movie in different libraries
- `feedback.json`: local feedback records with typed identities, including series feedback whose TMDB number equals a movie's, and movie feedback whose item left while two copies exist
- `expected-new.json` and `expected-picked.json`: the rows #113 must produce, including the "why" text and ordering
- `expected-reattachment.json`: feedback reattachment outcomes (wrong type stays detached; two copies are ambiguous)
- `plex-series-gated.json`: series-shaped items for the gated TV slice; **not** first-slice acceptance

The fixture clock is 2026-11-20T21:00:00Z. Expected rows omit `library` and `observed_at`, which depend on when they are computed; #113 adds them. These are the acceptance fixtures for #113's tests. They contain no real titles and no network access.

## 7. Retention and privacy

- Feedback and pick snapshots stay in Curator's local state. They are not exported, published or sent to providers.
- Only your own account's viewing state is used, and Curator stores no viewing history. It reads current `viewCount`/`viewOffset` when computing picks.
- Pick snapshots are kept for 30 days. Feedback is kept until you clear it, or for 90 days after its item has left the library.

## 8. Decisions for the operator

- **D1** Approve the first delivery as Plex-only signals plus local feedback, with no external provider.
- **D2** Later external popularity: TMDB (free developer key, signup, non-commercial terms, attribution), something else, or none. Deferred until you decide; no signup happens without it.
- **D3** Household viewing activity (other Plex users, or Tautulli): defer (proposed), or allow with a scope you choose.
- **D4** Movies only first (proposed; required by the catalog today), or add TV once the series index exists.
- **D5** Retention periods in section 7.

## Out of scope

Requests, purchases, subscriptions, provider signups, paid APIs, social data, watch-history export, Plex recommendation-row publishing (#116), and any write to Plex.
