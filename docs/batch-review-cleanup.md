# Batch review, encoding and retained originals

## Select and review

Group the library by **Task type** to select all matching tasks in a group, including files outside the visible scroll area. Individual checkboxes let you adjust the selection. Search/filter scope is reflected in the group; selection itself does not approve anything. Changed versions and finished/missing tasks are removed from group selection on refresh.

Selected completed upscale/encoding jobs also offer **Accept & Publish Selected**
and **Reject Selected** directly in Queue and task groups. Bulk acceptance warns
once with the exact selected count and library scope that outputs may be
published without individual inspection. Confirming prepares comparisons and
runs normal per-file publication checks; no second publication popup is needed.
Changed or failed items are reported and skipped. Bulk rejection returns eligible
tasks to suggestions with settings retained, approval cleared and version
advanced. Generated files stay on disk and their references remain in the audit;
they cannot be published through the rejected approval. Individual upscale and
encoding rejection uses the same reset behavior. Published and stale tasks are
never reset. Multipart joins and artwork retain their separate review workflows.

For upscale/optimization results, choose **Review selected**. Curator prepares existing source/output comparisons sequentially and keeps a durable batch receipt. Browse comparisons in pages of20 files. **Accept & publish N results** requires a separate confirmation for the exact prepared count. Each publication uses the existing per-task source/output/hash/original-retention checks, one at a time. Failures are reported per file. **Stop after current file** does not interrupt an installation already in progress. **Batch reviews** reopens recent receipts after closing/reloading the page. Restarted batches are interrupted and never automatically replayed; reselect remaining results deliberately.

## Output encoding

Settings now offer quality-based Topaz encoding or an explicit bitrate target. The existing quality65 remains the default. Bitrate mode sends average/maxrate/buffer targets to VideoToolbox; encoder behavior and copied audio/subtitles mean this is not an exact final-file-size guarantee. Tool settings are captured when a task is approved; changing settings does not rewrite existing queued approvals.

Review shows original/output size, approximate total Mbps, the approved mode and a warning when an output is more than25% larger. The1080p/4K Mbps thresholds still suggest review; they are not encoder caps. Compare representative output quality before adopting a lower target for a large library. This release does not automatically re-encode existing results.

## Cleanup

**Clean up originals** offers only retained filename-old.ext originals identified by completed publication receipts. Unrelated similarly named files, missing/changed mappings, symlinks, unverified publications and assets with active/waiting jobs are excluded. The preview shows exact paths and reclaimable bytes; nothing is selected or deleted automatically.

Select backups and explicitly confirm permanent deletion. Curator reserves the affected asset, verifies current replacement and original hashes, stages the original through a same-volume exclusive rename, verifies again and deletes only that staged original. Changed or uncertain files are retained and reported. On NAS shares without no-overwrite rename support, Curator creates an exclusive recovery copy, verifies it and rechecks both media files before removing the original. This requires temporary space and extra I/O; copy failures preserve the original and recovery marker. Cleanup does not remove processed-output caches or any published video. Start cleanup from the library. Active cleanup progress appears in Queue; completed receipts appear in History. Unrelated queue work can run while cleanup reserves only its current media file. Failed deletion counts and filesystem errors remain visible.

Interrupted staging retains a recovery marker. Open a fresh cleanup preview and use **Restore retained original** where offered; restoration refuses destination collisions. Inspect uncertain files if restoration cannot verify them. Running cleanup jobs remain visible in Queue with checked/deleted/failed counts and Details; completed receipts appear in History. The cleanup launcher appears only in the library. Cleanup reserves its current file but does not claim the video queue, so unrelated files can proceed. Completed cleanup receipts also remain available in the preview. Permanently deleted originals cannot be restored by Curator; retain independent backups where required. No cleanup runs on a timer, scan or startup.

## Deployment

Backend feature capabilities gate the new controls. A refreshed static page can run against an older backend with new backend-dependent actions disabled. Deploy the backend only while idle and restart explicitly. This feature set introduces private receipt records in the existing settings store, with no new package dependency or database schema migration.
