# Curator v2 — maintenance permissions (proposed)

Draft 2026-11-20 for [#117](https://github.com/kudama/curator/issues/117).
Requires operator acceptance; no permission, scheduler or runtime behavior is
installed by this document. Implementation remains gated by #118 and #107.
Read with [product direction](curator-v2.md), [standards](curator-v2-standards.md)
and [history](curator-v2-history.md).

## Intent and first slice

Let an operator reuse reviewed cleanup choices for newly arrived items in one
library. Standards describe the desired result; a separate maintenance rule
specifies permitted actions. Existing connections, a saved standard, previous
approvals and inferred preferences never enable a rule.

Proposed first slice: optional bounded analysis and processing to separate outputs.
Metadata saves, artwork publication and media replacement still require the
existing item/batch review. Later automatic publication needs a separately reviewed
permission contract; the implementation must not add it as an implied next stage.

## Action choices

All maintenance actions start off. Each rule selects one action in one library;
there is no “do everything” permission or automatic grant to future libraries.

| Action | What a saved opt-in permits | What remains manual |
| --- | --- | --- |
| Scan new arrivals | Read mapped media, probe and evaluate enabled standards; create findings | Expanding roots/library scope or changing standards |
| Local AI suggestions | Analyze selected permitted frames/context with the configured local provider; save suggestions | Accepting inferred titles, categories, cast or preferences; enabling a remote provider |
| Prepare processing | Create plans using an exact saved preset and effective standard; no subprocess execution | Queue/start approval unless the next action is separately enabled |
| Process separate outputs | Queue/run the selected upscale **or** encoding plan within rule and queue limits; validate output and put it in Ready for review | Accept/reject, publication, original cleanup or a different tool/model/preset |
| Metadata / cast changes | No standing write permission in this slice; suggestions only | Existing preview, explicit save/apply and provider readback |
| Artwork changes | No standing generation/publication permission in this slice | Reference/style review, exact paid quote and Generate approval, then artwork review/publication |

Rename, move, join, delete, retained-original cleanup, NFO/artwork sidecar export,
Plex collection-row publication, requests/purchases and infrastructure operations
remain explicit manual workflows. Rule evaluation cannot invoke their mutation
endpoints. Zero price does not imply permission to send an image to a provider.

## Rule approval record

A proposed record is separate from type standards and library overrides. Its
implementation shape is not an API commitment yet. Saving an inactive draft is
different from explicitly enabling its displayed action and limits.

| Required field | Contract |
| --- | --- |
| Identity and owner | Stable rule ID, revision, enabled state, operator identity when known, approval time; never invent identity for old records |
| Scope | Exact server/library identity, allowed mapped roots and exclusions; new roots and reconnects require identity/scope verification |
| Arrivals boundary | Explicit activation watermark; existing catalog excluded by default; an initial backfill needs a separately reviewed selection |
| Action | One allowlisted action with frozen tool/model/preset/options; processing action names do not authorize each other |
| Standard | Type revision, library override revision and effective-value digest; include resolver version so inherited changes invalidate correctly |
| Limits | Explicit finite items per run/day, output-byte allowance and minimum free space; provider-specific content/resource limits where applicable |
| Time | Named timezone, permitted execution window, quiet periods; no new external reads, AI calls or processing starts outside it |
| Exceptions | Excluded items/folders, unstable sources, unresolved identity, missing tools, missing fields or conflicting reservations |
| Recovery | Bounded read-only retry policy; no automatic mutating replay; owner-visible failure route and pause state |

The enable preview shows the action, library, effective settings, limits and which
steps remain manual. There is no silent numeric default that grants unlimited
work. Unknown values fail validation. Cross-rule limits aggregate for the same
library and machine; never multiply throughput by splitting rules.

## Eligibility and execution contract

1. Capture arrivals after activation from a completed authoritative scan. Wait for
   stable source identity; require existing source checks immediately before work.
   A reconnect/rematch or changed path alone is not a new arrival. Ambiguous matches
   become exceptions rather than another task.
2. Resolve exclusions, current rule/standard revisions, time window, available
   capacity and task reservations before creating an executable plan. Existing
   jobs and already-compliant media are skipped with reasons.
3. Approve an immutable plan only if the enabled standing permission covers its
   exact action and options. A proposal must not impersonate browser approval.
   Store the rule approval reference separately from item-level manual approval.
4. Reserve allowance and source ownership atomically with task creation. Deduplicate
   by library/media identity, source fingerprint, action/options, rule revision and
   effective-standard digest. Overlapping rules must also honor a source/action
   reservation, regardless of their distinct rule IDs.
5. Recheck eligibility immediately before starting an external action, including
   enabled state, revisions, source, window, allowance, connection and reservations.
   A pause/revision change wins over an unstarted job. Dispatch/disable must share
   an atomic boundary so disabling cannot race a newly starting task.
6. Preserve processing/publication safety and queue concurrency. Work on separate
   outputs; preserve originals even if a less strict standard exists. A validated
   output moves to review; success never cascades into publication or cleanup.

Repeated scans, reconnects and restart must not duplicate submitted work. A known
successful or active plan is reused/skipped. A failed attempt is retained; it is
not another eligible arrival. Changing a revision never bypasses an existing
reservation or quietly repeats previously successful work.

## Changes, quiet periods and failures

- Editing an action, scope, standard, effective inherited value, tool/preset,
  limits or time window creates a new rule revision needing explicit approval.
  Unknown fields/actions fail closed. Suggested preferences produce a reviewable
  diff only; dismissing or ignoring it leaves the rule unchanged.
- Invalidate unstarted plans on relevant changes. Active jobs finish their already
  approved separate-output step; changing a rule cannot broaden or kill that job.
  Existing validated results remain reviewable with their original provenance.
- Pause stops new rule dispatch; queue pause also takes precedence. Allow either
  one rule, a library or all maintenance to be paused. Disable revokes dispatch and
  invalidates queued rule approvals; resume/enable requires current-state checks.
  No maintenance recovery may start a queue paused manually by the operator.
  Reserve a conservative output allowance before processing and enforce its bound
  while writing; if a safe bound cannot be established, require manual review.
  Reaching the bound blocks the separate-output job; it never deletes originals.
- Quiet periods stop new starts; already-started processing may finish. They are
  not a promise of zero compute during those hours. Resolve named-zone wall-clock
  windows to instants; ambiguous/nonexistent boundaries use the more restrictive
  interval. Invalid timezone/window blocks dispatch. Reset daily counters using
  that rule's named calendar day; clock rollback must not restore spent allowance.
- Read-only transient connection checks may retry at most twice with backoff within
  the window. No automatic retry after a provider mutation, subprocess start or
  uncertain submission. A timeout means unknown, not failed-with-no-effect.
- Missing identity, stale approval, changed source, unavailable space/tool,
  exhausted budget or uncertain outcome becomes Needs attention with a readable
  reason. Pause the affected rule on uncertain state or a repeated identical
  failure; other independent libraries need not stop. Retry requires a fresh
  reviewed plan and reconciliation with any retained output/provider receipt.
- On restart, restore saved enable/pause state, reconcile reservations and receipts,
  and follow existing interrupted-work behavior. Do not replay interrupted work or
  automatically drain queued rules before current-state checks succeed.

## History and operator controls

Show rule name/revision, action, library, queued/running/waiting/review/blocked
counts, remaining allowance and next eligible window. Offer Pause, Disable and
Review exceptions at the rule entry. These controls need an approved Configuration
prototype before their implementation; this document is the behavioral contract.

Events use `rule` for rule-initiated work and `operator` for approval/override.
Record AI assistance separately in provenance; a rule calling AI keeps `rule` as
its initiator. Reserve `ai` for an independently AI-initiated suggestion, which
never grants execution permission. Keep original initiator plus rule/approval references through
execution, review and recovery; distinguish who proposed from who approved.
Record eligibility decisions, skips, starts, results, quota use, pause/revision and
failures in existing transactional history. A failed audit write prevents a new
mutation; do not report success without its durable outcome. Credentials and
provider payloads stay out of events; private source/receipt evidence stays in
private state, with sanitized public engineering evidence only.

## Review scenarios and acceptance

#118 must demonstrate with synthetic fixtures:

- Disabled rules and saved standards cause no execution; inferred preferences
  cannot enable rules. Enabling processing never grants publication or paid art.
- Duplicate scans, overlapping rules, concurrent claims, rematches and restart
  create at most one active source/action plan and preserve allowance accounting.
- Inherited revision/source changes, changed roots, pause/disable races, quiet
  boundaries and exhausted shared limits prevent unapproved starts.
- Partial/uncertain outcomes do not replay; retained output returns for review.
  Manual queue pause is respected and original files remain unchanged.
- Events distinguish proposal, standing approval, rule execution and manual
  publication; unknown initiators remain unknown. Failure messages offer the
  supported next action without credentials or automatic retry of mutations.

Operator acceptance requested: the first-slice action boundary and manual actions,
required per-rule scope/limits/windows, and pause/retry behavior above. Until that
review is recorded on #117, this is a proposal and #118 remains blocked. No standing
permission is granted by accepting a design; enabling a specific rule is separate.
