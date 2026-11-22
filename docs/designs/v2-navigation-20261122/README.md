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
- **Unsaved work:** any route change away from a dirty inspector goes through the existing check. Declining keeps the view, and the address goes back to it.
- **Per-tab context:** each tab remembers its last route for the session. In-app clicks keep the address in step; link-only parameters such as `lane` survive later background refreshes. The selected library is shared, as before.
- **Focus:** after navigation, focus moves to the page heading.

## Not in this change

- **Home content** (decisions, accomplishments, arrivals, health) is #110. The shell only links to existing work.
- **Standards routes** call `openStandardsEditor` from #161. Until that merges, those entries are disabled with a note.
- The default route is still Library Manager, so existing habits are unchanged. Switching the default to Home is a one-line change once #110 gives Home its content.
- The old sidebar "Ready for review", "History" and "Settings" buttons are hidden (the tabs replace them) but left in the page, so existing handlers keep working.
