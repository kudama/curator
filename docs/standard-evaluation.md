# Effective standards in scans and completion

Implementation for #107; compatibility contract review remains #92. Engineering
review and the operator's final review are separate from release acceptance #120.

Scans evaluate the current type standard plus library overrides inside the same
transaction as findings reconciliation. Changing standards during a probe cannot
commit findings from the earlier standard. No work is started by changing standards.

`state().assets[].completion` describes the five dimensions with `met`,
`needs_attention`, `unknown` or `disabled`, their missing facts, the observed scan
time and exact effective-standard identity. `state().completion[library]` provides
counts by dimension and overall. Empty libraries are unassessed, not 100% complete.
Unavailable/unscanned sources and failed technical analysis remain unknown.

- Metadata uses the configured fields, including valid year/date and nonempty
  categories/collections; it does not demand every possible metadata field.
- Cast uses named current credits (catalog credits or known people). Empty or
  unnamed credits require human review in Metadata. It does not infer people from
  imagery or certify that everyone appearing has been identified.
- Artwork checks the selected Plex poster/background/logo paths, including the
  current `Image` array. A selected path is an observation, not an image decode or
  independent client-display acceptance. It never silently uses an old draft.
- Upscaling uses aspect-aware class goals: long/short edges 1920/720 for 1080,
  3840/1440 for 2160; cinematic and portrait content keep their shape. Optional
  upscales do not count as unfinished. The existing 4096/2160 processing ceiling
  and explicit processing settings remain; a goal does not choose a Topaz scale.
- Encoding follows per-library thresholds or current global thresholds. The
  legacy `preserve_originals` setting means skip space-saving suggestions, not
  permission to delete originals. Duration/bitrate absence remains unknown unless
  this suggestion is explicitly disabled. A required upscale can also satisfy
  encoding in one plan; both unmet facts remain visible.

Findings retain the standard's type/revisions, parent/effective digests and resolved
encoding thresholds. Changing that identity advances only an unsubmitted
recommendation's review version, preserving its editable draft. Queue admission
checks it again before and inside its final transaction. Submitted plans, approvals,
retained output and receipts are never rewritten by a standards change.
A newly required finding after completion creates a separate unapproved attempt
linked to the completed task. Repeated scans reuse that current attempt; the old
plan and retained-output/publication receipts stay available unchanged. Final scan
evaluation reads both current standards and global thresholds in its commit
transaction, even when either changed during the probe.

## Legacy profile and Plex-agent compatibility

Schema 5 has the normal private pre-migration SQLite backup and transactional bump.
It records `observed_kind` from raw Plex fields and freezes `standard_kind` at an
existing saved kind. A home TV library remains TV. On a profile/type disagreement,
the profile's built-in standard fills only absent override fields whose inherited
value was not customized. Explicit library overrides and customized type fields
win. The profile and all task/approval/output records remain unchanged. Reopening
current state is idempotent. The old profile remains available to existing branding
and media UI; scan behavior now follows the explicit standard.

First connections may suggest Other Videos for a movie section with normalized
`Plex Video Files` or `Plex Video Files Scanner`; raw observation remains distinct.
Reconnect/location refresh changes observation only. It cannot silently change the
chosen type, overrides or their revisions when an NFO/custom agent is installed.

Settings → Library standards → library → **Change standard type** reviews both
parents and effective before/after fields while preserving overrides. The atomic
save validates library revision and both reviewed parent identities. Concurrent
changes keep the choice visible, refuse saving, and require explicit reload/review.
The new route is `POST /api/library/standard-kind` with the library, revision,
`before_kind`, `before_type_revision`, `before_type_digest`, `kind`, `type_revision`
and `type_digest`; omitted guards are refused. No-op saves leave history unchanged.

Synthetic browser evidence: [desktop](designs/v2-standard-type-20261122/desktop.png),
[phone](designs/v2-standard-type-20261122/phone.png). All three themes, no overflow,
explicit save/cancel, parent-conflict refusal and Settings-draft retention checked.
No real catalogue, account, provider call or media mutation was used.
