# Proposed preview contract, version 1

Task #138; implementation #140–#144. **Design only: these APIs/records do not exist yet.** Use existing storage, queue, authorization and transaction conventions. Python standard library and plain JS; no new service or runtime dependency. Keep private paths/tokens out of client payloads, public evidence and provider prompts.

## 1. Reusable card library

Import/validate completed PNG images first; optional JPEG support must be declared by the import capability. Reuse existing image upload/decode limits and show their concrete values in #140's UI. File extension alone is not validation. Store a private managed copy and record:

```json
{
  "id": "synthetic-intro",
  "revision": 1,
  "role": "intro",
  "name": "Family archive",
  "image": {"version": 1, "sha256": "server-computed", "width": 1920, "height": 1080, "format": "png", "alpha": false},
  "thumbnail_url": "/api/preview/cards/image?id=synthetic-intro&version=1"
}
```

IDs are stable; image versions are immutable. Replacing a card requires its current revision and creates a new version. Existing jobs and selected previews keep the referenced old bytes. Removing a card hides it from future choices; referenced versions are retained until an explicit safe cleanup. No automatic deletion/PSD import or image-provider call. Validate image hashes at plan/execute time; an unavailable selected version is an error, not a silent fallback.

Store cards under Curator's existing private state directory with owner-only permissions. The configured generated-art archive and Plex movie folder are not repurposed as mutable card storage. The operator's PSD masters remain outside the runtime library.

## 2. Defaults versus per-job overrides

A separate versioned `preview_defaults` settings record contains optional intro/outro selection, card durations, transition/audio values, output profile and default interval suggestion. These are preview settings, not an implicit addition to metadata/completion standards. Coordinate its Configuration hook with #109. A defaults save requires the current revision, explicit review, and a transactional history event. No-op saves do nothing. Keep edits on revision conflict.

A source draft shows defaults plus only its explicit overrides. A defaults change does not rewrite that draft, submitted job, candidate or selected preview. Reset intentionally reloads current defaults. Each plan freezes the resolved values and defaults revision; stale plan inputs need a new plan/review. No new per-library defaults hierarchy is assumed in this first contract.

## 3. Plan and timing

All UI/API durations use integer milliseconds. The server validates and normalizes them to the frozen output frame/audio profile, then returns the effective values/duration for review. Do not send raw FFmpeg filter strings or trust client-supplied paths/hashes.

Proposed request fields:

```json
{
  "asset": "synthetic-asset",
  "asset_version": "server-snapshot-token",
  "range": {"start_ms": 60000, "end_ms": 90000},
  "intro": {"card": "synthetic-intro", "version": 1, "duration_ms": 3000},
  "outro": {"card": "synthetic-outro", "version": 1, "duration_ms": 3000},
  "transitions": {"crossfade_ms": 500, "black_fade_ms": 350, "audio_fade_ms": 500},
  "output_profile": "preview-h264-720",
  "audio_track": "verified-source-track",
  "defaults_revision": 1
}
```

`intro`/`outro` may independently be `null`. Resolve one exact asset/library/edition/file/part on the server, using the existing mapped source and source reservations. Capture its fingerprint in the plan; the renderer hashes and verifies the source around execution, as with existing processing receipts. Reject changed mappings/identity rather than adopting another source. Use a plan ID/token covering the entire server snapshot, card identities/hashes, effective interval/settings and versions.

Let `C = end − start`, `I/O = enabled card durations`, `X1/X2 = crossfade duration at an enabled intro/outro boundary` (zero when that card is absent). Then:

**Total = I + C + O − X1 − X2.**

Outer black fades do not shorten the output. Audio fades are within the chosen clip. The chosen interval is used in full; crossfades blend its edge frames with cards, rather than claiming every frame remains unobscured. An optional scene-boundary helper is bounded, displays actual adjusted times and requires review; manual selection always works.

Validation before Generate:

- Finite, nonnegative integer values; source interval must be within a verified source duration and `C > 0`.
- Proposed UI limits: enabled card duration greater than zero and at most 10 seconds; each transition/fade 0–2 seconds. These bounds are proposed until approved.
- Let the source's first transition be `X1` when intro exists, otherwise the black fade; let its last transition be `X2` when outro exists, otherwise the black fade. Their sum must not exceed `C`.
- For an intro, `black fade + X1 <= I`; for an outro, `X2 + black fade <= O`.
- Two source audio fades must fit inside `C`. Unknown source geometry/FPS/track or unsupported output profile refuses planning, rather than guessing.
- Normalize to the actual output timing profile and recheck constraints. Return overlap-aware total duration. Validate rendered duration within the declared video/audio frame tolerance; do not silently change range/card choices to make an invalid plan fit.

Examples with a 30-second clip and proposed timing:

| Cards | Duration |
| --- | --- |
| Intro + outro | 35.0 s |
| Intro only / outro only | 32.5 s |
| Neither | 30.0 s |
| Either card only 0.5 s, with 0.35 s black fade + 0.5 s crossfade | Invalid; reject before Generate |

## 4. Composition

Normalize all segments to one explicit supported geometry, FPS/time base, pixel format and audio profile before concatenation/blending. Reset segment timestamps. Preserve source aspect ratio; proposed card fit is contain/pad on black, with explicit alpha compositing. Never stretch/crop the source or text/logo card silently. Proposed maximum is 720p with no upscaling; lower-resolution sources do not inherit a 1080-class processing validation floor.

Cards are silent. Source audio fades relative to the selected clip and is aligned to the video overlap offsets; silence fills the remaining output. Do not add card sounds/music or accidentally double-fade/misalign tracks through two conflicting transition pipelines. No autoplay sound in review. Only an independently decoded/validated completed output becomes a candidate.

## 5. Proposed API and lifecycle

Names below are a contract proposal, not deployed endpoints. Reuse current session/origin/request-header protections, server-side source/card validation and version guards. New UI is capability-gated when served against an older backend.

| Route | Effect |
| --- | --- |
| GET `/api/preview/cards`, GET card-image route | Versioned list/thumbnails; no mutations or provider calls |
| POST `/api/preview/cards/import` or replacement action | Validated private immutable image version; explicit import only |
| GET/POST `/api/preview/defaults` | Read or explicitly save versioned defaults; no job starts |
| POST `/api/preview/plan` | Read/validate inputs; produce immutable reviewed snapshot and opaque token |
| POST `/api/preview/generate` | Require current plan token/idempotency key; create one durable job, return ID/status/lane |
| GET `/api/preview/job?id=…` | Read job/progress/candidate/provenance; no action |
| POST `/api/preview/select` | Explicitly select an exact validated candidate/version for Curator; atomic pointer update/history |
| POST `/api/preview/publish/plan`, POST publish action | Separate destination/collision review and approval; implemented by #143 |

Proposed internal render kind `preview_render` appears under the existing **Encoding** lane, using reviewed per-type scheduling/reservations and limits. It is not a new sixth lane or a normal movie optimization. If Encoding is paused, Generate creates Waiting with an explicit queue link; it does not start unrelated queues. During an active queue, the durable scheduler picks it up normally. Retrying rendering requires a newly checked plan; unknown publication is inspected, not replayed.

Generate closes setup and opens/links the specific queued job. Prevent duplicate submissions with the persisted idempotency key. Outdated render responses cannot overwrite a newer draft. Keep the previous candidate/Curator selection until its replacement is validated and explicitly chosen. Preserve draft, selected library, filters, playback/scroll and return focus across navigation; guard unsaved edits.

Each candidate record includes job/asset IDs, exact source interval/fingerprint/hash, card IDs/versions/hashes, defaults/plan revision, effective settings, output digest/technical validation, initiator and outcome. Job outputs remain in private versioned storage. No automatic source modification, selected-preview overwrite, provider generation, full-library dispatch or publication.

Curator save is atomic and version-guarded. Plex publication separately reviews exact candidate, destination, prior trailer and capability; it uses existing file operations and keeps originals/old trailers. **Local saved → Plex association pending → verified** are distinct states. Respect scheduled scans. Missing immediate association is not an instruction to force a scan or roll back a verified local write. No paid generation, automatic agent switch or implicit library refresh.

## 6. Review and implementation gates

Synthetic fixtures unblock development; real PNG delivery is #139, not a dependency of #140/#141. Current HTML is a workflow illustration, not an API implementation or actual player. Approval of this render/contract and independent review completes #138; #140 onward requires its own implementation, relevant tests, exact-head review and acceptance. Disposal-library/client publication checks need their separate confirmed scope. This design does not grant production or provider permissions.
