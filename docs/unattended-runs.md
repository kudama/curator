# Preparing unattended work

Queue a batch using a shared preset. The preset picker can remember the choice
for each library that successfully queues jobs. Individual encoding setup uses
that remembered choice. Upscale setup can explicitly remember current workspace
settings for its library. Remembered defaults apply only to new approvals;
already queued plans and credentials are unchanged.

**Run all libraries** opens a readiness summary before **Start unattended run**.
It shows waiting/running counts, shared processing limits, source/tool problems,
free storage and estimated extra output/staging space. Mounted volumes sharing a
device are grouped rather than adding their free space together. Unknown output
sizes remain unknown. Processing ETA uses comparable measured history and
current encoder estimates; publication time is additional. Files and settings
are checked again at execution. The snapshot does not run encoders or contact
Plex/providers, and it cannot guarantee later mount availability or output size.

Processing continues past failed jobs. Recognized temporary source-read failures
before processing or external writes start get at most two retries, after five
and fifteen seconds. Actual encoder/provider/write failures, source changes,
configuration errors, paid calls and uncertain publication/deletion outcomes
never automatically replay. **Retry failed jobs** rechecks safe ordinary jobs
and queues them without starting a run. Retained outputs and uncertain file
operations show recovery guidance and keep their explicit inspection actions.

Run summaries have fixed membership and queue-attempt identities. Later additions
do not reopen a finished batch or make it appear to have completed other work.
The summary distinguishes ready, published, accepted/publishing, failed, remaining
and changed jobs. Restart holds unfinished runs for explicit continuation. Bulk
review and cleanup receipts also contribute durable summaries.

Browser notifications are optional and requested only through **Enable browser
notifications**. Supported secure browser contexts notify once per completed or
interrupted batch, with counts and a note if other work remains. Historical and
duplicate events are suppressed. The browser must remain open; unsupported or
insecure contexts, including ordinary remote HTTP, keep durable summaries in
Queue instead. There is no new email/cloud notification service.

Version 0.5.0 uses the existing SQLite/settings store, with no new package
dependency. Back up state and upgrade only while idle. This release does not
start old waiting jobs or delete retained media at startup.
