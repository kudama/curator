# Main navigation, implemented (#108)

This implements the approved navigation contract in [v2-home-navigation-20261120](../v2-home-navigation-20261120/README.md) (#104/#128). The renders are from a synthetic DEV sandbox.

| Render | Shows |
| --- | --- |
| [library.jpg](library.jpg) | Library Manager tab: the existing workbench, the review badge (3), and the status line under the tabs |
| [home.jpg](home.jpg) | Home shell: read-only links into the existing work |
| [queue-link-cyberpunk.jpg](queue-link-cyberpunk.jpg) | `#/library/all/queue?status=attention` in the Cyberpunk theme, with its removable "Opened from a link" banner |
| [phone-home-plex.jpg](phone-home-plex.jpg) | 375 px, Plex theme: tabs scroll sideways, no page overflow |

## What is implemented

- **Tabs and status:** four tabs (Home, Library Manager, History, Configuration) as a `nav` of links with `aria-current`, a Skip to content link, a review badge counting every awaiting-review kind, and a status line on every tab.
- **Routes:** every route in the contract:
  - files with `view`, `group` and `asset`
  - queue with `status` and `lane`, which expands and scrolls to that lane
  - the review inbox with `kind`, including `preview_render`
  - file management
  - artwork with `status=review`, which shows that library's waiting count and an Open button using the existing artwork review
  - History with its existing filters
  - Configuration `connections`, `processing`, `standards/<kind>` and `library/<id>`
- **Unknown or stale links:** they fall back to the nearest view with a notice, and the address is rewritten to what is actually shown.
- **Links only filter:** following a route sends no write request (checked in the browser across every route type). A filter that came from a link is shown as a banner with "Show everything".
- **Unsaved or in-flight work:** before any route change, an open inspector goes through the existing check, which also refuses while a save is in flight. An open standards editor must agree to discard its changes; a standards route instead switches the editor's target through its own check. On refusal nothing changes: tab, address and filters stay as they were.
- **Per-tab context:** each tab remembers its last route, search, selections, selected item and list scroll for the session, restored when you return by its tab. Ids that no longer exist are dropped, and inspector drafts are never revived. A new link replaces the context instead. In-app clicks keep the address in step; link-only parameters such as `lane` survive later background refreshes. The selected library is shared, as before.
- **Home:** separate links for results to publish, metadata suggestions, and artwork per library, each to its own destination. The badge is their sum.
- **Standard-dimension links** (`dimension=`) are accepted, but filtering by dimension needs standards evaluation (#107), so the page says that instead of claiming a filtered list.
- **Focus:** after navigation, focus moves to the page heading.

## Not in this change

- **Home content** (decisions, accomplishments, arrivals, health) is #110. The shell only links to existing work.
- **Configuration** opens the existing Settings dialog and #161's standards editor from its page, rather than embedding them.
- The default route is still Library Manager, so existing habits are unchanged. Switching the default to Home is a one-line change once #110 gives Home its content.
- The old sidebar "Ready for review", "History" and "Settings" buttons are hidden (the tabs replace them) but left in the page, so existing handlers keep working.
