# Manual NFO and selected artwork export

File management → **Generate NFO files** prepares an operator-run package for
selected files, an exact folder or the current library. Filters select all,
missing NFO, new/changed metadata, or previous failed/partial exports. A preview
is bounded to 2,000 files; split larger libraries by folder. Preparation reads
current sources and destinations without writing beside media.

Review each item's proposed UTF-8 XML, current supported metadata, exact paths,
source/destination SHA-256 hashes, formats and omissions. Current saved Curator
metadata must agree with a fresh Plex item. A conflict, changed mapping/file,
unavailable mount, wrong item identity, multipart or TV item is blocked rather
than exporting stale values or inventing a movie identity.

The default creates missing filename-matched movie NFOs and selected image files.
It never overwrites another tool's NFO or an existing image. A previously verified
Curator-written NFO can be updated only with that item's separate approval; old
bytes are retained and unknown XML elements/catalog identifiers survive safe
updates. Unsafe XML declarations and conflicting identifiers are refused.

Artwork comes from the current Plex selection (or explicitly seeded DEV artwork),
never a retained unapproved draft. Supported JPEG/PNG bytes retain their actual
format and extension. Every available cover/background/square/logo is included
or has a visible conflict. Generic names are supported only in an unambiguous
single-video folder; a shared folder can export its filename-matched NFO while
artwork remains blocked. Alternate image extensions are treated as conflicts.
Landscape covers are retained unchanged and flagged, never stretched or cropped.

Cast names, roles and order are exported. Portrait references whose durable,
credential-free re-import has not been verified are explicitly omitted; existing
Plex/Curator portraits stay intact. Collection relationships, labels, personal
ratings and unverified identifiers are reported as omissions. This package is
not a certified complete Plex backup or proof that a particular agent imports
every field. No scanner/agent setting, Plex refresh, provider call or generation
is part of this export.

**Approve & queue export** closes the panel and creates one durable File operations
job. Admission does not resume a paused queue. Details opens the pinned manifest.
The queue can pause safely between items; resuming the same job skips completed
items. Restart interrupts/holds work and never replays writes automatically.

Recent exports under Generate NFO files retains per-file verified outcomes,
missing images, partial failures and retained-original locations. Prepare retry
builds a fresh review for failed/partial/interrupted remaining items. Completed
files stay untouched on a safe rerun. Filesystems without a supported exclusive
install fail explicitly; there is no clobbering fallback. An interrupted approved
update can leave the destination absent with its original in the named recovery
directory; inspect that receipt before preparing another export.
