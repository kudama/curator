# Standards editor implementation — 2026-11-22

Issue #109, following the approved #105 / PR #127 design and inheritance contract.
Synthetic local DEV libraries only; no personal catalog, provider credentials or live writes.

The editor is reached from **Settings → Library standards → Manage library standards**.
This bounded implementation keeps the existing Settings form underneath, preserving
its unsaved inputs. `openStandardsEditor({kind, library})` is the entry point for the
Configuration shell in #108. Navigation and scan enforcement remain separate work.

- [Desktop](desktop.png) and [390 px phone](phone.png): scrollable fields/sections;
  review actions remain visible, no horizontal page/body overflow. All three themes verified.
- Full type values, individual library inheritance/overrides, reset-to-inherited and
  reset-to-defaults change only the draft. Disabled dimensions remain editable.
- Review shows before/after and affected libraries or inheritance source. No-op saves
  do not call the browser save API; server no-ops preserve revision and history too.
- The library write validates its own revision and the reviewed parent kind/revision/
  SHA-256 digest atomically with normalization and write. Revision-zero default changes
  and a changed library kind are refused. GET returns a coherent snapshot.
- Conflicts and errors preserve edits; explicit reload discards only with confirmation.
  Invalid thresholds block Review. Saving never starts queues or changes approvals.
- Public browser override saves require the whole parent guard. Existing internal
  callers retain the explicitly unguarded Python compatibility path; no browser bypass.

Verification: 632 Python tests run successfully (3 existing optional skips), including
8 added API/concurrency/no-op cases; 151 JavaScript tests; 18 Chromium workflow checks,
1440/390 layout and visible-action checks, Ruff and whitespace checks. Existing History
fixture now performs a real standard change instead of expecting an event from a no-op.

Forge implementer task returned `tool_denied` with no patch; no grants were expanded.
A bounded Forge test-design task completed; its suggestions were independently checked.
Implemented locally, pending exact-head independent review and hosted CI. Not deployed;
this evidence does not complete #107 standards-driven findings or full v2 acceptance.
