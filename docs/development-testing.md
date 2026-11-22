# Isolated v2 development and testing

The operator authorized a separate DEV/TEST instance for reviewing working v2
changes. This is a test deployment, not v2 release acceptance or production promotion.
Use a separate checkout and dedicated sandbox. Never copy a production database,
provider key, queue, catalogue or media directory into it.

## Profile and startup

Python 3.11+ is required. From the test checkout:

```sh
python3 scripts/seed-development.py --development-root "$HOME/Curator-DEV"
python3 -m curator.web --development-root "$HOME/Curator-DEV" \
  --state "$HOME/Curator-DEV/state" --port 8791
```

The seed uses installed FFmpeg to create three short synthetic videos, local artwork,
a sample home library and metadata recommendations. All queues start paused. It refuses
an existing catalogue or output file. Do not use `--replace` to reseed data.

The optional development profile:

- Shows a DEV / TEST banner, page title and service status environment.
- Uses a separate session cookie per dev port; production sessions retain their name.
- Rejects unmarked existing state and sandboxes overlapping the default production state.
- Blocks Plex, Mage REST/pricing/downloads, Mage key storage and vision analysis.
- Rejects external media mappings and archive roots, including resolved symlink escapes.
- Serves explicitly seeded synthetic artwork from within the sandbox.

This is a guard against accidental configuration reuse, not an OS security boundary
against a malicious local user. Do not put production data in the sandbox. Provider
workflows intentionally fail with an explicit disabled message; this instance supports
local/UI testing, not live Plex publication or paid generation. Testing those integrations
later requires a separate deliberate configuration and disposable service data.

## Foundry managed instance

Use an explicit private bind and a distinct label. Example from the test checkout:

```sh
python3 scripts/install-foundry-launchagent.py \
  --label com.curator.foundry.dev --development-root "$HOME/Curator-DEV" \
  --state "$HOME/Curator-DEV/state" --port 8791 \
  --host 10.0.0.10 --expected-host foundry --expected-host foundry.example.test
```

Substitute the verified host address and browser names. The installer prints bootstrap
commands for this user's GUI session. The DEV LaunchAgent starts after login, independently
of a production system LaunchDaemon. It does not start before login. It refuses the
production label in development mode. Never boot out or restart the production service
as part of test deployment.

Update only the test checkout to the exact reviewed/tested feature or v2 commit; confirm
its worktree is clean, restart only the dev label, then verify `/api/service/status`, the
banner, synthetic catalogue and provider/path guards. Preserve dev state across updates.
Record the deployed SHA on the issue. A feature branch can be deployed here for review;
that does not substitute for independent review before merging it into v2.

Rollback consists of stopping only the dev label and returning the dev checkout to the
last tested commit. Retain its sandbox. Remove the test instance only by explicit request.

## Trailer cards (first implementation slice)

Settings → Trailers → Manage trailer cards imports normalized PNGs under10MiB,
up to4096px per side /8million pixels. Browser import normalizes PNG pixels; the
server validates PNG contents and stores its own immutable version/hash. Replace
creates a new version. Hide removes a choice without deleting retained versions.
Defaults pin explicit versions, use optimistic revision checks and never start jobs.
Read/reset is not a save; no-op saves create no history. Missing/changed selected
versions must be resolved explicitly. Existing Settings draft stays beneath the
card dialog. JPEG/PSD import and cleanup are not implemented by this slice.

This is #140 only; card settings do not imply the renderer/review features
(#141/#142) are already available. No provider or Plex call occurs.

## Local preview renderer

Preview tasks use `preview_render` identity and share Encoding's order, workers,
pause and limit with optimization. A reviewed immutable plan pins source identity,
selected interval/audio, card versions/hashes and tool identities. Generation only
queues; it never resumes paused work. Duplicate submission keys return the same job.
A fresh plan is required after stale source/settings/tool inputs or a failed retry.

The initial output is H.264 MP4, at most1280×720 without spatial upscaling,30fps,
with AAC stereo when the source has audio. Selected multichannel audio is downmixed
and limited; cards are silent. Silent sources produce silent previews. Card images
contain/pad on black; transparent pixels are composited on black. Timings normalize
to output frames and are returned before approval. HDR conversion is unsupported.
FFmpeg must expose libx264 or macOS h264_videotoolbox plus AAC. Nothing is published
or replaces the source. Interrupted jobs remain blocked and partial outputs are
retained outside the verified-candidate index. Validation checks decoding, duration,
geometry, codec, expected audio and source/card identity before offering review.

References: [FFmpeg xfade](https://ffmpeg.org/ffmpeg-filters.html#xfade),
[adelay](https://ffmpeg.org/ffmpeg-filters.html#adelay). Keep stream profiles and
time bases equal before blending; apply the source audio offset once.

## Clip editor and candidate review

Open a sample media file, then **Create preview**. Drag the start slider, use0/30/60s
quick picks or enter an exact timestamp. Advanced exposes the default30s requested
length, card durations/fades and original audio. The server shows frame-normalized
range, shortened length and overlap-aware total before Generate becomes available.

Generate closes setup and opens its exact job in Encoding. Paused work remains
waiting; use the existing Encoding control to run it. Unknown submission outcomes
retain the same key across reload; **Check job** reconciles it while Reset/editing
stay locked. Inputs never silently create a second render.

Completed candidates have a real player with user-initiated playback and default
muting. Leaving the inspector pauses media and retains playback position. Source
playback depends on browser codec support; a refreshed source frame and H.264
candidate provide a fallback. All source/candidate routes require the existing
session and support bounded-memory byte-range streaming.

**Use in Curator** re-verifies source/card/candidate identity and atomically compares
the selected-preview revision. It closes review on success and changes only the
Curator selection. Previous candidates remain retained. Concurrent selection/delete
requests cannot remove the selected job; stale edits keep their candidate/draft.
**Publish to Plex** is visibly disabled until#143 is implemented and separately
accepted. Trailers do not replace movies or call Mage. Drafts are stored in this
browser tab, with in-memory fallback when browser storage is unavailable.

## Standards editor

Settings → Library standards opens type defaults and per-library override editing,
keeping the existing Settings form and its unsaved values intact. Review shows every
changed field and its scope before save. No-op saves do not advance revisions or history.
Library saves require the reviewed parent kind, revision and server-provided digest
inside the same transaction as the library revision/write. A conflict keeps the draft;
reload is explicit. Test this with synthetic libraries and another client changing a
type standard during a library review. No jobs or media changes should result.

The Configuration navigation shell and standards-driven scanning are separate slices;
these controls do not themselves approve work. The legacy preserve_originals field is
labelled Skip space-saving re-encoding suggestions and never changes original retention.
See [implementation evidence](designs/v2-standards-editor-20261122/README.md).
