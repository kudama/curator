# Synthetic Plex collection row review

2026-11-22. Proposed Settings flow for #116; all movie names, IDs and Plex responses
are synthetic. No live server or catalogue was used. Implementation/reviewer evidence
is distinct from operator acceptance.

Six browser captures: Classic, Cyberpunk and Plex at desktop1440 and phone390.
Phone dialog scrolls vertically; action controls remain in the dialog after the full
review, and horizontal overflow is checked. Each capture shows an explicit read-only
preview, before any approval or fake-Plex mutation. Initial opening reads only local
ownership state. The browser interaction test also verifies input invalidation and
one explicit approved publication to the in-memory fake adapter.
