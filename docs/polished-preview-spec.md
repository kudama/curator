# Curator — polished preview / local trailer specification

Draft for review · 2026-11-19 (America/Los_Angeles)

Scope: a focused Curator V2 feature. The operator selected a **polished preview made from the original movie footage**. This document does not change the broader V2 specification being developed separately. Baseline reviewed: V2 commit `aa1347a396379a2730ea7485887b660d8234a7a3`. No implementation or media processing is performed by this specification.

## 1. Outcome

Help someone decide whether to watch a movie by giving them a short, attractive preview. Make generating a useful result almost as straightforward as selecting “use 1:00–1:30,” with clean presentation and an easy way to choose a better moment.

Use original footage and original sound. Preserve the film's identity, composition and intended appearance. The result is a preview excerpt, not a promise of an edited story trailer or spoiler-free summary.

## 2. First-release feature list

| ID | Feature | Required behavior |
| --- | --- | --- |
| PRE-01 | Choose an excerpt | Select an exact movie/edition/file and start time; preview the proposed source interval. Provide a configurable initial suggestion and manual adjustment. |
| PRE-02 | Natural boundaries | Offer a bounded scene-boundary adjustment near the selected interval. Show the actual resulting time range. Manual time selection remains usable when no suitable boundary is found. |
| PRE-03 | Polish | Add an optional title card using existing movie artwork/title, short video/audio fades and playback-safe audio leveling. Preserve original footage; no generative restyling. |
| PRE-04 | Generate and review | Render locally as a background task, play the result, adjust settings, or select another moment. Keep the previous candidate until its replacement is ready. |
| PRE-05 | Save for Curator | Explicitly approve a candidate for use as that movie's preview in Curator. Preview playback is user-initiated with a clear sound control. |
| PRE-06 | Publish to Plex | Separately approve saving the candidate as a local movie trailer in a verified Plex-supported layout. Retain any prior trailer and verify the resulting association. |
| PRE-07 | Batch preparation | Select explicit movie sets, preview the plan/count and queue generation without a dialog per item. Approvals identify selected candidates and exact publication destinations. |
| PRE-08 | Traceable results | Record source, interval, effective settings, candidate versions, outcome and publication receipt in the existing job lifecycle/history. |

### Proposed initial defaults

These are implementation starting points for review, not settled library-wide standards.

| Setting | Proposed default |
| --- | --- |
| Footage length | 30 seconds |
| Suggested start | 1:00 for sources long enough; otherwise ask for or show an appropriate valid interval |
| Boundary mode | Search locally near the chosen boundaries; cap the adjustment to a few seconds and show it before generation |
| Title card | Optional, enabled initially; 2 seconds using the existing title and approved artwork |
| Fades | Short, approximately 250 ms, without adding a transition between unrelated scenes |
| Audio | Selected original audio track, normalized for comfortable preview playback; no added music |
| Output | MP4 with browser-tested H.264 video and AAC audio; maximum 720p, retaining source aspect ratio and never upscaling |
| Concurrency | One preview render at a time initially, through existing queue controls |
| Publication | Review first; generation alone publishes nothing |

Show the **total** output duration. A 30-second excerpt plus a 2-second title card is approximately 32 seconds; fades must not silently change the selected source range. Clamp or reject invalid ranges explicitly. Do not silently choose a closing scene for a short source.

## 3. User flow

1. From the movie's existing work area, choose **Create preview**. Identify the library, edition/file and whether a preview/trailer already exists.
2. Show a source frame/player with start time and duration controls. Provide **Use this moment**, an optional natural-boundary adjustment, and a way to move to another moment. Never imply this analyzes or summarizes the whole movie.
3. Show the effective interval, title-card appearance, chosen audio track, output settings and expected total length. Unsupported input/tool states have a useful explanation.
4. Choose **Generate preview**. The task runs in the background; the operator can keep working and return without losing the draft or playback position.
5. Play the result and choose **Use in Curator**, **Adjust**, **Try another moment**, or **Discard**. Adjustments create a new candidate and do not replace the approved preview automatically.
6. **Publish trailer to Plex** is an explicit separate destination action. Show the exact movie and existing-versus-proposed local trailer before approval. Report “Saved,” “Plex verified,” or a concrete verification problem accurately.

Keep playback controls and the main action visible on desktop and phone layouts. Do not autoplay sound or automatically expand a player just because a recommendation receives focus. Reuse the application’s inline feedback, inspector/draft conventions and theme selection.

## 4. Local rendering and media behavior

Reuse the existing FFmpeg/ffprobe discovery, task persistence, progress reporting and output validation. No mandatory model, cloud service or additional scene-detection dependency is required for the first release. Use a bounded scan around the requested interval when supported; fall back to an explicit time-based excerpt. Avoid full-movie semantic analysis for this feature.

- Read the source; never rewrite, rename, upscale or re-encode the original movie as part of preview generation.
- Use captured settings and source identity for each job. A later standards change applies to future plans, not already approved jobs.
- Preserve aspect ratio and source frame geometry. Preview any requested crop/pad separately; do not stretch to a fixed trailer shape.
- Preserve dialogue and selected-language audio. Downmix multichannel input safely for browser playback; avoid clipping and loud title-card audio. A silent source produces a valid silent preview with a clear indication.
- Use existing approved artwork or a plain title card when artwork is absent. Do not trigger artwork generation or require a paid provider to produce the card.
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

Existing [metadata/artwork preservation issue #70](https://github.com/kudama/curator/issues/70) remains a separate open risk. Do not bypass its paused operations or claim trailer publication solves it. Existing [worker refill issue #82](https://github.com/kudama/curator/issues/82) likewise remains separate; queueing a preview must not promise unattended starts that the scheduler does not yet support.

## 6. Configuration and future automation

Expose preview defaults through the separately designed V2 Configuration standards: duration, initial interval strategy, title card, audio/output preferences, concurrency and retention. Allow explicit per-job overrides; display their effective values.

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
2. Title-card on/off, missing artwork, aspect ratios, silent/stereo/multichannel and selected-language audio produce playable outputs without clipping or source mutation.
3. Adjust/regenerate, discard, browser refresh and navigation preserve the selected candidate/draft appropriately; theme changes retain state. No autoplay sound or hidden primary actions at narrow widths.
4. A batch has a reviewable target/count/settings plan; zero jobs begin from simply selecting media. One source's failure does not discard other candidates or falsely mark the batch complete.
5. Pause, cancellation, source changes, concurrent jobs, restart and unavailable tools/mounts leave correct durable states. No automatic replay, duplicate output adoption or unfinished-file approval.
6. Curator approval and Plex publication remain distinct. Synthetic publication checks cover wrong edition/identity, existing trailers, interrupted copies, stale approvals and Plex readback failure; previous media/trailers remain intact.
7. Job history identifies the source interval, settings version, initiator, candidate and verified outcome without exposing credentials.
8. Run one separately authorized disposable Plex-library acceptance test to verify local naming, item association and playback on the operator’s chosen client before enabling real-library publication.

Recommended delivery order: **excerpt and local polish → review/save in Curator → verified Plex trailer publication → selected batches → later standing-rule automation**. Each slice needs behavioral tests and a realistic visual/playback review; a working renderer alone does not establish a pleasant preview experience.

## 9. Remaining decisions

Review the proposed defaults against a few representative movies. Confirm the target Plex clients/agents and desired retention limits before rollout. Added music, deeper AI selection and future automatic publication remain later choices. These do not prevent implementing the local excerpt/polish/review slice.

References: [Plex local movie trailers and extras](https://support.plex.tv/articles/local-files-for-trailers-and-extras/), [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html), existing [task queues](task-queues.md) and [file-operation queue](file-operation-queue.md).
