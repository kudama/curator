# Plex / Tautulli theme — 2026-11-19

Third optional appearance theme requested by the operator during Curator v2 planning. Baseline: `1fc33ce4edde99021bcf00e6dff1c8f9e7917c0e`. The existing workbench structure is retained; V2 direction is recorded in [the product brief](../../curator-v2.md).

Charcoal surfaces, amber wayfinding and selection, system sans-serif headings, neutral editors and previews. No external fonts, assets or dependencies. Classic remains the default and both existing themes remain selectable. Only the browser's existing theme preference is saved.

## Synthetic previews

- [Queue](queue.png)
- [Library](library.png)
- [Phone inspector](phone.png)
- [Settings](settings.png)

All media, names, processing states and artwork in these captures are synthetic. These are the current workbench with the new appearance, not a prototype of the future Home/navigation.

## Verification

All 110 JavaScript behavior checks pass; theme coverage includes all three choices, saved preference restoration, switching back, unavailable storage and retained dirty state without server calls. Changed JavaScript parses and whitespace checks pass.

Chromium: preference survives reload; switching through Classic, Cyberpunk and Plex / Tautulli preserves the opened inspector, dirty flag and job IDs/statuses/versions. Queue, library and Settings visually inspected. Inspector checked at 1440/1024/768/390/320px with no page horizontal overflow or page errors. Browser recorded zero POST requests. Production deployment, real media, Plex and paid providers were untouched.

The user reviews the visual direction before rollout. V2 navigation, discovery, standards and history work are separately planned.
