# Shared file operations

Publication copies, retained-original cleanup, cleanup recovery, stream-copy
repair, file moves and rename restoration share one durable file-operation
queue across all libraries. Its default and maximum is **four** simultaneous
operations. Processing limits can lower it to 1–3.

Accept & publish queues the approved installation. Cleanup keeps its existing
exact-count deletion confirmation before queuing. Queue shows waiting/running
file operations and offers Resume and Pause after current. Global Run/Pause
also includes this queue. A claimed installation/deletion finishes before pause;
copy and deletion stages are not interrupted midway through their commit.

Each operation retains its existing source/version/hash, mapping, collision,
original-retention and recovery checks. Related source operations remain
reserved or serialized; sharing slots does not authorize a file change that
failed those checks. A cleanup batch uses one slot and verifies/deletes its
selected files sequentially. Individual publications can use the other slots.

Restart holds unfinished file operations for explicit inspection rather than
replaying them. Interrupted publication can return its validated output to
review through the existing recovery action. Cleanup retains its recovery
marker and requires a fresh preview. No original or output is automatically
deleted during startup or queue maintenance.
