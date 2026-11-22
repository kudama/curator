# Standards configuration — proposed design, 2026-11-20

Design for issue #105. **Status: operator approved the desktop direction on 2026-11-21 ("this looks good"); review corrections below are pending exact-head cross-review.** This package holds a static prototype with synthetic data and its renders. It is not served by Curator, calls no API, and authorizes no implementation; #109 implements it after approval.

Baseline: v2 `146d6ede13fe28befe76bcf9c8c4f57c32061ffa`. Model and API: [library standards](../../curator-v2-standards.md). The field mapping is recorded there under "Configuration screen".

Open `prototype.html` in a browser. `#s=` picks a scenario: `type`, `library`, `unsaved`, `review`, `libreview`, `noop`, `error`, `conflict`, `libconflict`, `leave`. Every name, value and revision in it is synthetic.

## Renders

| Render | Shows |
| --- | --- |
| [type.png](type.png) | Movies standard: dimensions with "Counts toward completion", revision, libraries using it, and which library overrides which field |
| [library.png](library.png) | An Other Videos library: each field marked Inherited or Override, the effective value, the type's value beside each override, "Use Other Videos value" |
| [unsaved.png](unsaved.png) | Unsaved edits: Changed tags, a dot on the section in the sidebar, the change count |
| [review.png](review.png) | Review before saving a type standard: before/after per field and which libraries each change reaches; libraries that override a field keep their override |
| [libreview.png](libreview.png) | Review before saving library overrides, including a field going back to inherited |
| [noop.png](noop.png) | Reviewing with no changes: nothing is saved and the revision stays the same |
| [error.png](error.png) | An invalid threshold: inline message, Review disabled until fixed |
| [conflict.png](conflict.png) | Stale revision: someone saved revision 4 in another window. Edits are kept, nothing is saved, Reload revision 4 |
| [libconflict.png](libconflict.png) | The type standard changed while library overrides were being reviewed: nothing is saved, overrides are kept, Reload Movies revision 4 and review again |
| [leave.png](leave.png) | Leaving with unsaved changes asks Keep editing / Discard changes |
| [phone-library.png](phone-library.png) | 390 px wide: tabs and sections scroll horizontally, cards stack, actions stay reachable |

## Decisions in this design

1. **Where it lives.** Configuration tab → **Standards by Plex type** (Movies, TV Shows, Other Videos) and **Library overrides** (one page per library), beside the existing settings sections. Settings that exist today are not redesigned here.
2. **Type page.** It edits the full standard. Each dimension is a card with one switch, **Counts toward completion** / **Not part of done**. A card that is off stays editable but dimmed, so turning it back on restores the saved choices. **Reset form to Curator defaults** only changes the form; it still has to be reviewed and saved.
3. **Library page.** It shows the **effective** value of every field. Fields are tagged **Inherited** or **Override**. Editing a field creates an override; setting it back to the type's value removes the override (overrides keep only real differences, as the API already does). **Use <Type> value** on any override, or **Use <Type> values for everything**, resets to inherited.
4. **Review then save.** Saving always goes through a review table (field, before, after, and which libraries are affected or the source). A type save names the libraries it reaches and those that keep an override. The save always says that nothing is processed or published.
5. **No-op.** Review with no changes saves nothing and keeps the revision. The API is never called for a no-op.
6. **Stale revision.** The API's revision check surfaces as a warning that keeps the edits and offers **Reload revision N**. It is never silently overwritten. Reapplying edits onto the newer revision is manual in this design.
   A library save also depends on the type standard it inherits from. Its review names the type revision it was checked against ("reviewed against the Movies standard at revision 3"). If the type standard, or the library's Plex type, changes before saving, the server refuses the save atomically, nothing is saved, the overrides are kept, and the page offers **Reload Movies revision N** and a fresh review. A browser re-fetch alone is not the guarantee; see the save contract in the standards document.
7. **Errors.** Field errors use the API's messages inline, with Review disabled. A server refusal on save is shown as a banner and keeps the edits.
8. **Unsaved changes.** Changed tags, a sidebar dot, a status count, and a Keep editing / Discard prompt when leaving the page.
9. **Upscaling target vs. scale.** The card states that the target is a resolution goal (1080p or 2160p), not a scale. The Topaz scale (1×, 2×, 4×, relative to the source) stays in Processing defaults, and the 4096 × 2160 output ceiling still applies.
10. **Posters** are fixed at 2:3 (operator decision, 2026-11-19), shown read-only.
11. **Space-saving re-encoding.** The field stored as `encoding.preserve_originals` is labelled **Skip space-saving re-encoding suggestions**. It only stops Curator suggesting re-encodes to save space. It is not a retention or deletion switch: publishing any re-encoded or upscaled file still keeps the original, whether it is on or off.
12. **Thresholds.** An empty encoding threshold shows **Uses global N Mbps**, taken from Connections & tools.

## Questions for the operator

- **Space-saving re-encoding (for #107).** Relabelled per review (decision 11). Still open for #107: whether it suppresses only bitrate-driven suggestions or every re-encode suggestion, and how it relates to today's per-file "preserve quality" choice. The stored field name stays `preserve_originals` for API compatibility.
- **Applying edits after a conflict.** Reload-then-reapply is manual. Is that enough, or should Curator offer to carry your edits onto the newer revision (still reviewed before saving)?
- **Completion counts.** Should the type page show how many items currently meet each dimension? That needs #107's evaluation first, so it is left out here.

## Boundaries

- Standards describe results and never start processing, publishing, purchases or requests.
- No new dependencies. The prototype is plain HTML, CSS and JavaScript with Curator's palette.
- Scans, completion and processing still do not read standards; that is #107.
