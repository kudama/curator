# Contributing

Keep changes focused and use the existing Python standard-library and plain JavaScript conventions. Read the architecture before changing processing, approval, publication, or recovery behavior. Discuss new dependencies and architectural changes before introducing them.

Run the checks in the README. Include regression coverage for meaningful behavior changes, especially stale approvals, changed sources, interrupted jobs, collisions, and partial provider writes. Use synthetic media and temporary state. Never commit Plex tokens, private paths, catalogs, watch history, personal media, or live task receipts.

Raise `curator.errors.UserError` for messages written for the person using Curator; only those are shown in the app. Any other exception, including a standard-library `ValueError`, is logged to `logs/curator.log` and shown as a generic message.

Bug reports should describe the expected and observed behavior, macOS/Python/tool versions, task phase, and a sanitized reproduction. Use generated test-pattern media where possible. Do not attach the runtime database or settings. Pull requests should explain the problem, resulting behavior, and validation.

Contributions are provided under the repository's MIT license.

## Shared v2 work

Read [AGENTS.md](AGENTS.md), the [shared workflow](docs/agent-workflow.md) and
[v2 readiness ledger](docs/v2-readiness.md) before claiming work. Use the Curator v2
milestone, existing shared boards and linked issues; keep one executor per task,
independent review evidence and separate acceptance/deployment status.
