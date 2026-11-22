# Curator v2 — feature-lock acceptance matrix

Issue #155. **Status: first audit pass, 2026-11-22, by Claude; awaiting independent review.** Nothing here is accepted. This document maps each requirement of the [feature lock](designs/queue-20261117/feature-lock.md) (including its 2026-11-18 amendments, with v2 portrait-poster standards superseding earlier landscape defaults) to the code and synthetic tests that cover it, and to what still needs external acceptance. It does not recreate or reassign the implementation tickets.

## Baseline and method

- **Source:** v2 `48d280cece63a03d947496e17dc5d1714e046c6f`. On this commit: 617 Python tests OK (3 optional skips) and 147 JavaScript tests pass (`node --test`).
- **Method:** each requirement was traced to its implementing module and to named tests in `tests/`. A test is cited only when its name and body exercise the requirement. Visual, live Plex, live Mage, real-media and host behaviour cannot be shown by synthetic tests and are marked **External**.
- **Not done in this pass:** interactive browser walkthroughs of every flow, theme-by-theme visual comparison with the approved renders, and any live provider, Plex or host check. Those belong to the external-acceptance rows below and to release acceptance #120.

**Evidence classes**

| Class | Meaning |
| --- | --- |
| **Tested** | Implemented, with a named synthetic test that exercises it |
| **Implemented** | Code present; no direct automated test found |
| **Gap** | Not found, or only partly met; owner named |
| **External** | Synthetic evidence exists, but acceptance needs a live service, real media, the host or the operator's visual approval |

None of the rows is **Accepted**: no operator acceptance against this matrix has been recorded.

## Ticket state (as found, not as evidence)

- Curator #53, #54, #55, #56 and #5 are **open with no work-state label**. Merged PRs reference them, but a merged title is not acceptance; none should be closed on this matrix alone.
- Forge #86–#109 are **open**, except Forge #95 (File management workspace), which is closed. Their reported completion is supporting evidence only.
- The feature lock's 2026-11-17 execution hold is historical: the same document records Mike's later authorization to develop with Forge. Deployment, production restarts, real media/Plex writes and paid generation remain separately authorized.

## 1. Queue and review (#53, Forge #86–#92)

| Requirement | Evidence | Class |
| --- | --- | --- |
| Universal cross-library queue, per-type limits; file operations share a maximum of four | `test_file_queue.py`: `all_entry_points_share_at_most_four_running_operations_and_pause_drains`, `file_limit_cannot_exceed_four…`; `test_universal_queue.py` | Tested |
| Lanes: Upscaling, Encoding, File operations, plus **Artwork generation** (amendment) and **Metadata** with AI assist and folder metadata (amendment) | `test_queue_board.js`: `five populated columns include AI assist in Metadata…`, `artwork generation has its own lane including parallel jobs…` | Tested |
| Hide empty columns; compact, left-aligned, at most 360 px; limits reachable for hidden queues | `test_queue_board.js`: `empty board has no columns…`; `.queue-board` grid columns `minmax(0,360px)` in `style.css` | Tested (hiding); Implemented (width/alignment); **External** (visual match) |
| Every concurrent running job visible with progress; one head card plus compact waiting rows | `test_queue_board.js`: `visible lanes keep all concurrent jobs and render the waiting head once`, `active and attention jobs stay visible while waiting columns expand independently` | Tested |
| First five waiting (including the head), per-column Show N more, survives refresh; shared allowances | `test_queue_board.js`: `waiting queues show five including the head…`, `five waiting jobs need no disclosure…`, `file preparation and copy jobs share one five-item waiting disclosure` | Tested |
| Start queue / Pause after current with explicit All-libraries scope; controls directly under each heading | `queue-board.js` `queueLaneControl`; `test_queue_board.js`: `selection and preparation controls precede active cards in every queue` | Tested |
| Drag or keyboard reorder only within a type; Move to top/bottom; stale/filtered snapshots safe | `test_queue_board.js`: `drag refuses cross-lane targets…`, `filtered move preserves hidden slots…`, `keyboard reorder moves one position…`; `test_queue_order.js`: `top/bottom actions retain…`; `test_queue_order.py` | Tested |
| File-operation reordering only through a reviewed contract | `test_file_queue.py`: `waiting_order_persists_and_admission_uses_display_order`, `invalid_order_cannot_drop_duplicate…`, `new_jobs_append_and_stale_snapshots_reject_without_writes` | Tested |
| Remove returns a waiting job to suggestions, preserving settings and outputs (#41) | `test_queue_controls.py`: `remove_waiting_job_preserves_plan_and_prevents_execution`; `test_queue_board.js` (no removal for file jobs) | Tested |
| Pink/plum temporary inspector; Escape/close restores lane and position; opening never mutates | `style.css` `.queue-workspace #task-dialog` (pink to plum); `test_queue_board.js`: `inspector restoration finds the same queue control after polling…`; `test_file_management.js`: `clicking the queue card surface opens the task…` | Tested (restore); **External** (visual match to render) |
| Review opens the comparison automatically; all required samples before accept; hash/version gates | `test_comparison_preparation.py`: `ready_requires_all_four_images_on_both_sides`, partial-image and late-preparation tests; `test_curator.py`: `missing_manual_comparison_blocks_publish`; `test_review_workflow.js`: `late comparison cannot populate a closed or different inspector` | Tested |
| Diagnose the reported missing-screenshot failure (Forge #91) | Partial/late preparation errors are specific and tested (above). The original incident is not reproduced in synthetic tests. | **External** |
| Continuous accept/reject/skip, keyboard, resume | Server session: `test_review_sessions.py` (4 tests: accept needs the actual task action and the saved cursor survives resume; reject and skip are distinct and skip leaves the result pending; reads reconcile without replaying; session scope). Browser: `test_continuous_review.js` (3 tests: opening snapshot, resume never publishes, shortcut guards) | Tested |
| Bulk accept warns once with count/scope; reject resets to actionable work, not cancelled | `test_bulk_selection.js`: `bulk acceptance warns once with exact selection…`, `bulk rejection needs no publication popup…`; `test_bulk_rejection.py` (3 tests); `test_bulk_review.py`: `direct_bulk_accept_confirms_once…` | Tested |
| No bottom-right overlay toasts; scoped inline feedback; persistent errors; reliable Undo | `app.js` `toast()` now writes to an inline feedback region; `test_inline_feedback.js` (4 tests including Undo); `test_queue_controls.py`: `undo_deleted_queued_task_does_not_restart_it` | Tested |
| Notifications optional in Settings; never asks permission automatically | `test_unattended_ui.js` (2 notification tests) | Tested |
| Current jobs first; recent activity collapsed; saved groups route to review or history | `test_queue_board.js`: `saved groups route to review or history and preparation retry uses current versions` | Tested |
| Ready to review covers every review kind | `test_queue_board.js`: `ready link sends all review kinds to the unified inbox`, `mixed artwork and video review remains visible…` | Tested |

## 2. Library and metadata (#54, Forge #93–#99)

| Requirement | Evidence | Class |
| --- | --- | --- |
| Group by task: distinct Metadata and Artwork groups; a row opens its editor directly; checkboxes independent | `test_file_management.js`: `a stale grouped row refreshes instead of opening an unrelated task`, `hidden selections are disclosed, and checking a row does not open a tool`; `test_review_workflow.js`: `ready file overview labels the result without preselecting unrelated work` | Tested |
| Collapse all groups for both grouping modes (amendment) | `test_folder_collapse.js` (6 tests) | Tested |
| Select all → Edit selected metadata → exact before/after preview → approve and queue, across folders; only changed fields apply; no no-op queueing | `test_metadata_managers.py`: `multi_folder_selection_and_atomic_approval`, `preview_and_approval_only_queue_and_keep_unchecked_labels`, `list_add_replace_clear_and_noop`, `stale_task_or_plex_value_rejects_without_any_queue_changes`; `test_bulk_selection.js`: `metadata selection opens the bulk metadata editor…` | Tested |
| Tags/genres renamed Categories (Plex genre kept); Categories and Collections search, multiselect and explicit Create; nothing writes Plex before approved work runs | `metadata-manager.js` labels; `test_collections.py` (lookup read-only, scoped catalogs, pagination); `test_editor_fixes.js`: `new collection creation is explicit…`, `smart collection cannot be selected or recreated` | Tested |
| Labels controls removed without clearing existing labels | `test_metadata_managers.py`: `…keep_unchecked_labels` | Tested |
| File management separate from metadata editors; library sub-navigation (Queue, File management, Artwork); unsaved-edit checks | Forge #95 closed; `test_file_management.js`: `File management navigation respects unsaved edits…`, `the library Queue link changes only the view scope…` | Tested |
| Metadata owns cast names, roles and order; shared bulk Cast unchecked by default and explicit | `test_metadata_managers.py`: `cast_is_explicit_and_existing_portrait_is_preserved`; `test_cast.py` (names/order/removals, stale checks, canonical portrait re-add) | Tested |
| Artwork owns portraits; portraits belong to the person, not each credit; Manage portraits preserves unsaved context | Person ownership: `test_approved_artwork_editors.py`: `person_generation_and_save_belong_to_profile_not_credits`; `test_artwork_workflows.py`: `portrait_review_selects_exact_credit_and_preserves_other_people`, `local_portrait_identity_and_image_save_do_not_modify_plex`; `test_editor_fixes.js`: `portrait library creates a local person without requiring existing credits`. The **metadata → People handoff keeping unsaved context** has no direct test found (`test_managers.js`'s generation-close test covers Artwork, not this handoff) | Tested (ownership); **Gap** (handoff context: no direct test; owner #54 / Forge #98); **External** (native Plex portrait publication remains blocked by design) |

## 3. Artwork types, targets and batch scope (#55, Forge #100–#105)

| Requirement | Evidence | Class |
| --- | --- | --- |
| Correct format per type: covers (portrait by v2 standard), 16:9 backgrounds, 1:1 square and portraits, true-alpha logos not forced square | `test_artwork_managers.py`: `correct_shapes_and_real_alpha_logo_required`, `opaque_logo_cannot_bypass_editor_validation…`; `test_artwork_workflows.py`: `ratios_target_defaults_explicit_overrides_and_style_defaults`, `nonportrait_posters_are_refused…`; `test_managers.js`: `personal media poster editor only offers portrait, backgrounds stay landscape`; `test_approved_artwork_editors.py`: `portrait_derivative_retains_original_and_square_geometry` | Tested |
| Collection art never changes member art, membership or smart rules | `test_artwork_managers.py`: `collection_identity_is_separate_from_members…`; `test_artwork_workflows.py`: `collection_poster_default_stays_portrait…` | Tested |
| Folder/shared background lists exact affected items; no silent fan-out | `test_folders.py`: `shared_cover_uses_existing_review_queue_and_verified_readback`, background reservation tests; `test_approved_artwork_editors.py`: `shared_background_rejects_changed_current_image_before_publication` | Tested |
| Editor: type-correct previews; Replace/Crop/Generate/Create logo; originals kept; never stretched | `test_approved_artwork_editors.py` (geometry, derivative tests); `test_artwork_workflows.py`: `original_is_preserved_and_identical_image_is_noop` | Tested; **External** (visual) |
| One changed badge per asset; no changes means Preview disabled; approve only changed targets; no automatic publication | `test_artwork_workflows.py`: `original_is_preserved_and_identical_image_is_noop`, `import_is_durable_review_not_a_write…`; `test_managers.js`: `reopened artwork cards use fresh preview URLs without creating drafts` | Tested (no-op and approval); badge appearance: **External** |
| Batch editor keeps each file's own cover; one shared versus individual backgrounds | Backend: `test_artwork_workflows.py`: `per_title_batch_freezes_distinct_context_and_selected_targets` (distinct generation context and targets per title); shared-background guard: `test_approved_artwork_editors.py`: `shared_background_rejects_changed_current_image_before_publication`. The **batch editor's per-file cover rendering and the shared-versus-individual background choice in the UI** have no direct test found | Tested (backend); **Implemented**, UI not directly tested (owner #55 / Forge #103) |
| Artwork previews fetch current Plex images on reopen; a verified rename pending with a 404 resolves only a unique exact destination (amendment) | `test_artwork_workflows.py`: `artwork_preview_follows_only_the_verified_renamed_file_and_keeps_task_identity`, `…does_not_guess_identity_for_an_untracked_rename`, `…refuses_ambiguous_rematches_or_changed_files` | Tested |
| Approve & queue closes the preview immediately on full success; stays open on failure or partial failure (amendment) | `artwork-manager.js` closes the inspector after the approve loop succeeds | Implemented (no direct test found) |

## 4. Style guides and simple generation (#55/#5, Forge #106)

| Requirement | Evidence | Class |
| --- | --- | --- |
| Branding presets as editable style guides, seeded with Gritty cinematic, Grindhouse and Anime | `branding.py` default presets; `test_artwork.py`: `settings_publish_editable_presets_and_validate_count`, `style_defaults_round_trip…` | Tested |
| Resolved prompt visible/editable; guide, version, prompt, context and settings frozen into the request; later guide edits never change queued jobs | `test_approved_artwork_editors.py`: `style_save_is_versioned_and_never_rewrites_existing_plans`; `test_artwork_workflows.py`: `style_snapshot_and_per_title_context_survive_rename_and_deletion` | Tested |
| Format, model, resolution and references are structured settings; per-model schema; advertised Mango versions | `test_approved_artwork_editors.py`: `catalog_is_image_only_prioritizes_mango_and_uses_per_model_options`, `width_height_models_preserve_ratio_and_schema_bounds`, `other_models_keep_their_architecture_and_reference_field_in_quote` | Tested; **External** (live catalog) |
| Exact reference template `re-imagine this image in style guidance X`; restore text-only wording when the reference is removed (amendment) | `test_artwork_workflows.py`: `reference_prompt_uses_exact_template_and_style_details`; `test_managers.js`: `selecting a family reference uses the exact style template…` | Tested |
| Small first view; priced Generate is the consent; no second approval; Cancel/X restores the editor draft | `test_managers.js`: `Generate approves once, starts only the artwork queue and removes the form`, `generation close restores parent nodes and unsaved artwork draft` | Tested; **External** (visual match to the simple-panel render) |
| Fixed-width Generate with status on its own row; Generate navigates to the queue; no second Run (amendment) | `test_managers.js`: `Generate approves once, starts only the artwork queue…`, `queue start failure retains approval and never resubmits the generation` | Tested |
| References are operator-chosen and disclosed before sending; private until quoted consent | `test_artwork_workflows.py`: `references_remain_private_local_blobs_until_quoted_consent` | Tested |

## 5. Mage quotes and Gems budgets (#5, Forge #108)

| Requirement | Evidence | Class |
| --- | --- | --- |
| Request-specific estimate (MCP `estimate_cost`), balance before generation; changes invalidate the estimate | `test_mage.py`: `quote_uses_exact_mcp_estimate_for_nondefaults_and_references`, `discovery_is_read_only_and_returns_live_models_and_optional_balance`; `test_mage_pricing.py`: `unrecognized_cost_cannot_enable_generation`, `live_estimate_envelope_prices_only_the_selected_model` | Tested; **External** (live MCP pricing) |
| Over-budget check still shows the estimate, option count, budget and Gems over (amendment) | `test_managers.js`: `an over-budget cost check keeps the estimate visible and generation disabled`, `monthly allowance blocks generation and exact batch limit is priced` | Tested |
| Atomic reservations across concurrent batches and the monthly limit | `test_mage_budgets.py`: `reservations_prevent_two_quotes_overspending_monthly_allowance` | Tested |
| Actual charge and only confirmed refunds adjust budgets; uncertain submits never retried silently | `test_mage_budgets.py`: `actual_charge_and_only_confirmed_refunds_adjust_budget`, `malformed_refund_never_hides_a_known_charge`, `unsubmitted_cancel_releases_but_uncertain_terminal_keeps_reservation`; `test_artwork_workflows.py`: `mage_uncertain_submit_reuses_same_body_and_key_after_explicit_resume`, `generation_request_identity_survives_restart_without_replay` | Tested; **External** (real billing) |
| Estimate is not presented as a provider-enforced cap | Documented in the lock; UI copy not separately tested | Implemented; **External** (copy review) |

## 6. Transparent logo production (Forge #107)

| Requirement | Evidence | Class |
| --- | --- | --- |
| Local styled text on a transparent canvas, chosen installed font | `test_approved_artwork_editors.py`: `local_render_is_queued_and_rejects_unknown_font…`, `text_is_literal_file_input_and_font_paths_are_not_caller_controlled`; `test_logo_auto_preview.js` (8 tests) | Tested |
| ImageMagick cleanup of a provider logo on a flat background, original kept, explicit preview | `local_artwork.py` (`magick` discovery); `test_logo_auto_preview.js`: `imported logo cleanup still requires an explicit preview` | Tested (preview gate); **External** (edge/halo quality on real images; ImageMagick installation on the host) |
| Checkerboard/light/dark preview; real alpha; trim/pad without stretching | `test_artwork_managers.py`: `correct_shapes_and_real_alpha_logo_required` | Tested; **External** (visual) |

## 7. Download, archive, review and Plex publication (Forge #109)

| Requirement | Evidence | Class |
| --- | --- | --- |
| Every candidate downloaded promptly into Curator storage before review; unchosen kept | `test_artwork_workflows.py`: `mage_completed_job_downloads_before_review_never_publishes`, `candidate_requests_are_individually_accountable…`, `completed_download_recovery_never_submits_or_prices_again` | Tested |
| Archive layout: Movies/ and Collections/ × Posters/Backgrounds/Logos/Squares; flat Cast/ | `artwork_archive.py` directory map; `test_artwork_archive.py`: `portraits_are_flat_and_path_configuration_does_not_copy` | Tested |
| One Settings archive path; changing it never moves or deletes; unavailable path reported; append-only, collision-safe, no partial files | `test_artwork_archive.py`: `changed_path_keeps_previous_archive_and_unavailable_path_blocks_publish`, `archive_is_append_only_and_retries_are_idempotent`, `conflicting_file_or_symlink_is_never_overwritten`, `interrupted_copy_leaves_no_partial_final_file` | Tested; **External** (the operator's real NAS path) |
| Publish only approved artwork, with verified readback; stale Plex image blocks before upload | `test_artwork_workflows.py`: `stale_plex_artwork_blocks_before_upload_retains_candidate`, `tampered_candidate_never_reaches_plex` | Tested; **External** (live Plex) |
| Import of the existing desktop image folder | Explicitly a separate, later, non-destructive operation in the lock | Not in this scope |

## 8. Rename and library-navigation amendments

| Requirement | Evidence | Class |
| --- | --- | --- |
| A rename completes after filesystem moves and verification, without forcing a Plex scan; stable identity is kept and reconciled later | `test_files.py`: `rename_completes_when_plex_still_has_old_path`, `rename_does_not_scan_or_edit_plex_metadata`, `rename_moves_sidecars_backups_preserves_identity_and_task_ids`; `test_rename_preservation.py` (#70) | Tested |
| Renaming keeps unsubmitted suggestions and drafts; only approved, path-dependent plans are invalidated; repair of rename-blocked suggestions only with proof | `test_files.py`: `rename_preserves_suggestions_and_deleted_receipts_but_invalidates_approved_work`, `repair_only_untouched_rename_blocked_suggestions_without_replaying_work` | Tested |
| Library sub-links (Queue, File management, Artwork) under the selected library; Queue starts with that library's filter; global scope unchanged | `test_file_management.js`: `the library Queue link changes only the view scope and clears waiting selection` | Tested |

## 9. Cross-cutting acceptance

| Requirement | Evidence | Class |
| --- | --- | --- |
| Both themes, keyboard use and narrow layouts | `test_themes.js` (3 tests: Classic, Cyberpunk and Plex themes); `test_queue_board.js` keyboard tests | Tested (behaviour); **External** (visual match in each theme and on a phone) |
| Approved visual match for queue, library and artwork screens | Renders in `docs/designs/queue-20261117/` | **External**: needs operator comparison |
| Real Plex, provider, native portrait and host recovery acceptance | Out of synthetic reach | **External**: release #120, Foundry #12 |

## Findings in this pass

No defect was found that needs a new ticket. Open items:

1. **Untested UI behaviour.** Corrected after Codex's audit (2026-11-22): the metadata → People handoff keeping unsaved context (section 2) and the batch editor's per-file covers and shared/individual background choice (section 3) are implemented but have no direct test. Owners: #54 / Forge #98 and #55 / Forge #103.
2. **Approval close-on-success has no direct test** (section 3). The behaviour is in `artwork-manager.js`, but no test pins "closes only when every change queued, stays open otherwise". Owner: Curator #55 / Forge #104.
3. **Visual acceptance is the main remaining gap.** The pink inspector, five-lane layout and 360 px columns, the simple generation panel, logo previews and the themes are implemented and behaviour-tested, but nothing here compares them with the approved renders. Owners: Forge #92, #99, #105 (integration and visual acceptance).
4. **Live-service rows** (Mage pricing and billing, Plex publication and readback, the NAS archive path, ImageMagick on the host) stay External. They carry into release acceptance #120 together with the carried regressions #94, #97, #1, #12, #27, #41 and #43.

## Next steps

- Independent review of this matrix (Codex), then operator review of the External rows and of the remaining visual comparisons.
- Close or re-label legacy tickets (#53–#56, #5, Forge #86–#109) only with their owners, on accepted evidence, never on this matrix alone.
