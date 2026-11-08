# Contributing

Keep changes focused and use the existing Python standard-library and plain JavaScript conventions. Read the architecture before changing processing, approval, publication, or recovery behavior. Discuss new dependencies and architectural changes before introducing them.

Run the checks in the README. Include regression coverage for meaningful behavior changes, especially stale approvals, changed sources, interrupted jobs, collisions, and partial provider writes. Use synthetic media and temporary state. Never commit Plex tokens, private paths, catalogs, watch history, personal media, or live task receipts.

Bug reports should describe the expected and observed behavior, macOS/Python/tool versions, task phase, and a sanitized reproduction. Use generated test-pattern media where possible. Do not attach the runtime database or settings. Pull requests should explain the problem, resulting behavior, and validation.

Contributions are provided under the repository's MIT license.
