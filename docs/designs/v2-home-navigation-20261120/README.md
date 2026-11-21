# Home and main navigation — proposed design, 2026-11-20

Design for issue #104. **Status: proposed, awaiting operator approval.** This package holds a static prototype with synthetic data, its renders and a proposed navigation contract. It is not served by Curator, calls no API, and authorizes no implementation. #108 (navigation) and #110 (Home) implement it after approval and after the contract below is frozen.

Baseline: v2 `146d6ede13fe28befe76bcf9c8c4f57c32061ffa`. Sources: [product direction](../../curator-v2.md), [standards](../../curator-v2-standards.md), [history](../../curator-v2-history.md), and the approved [queue feature lock](../queue-20261117/feature-lock.md).

Open `prototype.html` in a browser. `#s=` picks a scenario: `home`, `loading`, `error`, `empty`, `focus`, `library`, `draft`, `history`, `config`. Links inside the prototype show the proposed routes but do not navigate between scenarios. Every name, title and count is synthetic.

## Renders

| Render | Shows |
| --- | --- |
| [home.png](home.png) | Home with every section populated |
| [loading.png](loading.png) | First load: skeletons in place of each section |
| [error.png](error.png) | Refresh failed: last update kept and dated, retry offered, queue unaffected |
| [empty.png](empty.png) | No libraries connected: one action, to Configuration → Connections |
| [focus.png](focus.png) | Keyboard: skip link and a visible focus ring on the main tabs |
| [library.png](library.png) | Library Manager entered from Home's "Jobs need attention": the approved three-lane queue with a visible, removable filter |
| [draft.png](draft.png) | Leaving Library Manager with an unsaved editor: Keep editing / Discard and leave |
| [history.png](history.png) | History entered from "Work accomplished": filters come from the link and can be cleared |
| [config.png](config.png) | Configuration landing: today's Settings plus the standards sections proposed in #105 |
| [phone-home.png](phone-home.png), [phone-library.png](phone-library.png) | 390 px: tabs scroll sideways, cards stack, no horizontal page scroll |

## Main navigation

Four top-level tabs: **Home**, **Library Manager**, **History**, **Configuration**. A thin status line under the tabs, present on every tab, shows the live queue summary and that the queue runs across all libraries.

- **Home** is new. It is read-only: every item is a link into the matching work. Home never starts, pauses, approves, publishes, purchases or requests anything.
- **Library Manager** is today's workbench, unchanged. It keeps the library sidebar, with Queue, File management and Artwork indented under the selected library (approved 2026-11-18), plus the approved three-lane queue, inspector, review flows, confirmations and limits. The Library Manager tab shows the count of results ready to review, replacing the old sidebar "Ready for review" item as the approved lock asked.
- **History** is the existing screen (#86, #111), moved from the sidebar to a tab.
- **Configuration** holds today's Settings (Connections & tools, Processing defaults) plus Standards by Plex type and Library overrides (#105).

## Home sections

Ordered for "review by exception": what needs you comes first.

1. **Needs your decision.** Counts with one link each: results ready to review, jobs needing attention (with History's safe next step), items missing a standard's required field, and open standards questions.
2. **Work accomplished.** Last 7 days: jobs completed, upscales published, space saved, and who started them (you, rules, AI-assisted). Links to History with those filters.
3. **New in Plex.** Recent arrivals, each with its status against its library's standard. Each opens the item in Library Manager.
4. **Library health.** One row per library: its Plex type, how many dimensions its standard turns on, and its lowest dimension as a percentage of items meeting it. Dimensions turned off are not counted, and health is not shown as a single grade.
5. **Requests that landed** and **Worth watching** show their not-connected states until #114/#115 and #112/#113 land. They never request or buy.

Health, arrival status and missing-field counts depend on standards evaluation (#107). Before #107 they show "Not evaluated yet", and Home does not invent numbers.

## Navigation contract (proposed; freeze on approval)

Routes are hash URLs, so a view can be bookmarked, linked from Homebase, and reached with Back and Forward. Unknown or stale routes fall back to the nearest valid view, with a short notice.

| Route | Opens | Query (all optional) |
| --- | --- | --- |
| `#/home` | Home | — |
| `#/library/<id>/files` | Library view of one library | `view=attention\|files\|completed`, `group=folder\|task\|movie`, `dimension=<standard dimension>`, `asset=<id>` |
| `#/library/<id\|all>/queue` | Queue, filtered to one library or all | `status=all\|running\|queued\|review\|attention` |
| `#/library/<id\|all>/review` | Ready to review | `kind=upscale\|optimize\|join` |
| `#/library/<id>/filemanagement`, `#/library/<id>/artwork` | Those tools for the library | — |
| `#/history` | History | `view=jobs\|curator`, `library=<id>\|all`, `period=all\|1\|7\|30`, `status=…`, `level=…` (the existing History filters) |
| `#/configuration/<section>` | Configuration | `connections`, `processing`, `standards/<kind>`, `library/<id>` |

Rules:

1. **Links only filter.** Following a route changes what is shown and never changes a job, a setting or media. A filter that came from a link is shown as a removable banner ("Opened from Home…"), not hidden state.
2. **Unsaved work wins.** Any navigation away from a dirty editor (tab, sidebar, Back, or a deep link) goes through the existing unsaved-edit check: Keep editing / Discard and leave. Leaving never pauses or cancels the queue.
3. **Context is preserved per tab.** Each tab keeps its last route, scroll position, selection and filters for the session. Returning to a tab restores them; following a new deep link replaces them. The selected library is shared across Library Manager, History ("This library") and Configuration's library pages.
4. **Global scope stays explicit.** Start queue, Pause after current and processing limits keep their "Across all libraries" scope, whatever library or filter is in view.
5. **Focus.** A Skip to content link comes first. The main tabs are a `nav` landmark of links with `aria-current="page"`. After navigation, focus moves to the new page's heading, and after closing a dialog or inspector it returns to the control that opened it, as today. Every route works without a mouse.
6. **Loading and errors.** Each Home section loads independently, with skeletons. When a refresh fails, the last update stays visible with its time, as the existing connection status already does. Empty states name the one action that fixes them.

## Questions for the operator

- **Order of Home sections.** Decisions → accomplishments → arrivals → health, with discovery last for now. The brief expects discovery to take more space as maintenance becomes routine. Is this order right for today?
- **Library Manager badge.** Should the tab count only results ready to review (proposed), or also jobs needing attention?
- **Greeting.** Keep the time-of-day heading, or use a plain "Home"?

## Boundaries

- Design only. No application code, routes or state contract change until the render is approved and the contract above is frozen.
- Plain HTML, CSS and JavaScript with Curator's palette; no dependencies.
- The approved queue, editor, review and publication behaviour is preserved. Home adds no new way to run work.
