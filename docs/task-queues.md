# Task-type queues and History filters

Each task kind has its own processing queue. Run queue starts/resumes that type for the selected library; Run all task queues starts the eligible types in that library. Only one worker of a given type runs across Foundry, while different types can run concurrently (including HandBrake encoding and Topaz upscaling). A type occupied by another library is reported busy rather than duplicated.

Pause after current, or Pause all after current, stores a pause flag and lets claimed jobs finish. No waiting job is claimed after the pause commits. It does not cancel, reapprove or remove work. Resume is explicit; process startup never automatically resumes queues. Saved ordering and paused state survive restarts.

Jobs of different types that target the same source wait for the reservation to clear. Their task status stays Waiting; the type queue reports that it is waiting for another job on the file. Other queue types can proceed. Existing source/fingerprint/publication checks still apply. Dragging and position numbers are within a task-type queue; selected top/bottom operations preserve each type's relative order.

History has All, Completed, Cancelled, Rejected, Failed and Blocked/interrupted filters, including cleanup outcomes. Completed includes applied and resolved work. Waiting, processing and review tasks remain in Queue.

Version0.4.0 adds private pause settings without a schema migration or new dependency. Deploy only while idle; preserve waiting approvals and settings in a database backup. Real concurrent encoding resource/throughput acceptance is separate from synthetic scheduling tests.
