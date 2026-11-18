# File management and direct task entry — 2026-11-17

Mike reported the missing left-menu tools and the extra Review stage. After
the [File management render](file-management-approved.png), he said “yup fix it.”
This approves this workspace and the direct-entry correction. It does not
authorize new file operations or changes to the remaining artwork/budget screens.

## Implemented behavior

- File management sits directly below Queue. Its Library selector scopes the
  file list and operations to one library; search does not change library scope.
  No permanent empty inspector. Library navigation still returns to the library.
- A filename opens its existing rename form directly in the pink inspector.
  Checkboxes select files independently; Rename requires one, Join parts at least
  two, and Collection / playlist at least one. Hidden selections are counted.
  Explicit selections are passed unchanged to the existing forms, without adding
  automatic part suggestions. Their ordered preview remains editable.
- Current filename, new filename, folder and size give rename context. Preview
  still creates the existing reviewed plan; approval/queueing is a separate
  explicit action. Entry, selection and changing a draft do not alter media/Plex.
  The existing original-retention, identity/version and shared file-operation
  maximum-four checks remain untouched.
- Clean up originals names its full-library scope. It retains the existing
  preview/confirmation workflow and is independent of file selection/search.
- Metadata/file overview links to the dedicated workspace; the old nested
  File tools menu is removed. Existing supported grouping is retained; metadata
  collection membership fields are not moved or changed by this patch.
- One task in a task-type group opens that exact task/editor/comparison directly,
  preserving unrelated selections. A stale row refreshes, rather than opening
  another kind. Multiple distinct plans still require an explicit choice through
  the existing overview; no arbitrary plan is approved/opened automatically.
  Queue card background/title/Details all open the task; clicking its controls
  does not trigger a second open.
- Navigation and library/selection changes respect existing unsaved-edit guards.
  Closing the temporary panel restores list space, position and focus.

## Validation

414 Python tests run, three optional skips, all others passed. 72 JavaScript
tests passed, including nine new navigation/scope/direct-entry cases. Syntax,
compileall and whitespace checks passed. No backend workflow/schema/dependency
change beyond serving the new frontend component.

Synthetic browser checks verified the sidebar entry, empty selection, direct
rename form and a task-type row opening its task without the overview/Review
stage. A narrow preview had 375-pixel client and scroll widths (no horizontal
overflow), and keyboard focus reached Preview rename. No preview/approval/media
operation was submitted. A Chrome unsaved-confirmation check hit a browser-control
modal limitation and could not be completed there; unit tests verify refused
navigation/library changes preserve context. Continued nonmodal checks in the
isolated in-app browser. No browser warning/error logs observed there.

Actual synthetic screenshots: [File management](file-management-check.jpg),
[direct task entry](direct-task-entry-check.jpg). Placeholder nature files,
counts and build labels in the approved render are illustrative, not runtime facts.
The render's thumbnail play glyph does not introduce a video player.
