# Curator v2 — product direction

Recorded 2026-11-19 from the operator's Forge design discussion. This is the agreed product direction and a starting brief for detailed design. Only the separate theme slice described below is implemented by this change; navigation, discovery and maintenance features remain to be specified and built.

## Purpose and experience

Curator first helps the operator bring a large existing catalog up to the desired standard. It then shifts toward maintaining new arrivals with progressively less intervention and helping the operator discover something worth watching. Design around fewer repeated decisions, useful defaults, batch work, review by exception, preserved working context and visible progress.

The current application is the working screen. A new Home provides context and discovery, with direct entry into the corresponding filtered work. As routine maintenance becomes reliable, discovery takes more of Home's space. Automation follows explicitly configured standards and action permissions; navigation or recommendations do not authorize media changes, purchases or requests.

## Main navigation

| Tab | Purpose and content |
| --- | --- |
| Home | New Plex arrivals; Seer requests that have landed; recommendations; work accomplished; a concise library-health summary; decisions needing the operator. |
| Library Manager | The existing workbench: metadata, cast, artwork, file management, active queues and review. Preserve drafts, position and existing processing/publication safeguards. |
| History | Job history and Curator history, as described below. |
| Configuration | Existing Settings, service connections, and the standards/rules that define desired encoding, upscaling, metadata and artwork treatment. Shared defaults with library-specific settings where needed. |

Homebase remains the overall dashboard, with a compact Curator summary and links into Curator. Library health is a section of Curator Home, not an additional standalone destination or separate page for every library. Home summaries link directly to relevant work or filtered history. Exact placement and screens require prototype review.

## Library standards

Home movies and public media share the application but have different completion criteria. Expose the useful dimensions separately: cast, artwork, metadata, upscaling and re-encoding. Completion means meeting the selected standards, not performing every possible transformation.

- Home movies emphasize known people and portraits, dates/places/events, descriptive personal context and meaningful artwork. Enhancement and encoding choices reflect the source and preservation goals.
- Movies and television emphasize correct catalog identity, credits, descriptions, artwork and selected quality/storage/playback standards.
- Repeated cleanup choices should become explicit reusable preferences/rules, with a clear later path to approved maintenance of new arrivals. Do not treat inferred preferences as permission to execute.

## History

- **Job history:** completed, failed, cancelled and interrupted work; outcomes, relevant before/after details, and available supported recovery actions.
- **Curator history:** configuration/standards changes, connection failures and recovery, scans, application lifecycle events and system errors. Show readable events with technical details available beneath them. Exclude credentials.
- Identify the initiator where available: operator, automated rule or AI-assisted action. Filter by date, outcome and library where appropriate. Active work stays in Library Manager's Queue; Home summarizes accomplishments and links to history.

## Discovery and Plex recommendations

Candidate signals: recently added media, Rotten Tomatoes scores, social popularity, authorized library viewing activity and personal preferences/feedback. These are distinct sources with their own dates and meanings; show why an item was selected. Signal availability, account/data permissions, licensing and ranking behavior remain to be specified.

Curator should be able to maintain selected collections and publish them as rows in Plex Home / library Recommended. The operator confirmed Plex Pass. Plex documents [published collections](https://support.plex.tv/articles/publishing-collections/) and [recommendation row management](https://support.plex.tv/articles/manage-recommendations/); this does not establish control over Plex's internal recommendation algorithm or prove an implemented Curator integration. Proposed starter rows include “Picked by Curator” and “New and worth watching.”

Potential external sources discussed: [TMDB trends](https://developer.themoviedb.org/docs/popularity-and-trending), [Netflix's public Top 10](https://www.netflix.com/tudum/top10), [FlixPatrol's paid API](https://flixpatrol.com/api2/) and [JustWatch's partner API](https://apis.justwatch.com/docs/api/). No provider subscription, account connection, social-data integration or paid access was selected or purchased. Match available titles by verified catalog identity; preserve the distinction between recommendations already in Plex and titles that could be requested later.

## Plex / Tautulli theme slice

The operator requested a Plex/Tautulli-inspired appearance. Added as a third optional theme alongside Classic and Cyberpunk: charcoal surfaces, amber accents, system sans-serif typography, neutral media/editor backgrounds and matching selected states. It retains Curator branding and uses no third-party fonts/assets. Selection remains a browser-local preference; it does not change settings, drafts, job state or server configuration.

Development evidence: all 110 existing JavaScript behavior checks pass, with the theme coverage extended for the third choice, restoration, switching and blocked storage. Synthetic Chromium verification covers persistence, switching through all themes while an inspector draft remains open, queue/library/settings surfaces and five widths from 320–1440 pixels. No server mutation, production deployment or live media/provider action is part of this slice.

See [theme previews and verification](designs/plex-tautulli-20261119/README.md).

Next: review the theme preview and develop realistic prototypes for the V2 Home/navigation, Configuration standards and History views before their implementation. Preserve the separately reviewed interaction improvements in PR #83 when integrating.
