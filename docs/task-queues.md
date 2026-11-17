# Task-type queues and History filters

Queue is shared across libraries. The Library filter changes what you see; **Run all libraries** and per-type Run/Resume use the shared queue. **Processing limits** sets 1–8 concurrent jobs per type; the existing default is one. For example, choose one upscale and two encoding jobs. Lower limits let current jobs finish; Run/Resume fills extra slots after an increase. Different types can run together, while jobs targeting the same source never overlap.

Pause after current, or Pause all after current, stores a shared pause flag and lets claimed jobs finish. No waiting job is claimed after pause commits. It does not cancel, reapprove or remove work. Resume is explicit; startup never automatically resumes. Saved ordering, limits and paused state survive restarts. Legacy library-specific run requests remain library-scoped but share global type capacity; the new UI explicitly requests all-library execution.

Source-reserved jobs stay Waiting while independent eligible jobs can proceed. Existing source/fingerprint/publication checks still apply. New submissions append to one durable order. Dragging and top/bottom actions update it; per-type position numbers derive from that shared order. Cross-library ordering is migrated deterministically while preserving each library's saved relative order. A previously paused library/type pauses that type globally on migration; migration never starts work.

History has All, Completed, Cancelled, Rejected, Failed and Blocked/interrupted filters, including cleanup outcomes. Completed includes applied and resolved work. Waiting, processing and review tasks remain in Queue.

Version0.4.0 adds private pause settings without a schema migration or new dependency. Deploy only while idle; preserve waiting approvals and settings in a database backup. Real concurrent encoding resource/throughput acceptance is separate from synthetic scheduling tests.
