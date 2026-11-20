# Queue interaction and accessibility follow-up — 2026-11-19

Scope: the development approval in “Assess Modern Web Guidance,” continued in Forge on November 19. Baseline: `1fc33ce4edde99021bcf00e6dff1c8f9e7917c0e` on Curator main. The November 17 feature lock and approved visual direction remain governing. Related outcomes: Curator #53/#56; Forge #88/#89/#92.

## Changes

- Waiting-job handles support Up/Down and Home/End, retaining filtered-out jobs and other operation types in their existing slots. Both task and file-operation moves use the existing snapshot-checked endpoints. Moving beyond the five-row disclosure expands the lane, restores the handle and scrolls it into view. One persistent status region announces a successful move; rejected moves retain the existing inline error path.
- Dragging distinguishes the source and eligible same-kind drop targets. Right-button/secondary pointers are ignored. Escape, pointer cancellation and lost capture release the interaction guard so polling can render again. No cancellation path submits a reorder.
- Polling restores a focused queue control by task identity. Closing Details finds its original control after a refresh replaces that card. The inspector is a named nonmodal region: queue controls remain keyboard-accessible, with no modal focus trap. Escape respects handled child events and existing unsaved/save guards.
- Queue layout adapts to available pane width. Long names wrap; file-operation cards and inspector headers retain their controls. Phone header sizing accommodates the brand and theme selector. The pink inspector, existing lanes and themes remain intact.

The server queue/order APIs, processing, approvals, publication and provider implementations are unchanged.

## Guidance and design choice

Google's [dynamic sorting guidance](https://developer.chrome.com/docs/modern-web-guidance/guides/ui-behaviors/dynamic-sort), [dragging guidance](https://developer.chrome.com/docs/modern-web-guidance/guides/ui-behaviors/drag), and [dialog guidance](https://developer.chrome.com/docs/modern-web-guidance/guides/ui-components/dialog) informed keyboard alternatives, one status announcement, input cancellation, focus and nonmodal semantics. This focused change retains the existing polling renderer and restores focus by stable identity. It does not implement Google's broader DOM-node-preservation/animation recommendations, introduce a framework or claim a rendering-performance improvement.

## Verification

- Python: 511 tests, passing with three optional integration skips. Initial restricted-run listener/restart failures passed when rerun with temporary local listeners permitted. Compilation passes.
- JavaScript: 114 behavior checks pass, including filtered single-position movement, file snapshots, boundaries/modifiers/busy guards, pointer cancellation/capture loss, and inspector control identity. Changed scripts parse; whitespace checks pass.
- Chromium synthetic browser: 74 waiting upscale jobs, active/blocked work and the existing populated lanes; no real media, Plex or paid provider requests. Verified arrow-key movement, Home/End with visible retained focus, refresh while focused, Details open/close after polling, rejected/accepted unsaved-change prompts, Escape drag cancellation, valid pointer target/drop and a simulated HTTP 409 stale-order rejection without a false success announcement.
- Classic and Cyberpunk at 1440, 1024, 768, 390 and 320 pixels, with long filenames/library names and Details open/closed: no page horizontal overflow, footer controls present, no page JavaScript errors. Representative synthetic captures: [Classic phone](modern-web-classic-320.png), [Cyberpunk desktop](modern-web-cyberpunk-1440.png).

This is development/browser evidence, not screen-reader, Safari/touch-device or operator visual acceptance. No production deployment, service restart, live media mutation or paid generation occurred. Broader rendering performance and notification consistency remain separate review work.

## Coordination and next action

The Foundry local analyst task `60617c5890074f3b9720521b1b2a58ec` failed `tool_denied`; no worker result was accepted or grants changed. Implementation and review were performed directly. GitHub issue/source reads succeeded; project-board reads were unavailable because the existing credential lacks `read:project`. No board state is claimed or changed.

Next: review this branch/PR and the synthetic captures against the approved design. Merge/deployment and operator/live-provider acceptance remain separate.
