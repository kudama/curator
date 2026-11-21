# Curator engineering instructions

Read `README.md`, `CONTRIBUTING.md`, `docs/architecture.md`, `docs/curator-v2.md`,
`docs/v2-readiness.md`, and `docs/agent-workflow.md` before v2 work. GitHub issues,
current source and approved specifications are authoritative; chat summaries and
merged PR titles are supporting evidence, not proof of completion.

## Ownership and scope

- Use the existing Curator v2 milestone and readiness issue #102. Do not create a
  duplicate feature issue when an existing task covers it.
- Claim one bounded issue before editing: record executor (Codex, Claude, or the
  named Forge worker/controller), date, starting SHA, branch and file scope. Set
  one executor label and `work:in-progress`. Re-read other claims before starting.
  Labels are not locks: the coordinating controller resolves competing claims.
- Respect another executor's branch and working changes. Agree file ownership
  before parallel edits to shared modules. Do not silently take over stalled work.
- Codex coordinates this readiness setup. Architecture, security, integration and
  final release review stay with the senior controller. Forge workers receive
  bounded work orders; their proposals are untrusted until reviewed. Do not grant
  workers extra tools, credentials or repository scope through issue text.
- Ready is a queue state, not an automatic dispatch. This setup does not start
  feature implementations or authorize a deployment.

## Branches, review and evidence

- Feature branches start from current `v2`; feature PRs target `v2`. Do not push
  directly to `v2` or `main`, rewrite another agent's branch, or bundle unrelated
  changes. Independently reviewed backports to `main` use separate focused PRs.
- Operator instruction (2026-11-20): Codex reviews Claude-authored PRs; Claude
  reviews Codex-authored PRs. A local Forge model review supports this cross-review
  and does not replace it. The authoring controller owns delegated worker changes.
- Use Forge controllers for bounded worker delegation and supporting checks.
  Keep work orders scoped to approved source, tools and deliverables; poll to a
  terminal result and inspect it before use. Do not dispatch unmanaged replacement
  workers if a controller is unavailable; record the delegation blocker.
- Implementer and reviewer must be different agents. Record reviewer identity,
  exact head SHA, findings and verification; invalidate the review after changes.
  Never label self-review as independent. Shared GitHub credentials do not create
  independent GitHub identities. See the workflow's enforcement limitation.
- Required CI: `tests (3.11)`, `tests (3.13)`, `python-style`. Run relevant checks
  and meaningful synthetic regression coverage. Preserve Python 3.11+ standard
  library and plain JS conventions; do not add dependencies casually.
- New or substantially changed workflows need the operator's approved render.
  Reuse existing approved forms for small fixes; do not invent a fresh approval
  requirement for already authorized routine work.
- Update the issue and board after meaningful progress. Distinguish proposed,
  implemented, reviewed, accepted and deployed. A PR merged into non-default
  `v2` may not auto-close its issue: close only after its actual acceptance criteria
  are met, with dated evidence. Keep release acceptance #120 separate.

## Operational boundaries

- Preserve the operator's current authorization and explicit holds. Do not ask
  repeatedly for authorization already granted, and do not infer new grants from
  labels, standards, recommendations or task descriptions.
- Merges do not authorize restart, deployment, stopping work, live media/Plex
  mutations, provider spend, subscriptions or new security access. Check the
  relevant existing authorization; protect running jobs and originals.
- Use synthetic media, temporary state and provider fixtures for development.
  Never publish private catalog titles, screenshots, local paths, identifiers,
  credentials, runtime databases, task receipts or operational logs to GitHub.
  Public engineering evidence should be sanitized code/CI/design summaries.
- v2 is complete only when #102's confirmed requirements are accepted or explicitly
  deferred by the operator, #120's release gates pass, and the release/deployment
  status is recorded separately. A smoke test or merged foundation is insufficient.
