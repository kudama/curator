# Metadata and Artwork delivery — 2026-11-18

Implementation branch: `feat/metadata-artwork-managers-20261118`. This record describes this delivery slice; the feature lock remains the governing scope. The user's later instruction to implement supersedes the earlier ticketing-only hold.

## Implemented in this slice

- Independent Metadata / Artwork scan findings. A one-time cached-data migration splits untouched recommendations while preserving existing plans, approvals, active jobs and history.
- Single and task-group bulk Metadata open directly. Only checked fields change; Categories and Collections support explicit new names and Add / Replace / Clear. Cast names, roles and order are opt-in; matching portraits and existing Plex labels are preserved. Preview records exact before/after values, source/task versions and destination identity. Approval queues the reviewed changes without starting processing.
- Artwork workspace: media items, collections, and entry points to the existing folder and portrait tools. Item editors show Cover, Background, Square art and Logo. Cover formats are explicit, with home-video 16:9 and commercial 2:3 defaults. Collection posters stay 2:3, backgrounds 16:9, squares 1:1. Logos retain original proportions and require real PNG transparency before publication.
- Multi-selection keeps covers/squares/logos individual. Shared backgrounds require explicit opt-in and list the exact affected targets in current-versus-proposed review. Imported/cropped drafts use the existing durable publication queue and Plex readback checks. Collection identity is separate from member media and scanned assets.
- Simple Generate setup with style, explicit reference selection and collapsed advanced settings. Closing Generate restores the parent artwork draft. Quotes are invalidated when settings change; no automatic generation from selection, preview or scan.
- Settings: per-batch and monthly Curator Gems allowances, plus artwork archive path. Reservations are atomic at authorization; uncertain submissions retain their reservation, known charges remain counted, and only confirmed refunds release spent Gems. These are Curator-local limits, not account-wide provider caps.
- Optional append-only archive through the existing shared file-operation queue (maximum four): `Movies/{Posters,Backgrounds,Squares,Logos}`, `Collections/{Posters,Backgrounds,Squares,Logos}`, flat `Cast/`. Files and provenance manifests are retained; retries are idempotent, writes become visible only when complete, and old archives remain after changing paths. Archive failure blocks publication rather than losing the candidate.

## Acceptance evidence

- 445 Python tests pass, three optional skips; 85 JavaScript behavior checks pass. New coverage includes stale/atomic metadata approval, preserved cast thumbnails/labels, collection isolation, image dimensions/alpha, quote invalidation, monthly/batch reservations, unknown billing, append-only archives, interrupted copies and unavailable paths.
- Synthetic browser fixture: bulk metadata preview→queue; imported art→current/proposed→verified fixture publication; collection-owned editor; exact three-item shared-background preview; Generate close→parent draft; Classic/Cyberpunk and narrow layout. No production Plex/media mutation or paid generation was used for these checks.
- Native Forge analyst `d9dcb78f87fe41119cdfe15b0ec141b1` failed `tool_denied` on its initial source read despite ready health. No worker patch was accepted. Senior implementation and review performed directly; reliability evidence tracked under Forge #76.

## Still open — not acceptance claims

- Authenticated Mage estimate/account schemas and billing behavior: Foundry currently has no Mage key configured. Nondefault/reference quotes use a fixed-host, read-only MCP bridge restricted to `estimate_cost`, `get_account`, `get_model`; unsupported schemas/prices fail closed. Generation remains disabled without a usable price and explicit approval. Provider references: [MCP](https://docs.mage.space/api/mcp), [billing](https://docs.mage.space/api/billing).
- Dedicated People portrait view, opened folder/shared-background view, full style-guide manager and dedicated logo editor retain their visual approval gates. Existing folder/portrait tools remain available. Do not describe their old screens as the new approved managers.
- Native portrait publication remains explicitly unverified/manual. Collection square/logo transport retains existing native endpoints plus destination identity/readback checks; this synthetic run does not establish support on a live Plex server.
- Transparent logo creation/cleanup and strict portrait normalization are not established by importing an opaque generation result. Opaque logos cannot be published through the artwork gate.

Production rollout and exact revision/backup evidence belong in Curator #56 after deployment verification, not inferred from tests or merge status.
