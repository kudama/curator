# Curator v2 readiness ledger

Audit: 2026-11-20 (America/Los_Angeles), v2 ecd1ff75a3a5f910068fcc7e7f80ef28a6aadd2f.
Source: [product direction](curator-v2.md), [standards](https://github.com/kudama/curator/blob/v2/docs/curator-v2-standards.md),
[history](https://github.com/kudama/curator/blob/v2/docs/curator-v2-history.md), current source and linked issues/PRs.

**Status: incomplete.** The theme, standards model/API, schema/history foundations
and focused fixes are merged. Standards are not yet consumed by scans. New Home,
main navigation, standards Configuration, discovery and maintenance remain work.
This audit is not fresh runtime acceptance or deployment certification.

Tracking: [milestone](https://github.com/kudama/curator/milestone/1),
[umbrella #102](https://github.com/kudama/curator/issues/102),
[release gate #120](https://github.com/kudama/curator/issues/120),
[shared workflow](agent-workflow.md). Current issue/PR evidence takes precedence
when this dated snapshot becomes stale. Update this file after meaningful decisions.

## Requirement coverage

| Requirement | Implemented evidence | Remaining work / gate |
| --- | --- | --- |
| Optional Plex/Tautulli appearance | #84; previous interaction slice #83 | Preserve and verify in release matrix #120 |
| Home / Library Manager / History / Configuration navigation | Existing workbench remains usable | Prototype #104; implementation #108; explicit render approval |
| Home arrivals, health, work accomplished and decisions | Catalog/history sources exist | #110, after navigation and standards evaluation |
| Type standards, library overrides and schema upgrades | #85 and poster correction #93 | Configuration prototype #105, UI #109, scan/completion #107 |
| Legacy profile intent and personal media after NFO-agent changes | Existing profile preserved; investigation #92 | #92 decision before #107 migration; no silent reclassification |
| Job and Curator history, filters, timeline, attribution | #86 | Supported recovery entry points #111; rule initiators depend on automation |
| Explainable discovery and operator feedback | Candidate signals only | Source/permission contract #112; implementation #113 |
| Seer requests that have landed | Interface/account selection unverified | Contract #114; read-only integration #115 |
| Curator-selected Plex collections / recommendation rows | Documented product direction only | #116 after recommendation contract; explicit preview/publication |
| Reusable preferences and authorized new-arrival maintenance | Standards do not grant execution permission | Policy #117; bounded implementation #118 |
| Compact Curator summary in Homebase | Product requirement, not delivered evidence | #119; keep overall dashboard in Homebase |
| One-time NFO export with required local artwork | #88 parent, specification PR #89 | Prototype #106; #90 and #91 as one complete package; #92 compatibility |
| Rename/rematch metadata and original-art preservation | Preview-cache fix alone is insufficient | Existing #70; critical preservation acceptance in #120 |
| Below-target upscale recovery choice | Prevention ceiling fix #99 addresses a different case | Existing #97: explicit resolution-only acceptance or reviewed 4x rerun |
| Worker refill and processing guard regressions | #82/#96, #98/#99 | Include repeat/drained-worker and ceiling cases in #120 |
| Cast canonical portrait re-add | #95 implements comparison correction | #94 remains for independent/appropriate client acceptance; do not conflate backend readback with display |
| Artwork download spacing and logo auto-preview | #100 and #101 | Preserve under three-theme/editor acceptance #120 |
| Full release | No full v2 completion claimed | #120 and #102 must be accepted before a full v2-to-main release |

Merged means the code exists at the cited revision. It does not by itself mean
all user/client/provider acceptance has passed. #120 supplies the cross-feature
acceptance gate; no v2-complete label is inferred from closed PRs.

## Existing proposals and scope boundaries

- PR #89 documents the already requested NFO/local-artwork package and remains in
  Review. It is a specification, not an implemented exporter. Reuse #88–#92.
- PR #87 describes operator-selected polished previews/trailers independently of
  the broader v2 specification. Keep it visible as a separate proposal; do not
  silently make it a v2 release blocker or claim it delivered. Adding it to the
  milestone needs an explicit scope decision and bounded implementation issues.
- Candidate ratings/social/trend providers, Seer interfaces and paid access remain
  choices to verify in #112/#114. No source subscription or new access is selected
  by creating a task.
- Broad pre-v2 tracking issues (#53–#56 and deployment acceptance #12) retain their
  history. Link and audit relevant criteria; do not close them merely because the
  new milestone exists. Do not duplicate #70/#88/#90/#91/#92/#94/#97.

## Release gate

- [ ] All confirmed rows above have accepted evidence, or an operator-approved
      explicit deferral with impact recorded. Resolve required external decisions.
- [ ] New workflows have approved prototypes; touched existing workflows retain
      drafts, library context, keyboard access and three-theme/narrow-screen behavior.
- [ ] PRs are independently reviewed at their final heads and required CI passes
      on the combined candidate. Resolve shared-file conflicts without losing work.
- [ ] Migration/backup/restore and incompatible downgrade behavior are verified
      against disposable state; immutable approvals and original media stay safe.
- [ ] Standards drive findings and completion, with legacy/NFO intent preserved.
- [ ] Queue refill, per-type limits, pause, filtering, stale approvals, media/cast/art
      publication, collisions and supported recovery pass meaningful regression checks.
- [ ] NFO plus every available supported image round-trips on an authorized disposable
      library; missing/unsupported fields and partial results remain explicit.
- [ ] Selected provider/client integrations have separately authorized acceptance.
      Unavailable capabilities are reported rather than represented as working.
- [ ] Review an exact v2-to-main release candidate and a separate authorized
      deployment/rollback plan. Record safe public release evidence separately from
      private operational details. A startup smoke check alone does not meet this gate.

No deadline, new agent assignment, feature execution, live media operation or
restart is authorized by this ledger. Ready tasks can be claimed under the shared
workflow; deployment follows the operator's current instructions.
