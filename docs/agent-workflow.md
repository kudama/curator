# Shared Curator delivery workflow

Recorded 2026-11-20 (America/Los_Angeles). Applies to Codex, Claude and bounded
Forge workers. This is coordination infrastructure, not an execution grant.

## Work ledger

- [Curator v2 milestone](https://github.com/kudama/curator/milestone/1)
- [Readiness and dependency checklist](https://github.com/kudama/curator/issues/102)
- [Implementation board](https://github.com/users/kudama/projects/1)
- [Existing Curator outcome](https://github.com/kudama/personal-ai-platform/issues/9)
  on the [build requests board](https://github.com/users/kudama/projects/2).

The outcome links the implementation ledger; it does not duplicate every child
issue. An issue's acceptance criteria and latest evidence define its state. Coordination
is a manual issue/board process, not a runtime lock or automatic dispatcher.
Worker tool grants are enforced by the Forge controller, never by issue prose.

| Issue label | Implementation board | Meaning |
| --- | --- | --- |
| `work:ready` | Ready | Bounded next step is claimable; no automatic pickup |
| `work:in-progress` | In progress | One recorded executor owns active work |
| `work:review` | Review | PR, prototype or acceptance awaits another reviewer |
| `work:blocked` | Blocked | Named prerequisite/decision prevents the next step |
| Closed, completed | Done | This issue's defined acceptance is met and evidenced |

Keep exactly one open work-state label. Use one `executor:codex`,
`executor:claude` or `executor:forge` only while claimed; name a Forge worker and
controller in the claim. GitHub assignees represent real accounts, not invented
agent usernames. `phase:*` distinguishes design, implementation, validation and
coordination. A ready design task does not make its dependent implementation ready.

## Claim, handoff and parallel work

Before edits, inspect the current issue, comments, PRs and branch. Post a claim:

```
Executor: Codex | Claude | Forge worker + controller
Claimed: ISO date/time with timezone
Starting v2 SHA:
Branch:
File scope / shared-file reservations:
Next deliverable and checks:
Independent reviewer: unassigned | different agent
```

Set the executor and In progress state on both issue and board, then re-read the
issue for a competing claim. Labels/comments are not atomic locks. The controller
serializes assignments when several sessions are available. If claims conflict,
stop overlapping edits and resolve ownership; do not assume the last label wins.

Do not work on another executor's dirty checkout. Use a suitable isolated checkout
when concurrent work requires it. Keep one implementation issue per feature PR.
Coordinate edits to service.py, migrations, state contracts and shared frontend
files explicitly. Prefer independent design/data-contract work while a shared
implementation is occupied. New dependencies or architecture changes require
senior review before implementation.

A handoff records the branch, exact SHA, changed files, checks, remaining work,
blocker and next owner. Do not mark a worker proposal complete before the controller
has reviewed it. Release a claim explicitly; do not silently replace an executor.

## PR and independent review

Feature PRs target v2 and link the covered issue and approved specification/render.
Use the PR template. The author provides the problem, final behavior, relevant
checks and limitations. A different agent reviews the exact head SHA and records
findings and verification. New commits invalidate that review; request re-review.
Code changes require relevant existing checks and meaningful regression coverage.
Documentation-only changes need link/structure/scope verification, not invented tests.

GitHub currently has one collaborator account. PRs/checks can be enforced, but
GitHub cannot distinguish Codex/Claude/Forge when they share that account. Different
agent review is therefore an explicit, auditable process requirement, not a claim
of native different-account enforcement. Do not require a native approval that
cannot be supplied; separate agent identities remain platform work, not a new
credential grant in this setup. Never fabricate an approval or reviewer.

Require passing tests (3.11), tests (3.13), python-style and resolved review
conversations. Do not bypass failed checks. A merged PR is implementation evidence;
user-facing acceptance and deployment can still be pending. Keep the issue in
Review until its own criteria are met. GitHub closing keywords may not close
issues on a merge into non-default v2; reconcile them deliberately.

## Integration and release

The v2 readiness matrix records required scope, independent review, acceptance
and remaining work. Unmerged proposals do not silently enlarge the milestone.
New scope or a deferral needs an explicit operator decision in the ledger.

A v2-to-main release PR requires #120's complete checklist and #102's accepted
scope, not just a smoke check. Selected stable fixes can be backported with a
separate reviewed PR without claiming v2 complete. A feature branch merge must
not revert another agent's work while resolving conflicts.

Deployment is a separate authorized operation against an exact candidate SHA.
Privately verify service/queue state, preserve required backups, protect active
work and validate the deployed revision. Honor current holds. Never infer approval
to stop a job, spend credits, write real media or grant access from a milestone.
Keep private operational records outside public GitHub; only post sanitized,
explicitly permitted release evidence.

## Initial parallel candidates

- #104: Home/navigation prototype.
- #105: standards/override Configuration prototype.
- #106: NFO/artwork package-review prototype.
- #112 and #114: discovery/provider and Seer contracts.
- #117: explicit maintenance permissions/policy.
- #111: history recovery using existing approved flows.

These are unclaimed, not assigned. Check current labels and claims before starting.
Existing #70/#92/#97 have their own source/acceptance constraints. Do not run
parallel PRs against shared files without a file-scope agreement.
