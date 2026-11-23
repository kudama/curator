# Local trailer publication

Implementation #143 adds a separate **Publish to Plex** action to a completed
preview. Review the exact movie/edition, candidate digest and Plex destination,
then **Approve & queue**. Selecting **Use in Curator** alone never writes media.
Approval closes the panel and creates a durable shared File operations job; it
does not resume a paused queue. Reopen the preview to inspect its publication
receipt and check association after Plex's scheduled processing.

Supported layout: a single movie file/version inside its own mapped movie folder;
each edition must have its own folder. Episodes, multiple parts/versions and
shared/root movie folders are refused. The additive filename is
`<movie>-Curator-<digest prefix>-trailer.mp4`. Existing trailers are listed and
retained. Destination collisions refuse the write, including dangling symlinks.
There is no overwrite, movie replacement, agent change or forced Plex refresh.

The destination review freezes server/library/item/edition and normalized canonical/external movie GUIDs, mapped source and
parent-directory identity, supplied Plex library-section identity, source/candidate hashes and task version. Approval is
idempotent and transactionally creates the shared queue record. Execution
rechecks these guards, exclusively stages beside the movie, flushes and reads
back its SHA256, installs without replacement, then verifies installed bytes.
Failed or interrupted attempted writes retain their staging and receipt for
inspection, never automatic replay. Shared file-operation recovery also prevents
replaying waiting/running work after restart. A fresh separately reviewed approval can
supersede only a terminal failed/interrupted/cancelled file job whose durable
publication still says queued and has no destination or deterministic staging
file/symlink. The old receipt becomes abandoned_unattempted in the same approval
transaction; its errors/history remain and old payload replay is refused. Active,
attempted, saved or uncertain receipts never release automatically.

**Saved locally**, **Plex association pending**, and **verified** are distinct.
Read-only association checks require Plex to expose a trailer extra with this
exact movie-side path. Missing extras/path details stay pending; a successful
copy is never rolled back because Plex has not discovered it. Plex settings,
scanner/metadata timing and client presentation need separate authorized
acceptance; a pending association may need the operator's later metadata refresh.

Conventions verified against [Plex's movie extras documentation](https://support.plex.tv/articles/local-files-for-trailers-and-extras/)
on 2026-11-22. The current Plex Movie agent requires Use local Assets; this action
does not silently enable it. Plex documents edition-specific directories and warns
that metadata refresh may be necessary for newly added extras.

Development evidence: disposable synthetic candidate/media fixtures verify
explicit separate approval, paused queues, exact byte retention, collisions,
source/candidate/edition changes, concurrent approvals, interrupted installation
and read-only exact-path association. Browser checks cover desktop/narrow layout,
keyboard approval, close-on-approval and a paused shared queue. These checks do
not claim real-library/NAS/Plex-client acceptance (#145).
