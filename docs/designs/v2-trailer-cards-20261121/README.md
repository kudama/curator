# Trailer cards and preview workflow

Design for #138 / parent #137. **Operator approved the displayed direction and the clip-selection interaction on 2026-11-21; independent final-head review and the remaining proposed defaults are pending.** Baseline: v2 `d0782b2c46d5c3dd790ef1cb83ac8ce184517833`.

This package is a standalone HTML prototype with synthetic names, illustrations and cards. It calls no API, processes no footage, reads no private library and spends no credits. Its playback buttons illustrate controls; they are not a rendered-video demo. It is not served by Curator. The finished card artwork will be supplied by the operator (#139); the typography/illustrations here are placeholders, not proposed finished artwork.

## What is confirmed

- One continuous source excerpt, not multi-scene trailer editing.
- A saved stock intro and outro library: prepare artwork once, reuse it for each preview.
- Operator workflow: Mage → Topaz Photo → Photoshop → finished PNG. Keep PSD masters separately.
- Fade from black to intro, crossfade into the clip, crossfade to the outro, fade to black; source audio fades in/out.
- FFmpeg composition is local; never generate images as part of rendering a preview.
- Explicit Curator selection and separate Plex-publication approval; preserve originals and previous candidates/trailers.
- A draggable start-position slider with a 30-second default excerpt, quick picks at 0:00 / 0:30 / 1:00 and an exact timestamp field. Duration is editable under Advanced. Near the end, show the available shorter range without silently moving the chosen start.

The exact durations/output profile below remain **proposed defaults**. No operator approval of these defaults is inferred from approval of the basic feature.

## Open the prototype

Open `prototype.html`; query `?s=setup`, `?s=cards`, `?s=queued&paused=1`, `?s=running`, `?s=review` or `?s=failed` selects a scenario. `theme=classic|cyberpunk|plex` selects appearance. The visibly separate Prototype controls switch scenarios. No route is a deployed Curator route.

- Setup: one source/player, draggable start slider, quick picks and exact timestamp; two independently optional card selectors; duration and overlap calculation. Duration/fades/output are collapsed to keep the main screen simple. A near-end message shows the shortened clip explicitly; invalid fade overlap still blocks Generate.
- Cards/defaults: preview saved versions and edit default timing. Saving updates this prototype's in-memory defaults only; existing draft/job values are retained. Library import/version behavior is specified in the contract and implemented by #140.
- Generate closes setup and shows one Encoding job. A paused queue explicitly shows Waiting. There is no second Generate action floating over an already submitted job.
- Review: candidate playback/sound controls, adjust/discard, explicit Use in Curator and a separate Publish to Plex confirmation.
- Error: the previous candidate is retained; recovery returns to a newly reviewed plan.
- Leaving dirty setup for card settings opens Keep editing / Discard and leave. Reset restores defaults without changing submitted plans.

The synthetic player and simulated publication receipt are illustrative only. Actual playback/rendering/publication are #141–#143. Full application routing, background job execution, API revision checks and persistence are not implemented by this package.

## Proposed first delivery

| Setting | Proposal | Rule |
| --- | --- | --- |
| Clip selection | Start slider + quick picks + exact timestamp; 30-second default | Approved interaction. Initial suggested start remains proposed; near the end preserve start and display the shorter available range |
| Cards | Optional intro and outro; 3 seconds each | Select exact saved versions; either or both may be disabled |
| Crossfades | 0.5 seconds at enabled card/clip boundaries | Overlap shortens total duration; the whole source interval remains present, with blended edge frames |
| Black fades | 0.35 seconds at the first/last visual segment | Change opacity, not total duration |
| Source audio fades | 0.5 seconds in/out | Cards are silent; preserve selected source audio, align with video offsets |
| Output | H.264/AAC MP4, up to 720p, no upscale | Retain source aspect ratio; freeze one supported geometry/FPS/audio profile for all segments |
| Master card guidance | PNG; 1920×1080 for landscape artwork | This is guidance, not forced stretching or a requirement to recreate existing high-quality cards |
| Card fitting | Fit inside output canvas, black matte | Preserve text/logos; alpha composited on the chosen explicit background; no automatic crop |
| Text/logo safety | Keep important content in the central 80% | Guidance for operator assets; actual fit/pad preview is authoritative |

For the illustrated 30-second clip: **3 + 30 + 3 − 0.5 − 0.5 = 35 seconds**. See [contract.md](contract.md) for validation, optional-card cases and frozen job fields. PR #87's earlier two-second per-film title-card proposal is superseded by reusable stock bookends; other unconfirmed defaults remain proposals.

## Render package

`setup.png`, `review.png`, `cards.png`, `phone-setup.png` and the theme examples are generated from this HTML using isolated headless Chrome. Render/interaction verification is recorded in the PR; do not infer validation from a filename alone. New screenshots show synthetic data only.

## Delivery and approval

1. #138: finish this contract/prototype, verify it, obtain operator render approval and independent exact-head review.
2. #140: implement card library/defaults with synthetic images. Real artwork (#139) does not block coding.
3. #141: implement renderer/queue using the frozen contract; #142 adds actual playback/review/save.
4. #143: explicit Plex publication; local saved versus association pending/verified stay distinct. No forced library refresh is implied.
5. #144 / #145: selected batches and integrated acceptance, including actual supplied cards and separately authorized disposable Plex playback checks.

Codex owns senior architecture/integration and review of any Forge worker proposals. The controller task IDs and any unavailable results are recorded on #138, not represented as completed or independent review. Claude availability is not required to create or inspect this prototype; no Claude approval is fabricated. The application implementation does not start before the reviewed render/contract gate is met.

## Remaining decisions

Confirm proposed timing defaults, output profile and card fitting after viewing the renders. The operator can prepare final artwork whenever convenient. No finished card artwork, paid image calls, runtime code or production media are created by this design task.
