# Trailer synthetic acceptance preparation (#145)

Status: synthetic preparation only. This is not release, operator-card, real Plex
client, network filesystem or deployment acceptance. Executor: Codex
trailer_delivery; integrating/reviewing controller: root. Parent: #137.

## Reviewed implementation and exact scope

The candidate stack is PR #164 `553d5c605ba217934340efd0288a7be81cbc9962`
then PR #166 `0ca6fd907900be2b2bdeefa16ff754684b75ffc8`, on V2 `4d16be1`.
This acceptance-only change adds no production endpoint, queue, provider call or
automatic publication behavior. A subsequent integration requires its own exact
head review and required CI. Public branch updates use merges and normal pushes.

The combined regression `tests/test_preview_workflow_acceptance.py` uses real
local FFmpeg/ffprobe, a generated three-second stereo test-pattern video, synthetic
landscape/portrait PNG cards, temporary private state, and an injected fake Plex
client. It skips explicitly when tools or required encoders are absent; a skip is
not rendering evidence. It deliberately executes only its disposable job while
asserting that the shared Encoding and File operations queues remain paused.

Its explicit two-source batch pins interval, audio and both card versions before
any jobs exist. Changing one selected source produces a durable mixed result;
the other renders the reviewed 0.5–2.5 second interval. Three-second cards and two
0.5-second overlaps yield seven seconds total. The candidate is H.264 at the
source's 320×180 size with audio. Rendering and saving in Curator create no file
publication job. Separate publication review and approval create the paused file
job; explicit fixture execution makes an additive hash-verified local trailer,
retaining source bytes, the previous trailer and Curator selection. Association
stays pending, fake Plex records no writes, and replay is refused.

## Complementary existing regression coverage

| Requirement | Existing fixture evidence |
| --- | --- |
| Card immutability, hidden/replaced/missing cards, stale defaults | `test_preview_cards.py`; `test_preview_render.py` |
| Short/invalid intervals, fitting, overlaps, black/crossfade frames | `test_preview_render.py` |
| Silent, stereo, multichannel, delayed audio and source preservation | Real-media cases in `test_preview_render.py` |
| Pause, mixed Encoding pool, cancellation and restart without replay | `test_preview_render.py`; `test_preview_batches.py` |
| Authenticated playback/ranges, adjust/discard/selection retention | `test_preview_review.py` |
| Exact editions/GUID/section, old trailers, collisions, interrupted install | `test_preview_publication.py` |
| Explicit terminal-unattempted retry, no abandoned payload replay | `test_preview_publication.py` |
| Selected count/settings, per-item mixed results and crash recovery | `test_preview_batches.py` |
| Cross-feature cards → batch → render → selection → separate copy | `test_preview_workflow_acceptance.py` |

Reproduce using `python3 -m unittest discover -s tests -p 'test_preview*.py' -v`
and the repository's full tests plus Ruff. Run locally and required Python 3.11,
Python 3.13 and style CI after integration. Temporary fixture files are removed;
private production titles, IDs, artwork and local paths are not public evidence.

## Operator review steps after feature integration

1. Record the exact integrated commit and required CI results. In a disposable
   configuration, import synthetic intro/outro PNGs. Verify each role and version
   in Configuration; select an explicit source with both cards and a short interval.
2. In each of all three themes, at desktop and narrow widths, use keyboard focus
   to review the effective interval, output size, cards, audio and total duration.
   Generate once. Confirm the panel closes and the job appears in Encoding.
   Refresh/navigation/theme changes must retain the draft and its source context.
3. Open the completed candidate. Verify playback, initially muted sound controls,
   source comparison, no clipped actions or horizontal overflow, and sensible
   focus order. Adjust/regenerate, discard another candidate, then save this one
   in Curator. Confirm saving alone has no publication side effect.
4. Select two exact disposable files for a batch. Review count, each interval,
   editions and pinned shared settings. Confirm selection alone starts no job.
   Submit, make one fixture source unavailable, and verify independent mixed
   results; keep the successful candidate reviewable and saved separately.
5. Open the separate local trailer publication review for the successful item.
   Confirm exact edition/source and additive destination. Approve only this
   disposable publication. Verify retained originals/prior trailers, copy hash,
   durable receipt, and Local saved / association pending distinction. Do not
   force a Plex refresh or automatically repeat uncertain writes.
6. Retain sanitized screenshots of selection, mixed batch, candidate review and
   separate publication in desktop/narrow layouts for each theme, identified by
   integrated commit. Earlier feature-level screenshots are supporting evidence;
   they do not replace this integrated pass.

## Gates intentionally still open

- Operator-supplied finished PNG text/logo quality at supported output sizes and
  exact tested asset versions (#139). Synthetic solid-color PNGs cannot prove it.
- The complete keyboard/draft/scroll/theme matrix above against the final merged
  application; screenshots must identify that integrated version.
- Separately authorized disposable Plex library/client naming, association,
  scheduled refresh and playback. A fake extra response is not client evidence.
- Actual target filesystem behavior (including SMB if used), unavailable mount
  recovery, client/agent/layout compatibility and operational retention decisions.
- Independently reviewed final candidate, deployment and rollback plan under
  #120. No service restart, provider spend or live publication is authorized by
  this preparation document or its tests.

## Recorded local result (2026-11-22)

On the candidate stack above, the combined real FFmpeg regression passed rather
than skipped. The full suite ran 700 tests successfully with three unrelated
optional skips; full Ruff checks and formatting checks passed. This records local
synthetic verification, not independent review or the final integrated CI result.
