# Curator — polished preview / local trailer specification

Draft for review · updated 2026-11-21 (America/Los_Angeles)

Scope: the operator-confirmed trailer workstream [#137](https://github.com/kudama/curator/issues/137), carried forward from PR #87. The operator selected a **single excerpt from original footage with reusable stock intro/outro cards**, black fades, crossfades and source-audio fades. Baseline: v2 `d0782b2c46d5c3dd790ef1cb83ac8ce184517833`. This specification/prototype is not an implemented renderer. [Design package and versioned contract](designs/v2-trailer-cards-20261121/README.md); task #138 records render approval and review status.

## 1. Outcome

Help someone decide whether to watch a movie by giving them a short, attractive preview. Make generating a useful result almost as straightforward as selecting “use 1:00–1:30,” with clean presentation and an easy way to choose a better moment.

Use original footage and original sound. Preserve the film's identity, composition and intended appearance. The result is a preview excerpt, not a promise of an edited story trailer or spoiler-free summary.

## 2. First-release feature list

| ID | Feature | Required behavior |
| --- | --- | --- |
| PRE-01 | Choose an excerpt | Select an exact movie/edition/file, drag a start-position slider or use 0:00 / 0:30 / 1:00 quick picks and an exact timestamp. Default length is 30 seconds; duration is editable under Advanced. Preview the resulting source interval. |
| PRE-02 | Natural boundaries | Offer a bounded scene-boundary adjustment near the selected interval. Show the actual resulting time range. Manual time selection remains usable when no suitable boundary is found. |
| PRE-03 | Polish | Fade from black onto the intro, crossfade to the excerpt, crossfade to the outro and fade to black; fade source audio in/out. Cards are independently optional. Preserve footage geometry and selected original audio; no generative restyling. |
| PRE-04 | Generate and review | Render locally as a background task, play the result, adjust settings, or select another moment. Keep the previous candidate until its replacement is ready. |
| PRE-05 | Save for Curator | Explicitly approve a candidate for use as that movie's preview in Curator. Preview playback is user-initiated with a clear sound control. |
| PRE-06 | Publish to Plex | Separately approve saving the candidate as a local movie trailer in a verified Plex-supported layout. Retain any prior trailer and verify the resulting association. |
| PRE-07 | Batch preparation | Select explicit movie sets, preview the plan/count and queue generation without a dialog per item. Approvals identify selected candidates and exact publication destinations. |
| PRE-08 | Traceable results | Record source, interval, effective settings, candidate versions, outcome and publication receipt in the existing job lifecycle/history. |
| PRE-09 | Reusable cards | Import finished PNG card assets once into a private versioned library; choose default intro/outro cards and per-job overrides. Pin selected card versions/hashes. Never call Mage or another image provider while rendering a trailer. |

### Proposed initial defaults

These are implementation starting points for review, not settled library-wide standards.

| Setting | Proposed default |
| --- | --- |
| Footage length | 30 seconds |
| Suggested start | 1:00 for sources long enough; otherwise ask for or show an appropriate valid interval |
| Boundary mode | Search locally near the chosen boundaries; cap the adjustment to a few seconds and show it before generation |
| Intro / outro cards | Independently optional; prototype proposes 3 seconds each, selected from saved stock cards. This replaces PR #87's proposed per-film two-second title card. |
| Transitions | Prototype proposes 0.5-second crossfades and 0.35-second black fades; adjustable and subject to the overlap limits in the contract |
| Audio | Selected original audio track, normalized for comfortable preview playback; no added music |
| Output | MP4 with browser-tested H.264 video and AAC audio; maximum 720p, retaining source aspect ratio and never upscaling |
| Concurrency | One preview render at a time initially, through existing queue controls |
| Publication | Review first; generation alone publishes nothing |

Show the **total** output duration, including crossfade overlap. For example, 3-second intro + 30-second excerpt + 3-second outro − two 0.5-second overlaps = **35 seconds**. Black fades change opacity, not length. The full chosen source interval is used, with its edge frames blended into the selected cards; show that fact before approval. Reject invalid ranges/overlaps explicitly; do not silently select another interval or a closing scene for a short source.

## 3. User flow

1. From the movie's existing work area, choose **Create preview**. Identify the library, edition/file and whether a preview/trailer already exists.
2. Show a source frame/player with draggable start slider, quick picks and exact timestamp input. Use 30 seconds from that point by default; Advanced exposes duration. Show the resulting interval and let the operator play it before Generate. If less footage remains, display the shortened interval without moving the selected start; invalid overlaps still require correction. Optional natural-boundary adjustment remains explicit and bounded. Never imply this analyzes or summarizes the whole movie.
3. Select reusable intro/outro cards or turn either off. Show their versions, duration, fit, effective fades, chosen audio track/output settings and overlap-aware total length. Settings → trailer cards/defaults manages the reusable set; no paid generation is involved.
4. Choose **Generate**. Submission closes the setup view and exposes the durable job in the existing Encoding lane, without a sixth top-level queue. A paused queue clearly reports Waiting and is not implicitly resumed. The operator can keep working and return without losing draft/playback context.
5. Play the result and choose **Use in Curator**, **Adjust**, **Try another moment**, or **Discard**. Adjustments create a new candidate and do not replace the approved preview automatically.
6. **Publish trailer to Plex** is an explicit separate destination action. Show the exact movie and existing-versus-proposed local trailer before approval. Report “Saved,” “Plex verified,” or a concrete verification problem accurately.

Keep playback controls and the main action visible on desktop and phone layouts. Do not autoplay sound or automatically expand a player just because a recommendation receives focus. Reuse the application’s inline feedback, inspector/draft conventions and theme selection.

## 4. Local rendering and media behavior

Reuse the existing FFmpeg/ffprobe discovery, task persistence, progress reporting and output validation. No mandatory model, cloud service or additional scene-detection dependency is required for the first release. Use a bounded scan around the requested interval when supported; fall back to an explicit time-based excerpt. Avoid full-movie semantic analysis for this feature.

- Read the source; never rewrite, rename, upscale or re-encode the original movie as part of preview generation.
- Use captured settings and source identity for each job. A later standards change applies to future plans, not already approved jobs.
- Preserve aspect ratio and source frame geometry. Preview any requested crop/pad separately; do not stretch to a fixed trailer shape.
- Preserve dialogue and selected-language audio. Downmix multichannel input safely for browser playback; avoid clipping and loud title-card audio. A silent source produces a valid silent preview with a clear indication.
- Use explicitly selected reusable card versions. The operator prepares artwork externally (Mage → Topaz Photo → Photoshop → finished PNG) and retains PSD masters separately. Fit/pad with the approved background; do not stretch or silently crop text, logos or source footage. Alpha is composited onto an explicit background. Missing selected assets require a new reviewed plan, not silent substitution or a provider call.
- Show source intervals and the limitations of selection. An early interval, black-frame/silence checks or scene boundaries cannot establish spoiler safety.
- Validate output decoding, duration, dimensions, audio where expected and file completion before offering approval. Never show a partial render as a finished preview.

## 5. Storage, queues and publication

Keep drafts, candidate files and approved previews in private Curator-managed storage, outside source control and separate from movie originals. Use stable asset/edition IDs and versioned output names; a title alone is insufficient identity. Retain provenance and previous approved versions until an explicit retention/cleanup action applies.

Use the existing durable queue and relevant source reservations. Concurrent processing/publication must not adopt a changed movie or race a preview commit. Capture and recheck source identity; stale, missing or remapped sources fail with a recoverable message. Follow existing safe pause/cancel behavior, bounded shared file-operation limits and no automatic startup replay. Retry rendering only from a newly checked source/plan; do not blindly repeat an uncertain publication.

For **Curator approval**, verify the candidate and atomically update the movie's selected preview; keep the previous selection available for recovery.

For **Plex publication**:

- Verify library/agent/client capability and exact movie-folder mapping first. Local movie trailer conventions are documented by Plex, but this is not proof that every installed client or library type supports the same behavior.
- Stage a completed trailer using a supported `-trailer` filename or `Trailers` folder. Prevent it from being scanned as a separate feature movie.
- Never overwrite an unrelated or existing user trailer. Offer a clearly reviewed replacement only when the earlier file is identified and retained; otherwise report a collision.
- Keep staged copies, approvals and receipts sufficient to distinguish completed, failed and uncertain outcomes. Missing mounts, destination collisions and interrupted copies preserve the original movie and prior trailer.
- Verify local-file integrity and the Plex association where supported. Use the existing bounded refresh/readback path only after identity checks. A changed rating key or lost metadata is a conflict, not permission to rematch or rewrite the movie.
- If the target cannot be verified or is unsupported, keep the approved Curator preview and explain why Plex publication is unavailable.

Existing [metadata/artwork preservation issue #70](https://github.com/kudama/curator/issues/70) remains separate; its first reviewed slice is deployed, while artwork/portrait restoration UI and full acceptance remain outstanding. Do not bypass any operator pause or claim trailer publication completes it. Preserve the current worker-refill/queue guards and test new task integration rather than claiming old issue titles prove runtime acceptance. Local trailer publication follows the scheduled Plex scan: local file saved, association pending and association verified are distinct states. No forced refresh is implied by generating or saving a Curator preview.

## 6. Configuration and future automation

Expose preview defaults in Configuration alongside the existing processing/defaults conventions: interval suggestion, default intro/outro card versions, durations/transitions, audio/output preferences and supported queue settings. Do not extend type-standard schema implicitly; coordinate with #109 and record the exact storage/API contract. Allow explicit per-job overrides and show their effective values.

First release is manual or explicitly selected batch generation. No full-catalog processing, upload, publication or new-arrival automation runs merely because this feature is installed or a library is scanned. Future standing rules may enable those actions only within an explicitly configured scope and with the existing approval/recovery model. The feature must remain usable without those future rules.

## 7. Outside the first release

- Story-aware multi-scene trailers, plot summarization and guaranteed spoiler detection.
- Mage video-to-video restyling, generated actors/scenes, narration, voice cloning or paid generation.
- Automatic soundtrack replacement or music sourcing/licensing. User-supplied music can be considered later as a distinct option.
- Full-movie AI analysis, face recognition or automatic personal-footage uploads.
- Home-movie highlight reels and TV season/episode trailers. Preserve room for these later; do not assume movie extras behavior applies to them.
- A new standalone trailer application, redesign of the V2 tabs, or replacement of existing media-processing infrastructure.

## 8. Acceptance and delivery

Use synthetic sources and temporary state for development. Before rollout, demonstrate:

1. An explicit 1:00–1:30 excerpt, manual adjustment and optional bounded scene adjustment yield the displayed interval/length; short sources, credits/black frames, no cuts and invalid time ranges have usable fallbacks.
2. Either/both cards off, pinned/replaced/missing stock cards, black fades/crossfades, total duration, aspect ratios, silent/stereo/multichannel and selected-language audio produce playable outputs without clipping or source mutation.
3. Adjust/regenerate, discard, browser refresh and navigation preserve the selected candidate/draft appropriately; theme changes retain state. No autoplay sound or hidden primary actions at narrow widths.
4. A batch has a reviewable target/count/settings plan; zero jobs begin from simply selecting media. One source's failure does not discard other candidates or falsely mark the batch complete.
5. Pause, cancellation, source changes, concurrent jobs, restart and unavailable tools/mounts leave correct durable states. No automatic replay, duplicate output adoption or unfinished-file approval.
6. Curator approval and Plex publication remain distinct. Synthetic publication checks cover wrong edition/identity, existing trailers, interrupted copies, stale approvals and Plex readback failure; previous media/trailers remain intact.
7. Job history identifies the source interval, settings version, initiator, candidate and verified outcome without exposing credentials.
8. Run one separately authorized disposable Plex-library acceptance test to verify local naming, item association and playback on the operator’s chosen client before enabling real-library publication.

Delivery tasks: **design #138 → card library/defaults #140 → excerpt and local polish #141 → review/save #142 → separate Plex publication #143 → selected batches #144 → acceptance #145**. Operator assets are #139; synthetic fixtures keep software work independent of their arrival. Later standing-rule automation remains outside this workstream. Each slice needs meaningful behavioral verification; a working renderer alone does not establish a pleasant preview experience.

## 9. Remaining decisions

Review the proposed defaults against a few representative movies. Confirm the target Plex clients/agents and desired retention limits before rollout. Added music, deeper AI selection and future automatic publication remain later choices. These do not prevent implementing the local excerpt/polish/review slice.

References: [Plex local movie trailers and extras](https://support.plex.tv/articles/local-files-for-trailers-and-extras/), [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html), existing [task queues](task-queues.md) and [file-operation queue](file-operation-queue.md).
