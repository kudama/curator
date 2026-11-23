# Selected preview batches

Implementation #144 builds on the single-file preview renderer and separate
local trailer publication. In a media inspector, choose **Create selected
previews**, explicitly check up to 50 exact sources in the current library, and
choose each start timestamp and original audio track. Shared intro/outro choices
and timing/output settings can be adjusted before **Review selected**.

Review names every selected file/edition, effective interval (including any
shortening at source end), duration, immutable card versions/hashes and effective
settings. **Queue N previews** approves only the reviewed plans that are
available. Unavailable items remain visible with their own errors; they do not
silently disappear or mark a batch successful. No scan, installation or library
refresh creates a batch, and no queue is automatically resumed.

Each item is an ordinary durable `preview_render` job in Encoding, with existing
limits, source reservations, cancellation, validation and History. The batch
receipt links the individual job IDs and reports mixed outcomes. Reopen a batch
from any of its jobs or from the picker’s recent batch list. **Review candidate**
opens the existing player and **Use in Curator** action. Existing candidates and
selections remain intact. Publication is per item through the separate exact
candidate/destination review; this feature introduces no bulk publish shortcut.

The manifest and submit key are persisted before dispatch. Stable per-item keys
make retry after a partial submit recover the existing job rather than duplicate
it. A crash between durable job creation and recording its ID is covered by the
same key. Failed items do not automatically rerender; prepare a fresh reviewed
batch for intentional retries. Source/edition, defaults, selected hidden cards,
pinned bytes or tool changes refuse stale work under the existing renderer
checks. Replacing a card version does not alter already pinned bytes or jobs.
A selected batch is never a standing new-arrival rule.

Synthetic tests cover exact selection/settings, physical-file aliases, missing
sources, changed source/edition, mixed completion and retained candidate state,
stale defaults, concurrent submission and crash recovery. Actual Chromium
checks cover desktop and narrow selection/review, effective shortening, no
panel/page overflow, close-on-submit, correct per-source job identity and paused
Encoding. Real card/media/client acceptance remains separately tracked in #145;
no live library/provider operation is evidence for this implementation.
