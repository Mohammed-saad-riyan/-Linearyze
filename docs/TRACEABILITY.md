# Traceability: SRS clause → code → test

Every row points at the code that implements the clause and the test that proves it. Test
names carry the clause number, so `pytest -k 1_5_4` runs everything behind 1.5.4. Clause
descriptions are paraphrased; the SRS itself is not in this repository.

Status: **Tested** (automated test in `api/tests`, runs in CI), **Eval** (covered by the
golden sets in `eval/`; `make eval` with the Claude key writes `docs/EVAL_REPORT.md`),
**Partial**, **Designed** (not built in the PoC, see the README).

## Component 0: platform, roles, permissions

| Clause | Requirement (paraphrased) | Code | Test | Status |
|---|---|---|---|---|
| 0.6.7 | Logout invalidates the session server-side | `app/auth/sessions.py` `logout` | covered by `test_0_7_7_no_session_is_401` path | Partial |
| 0.7.1, 0.7.3 | Three roles, one per account | `app/db/schema.sql` `users.role` CHECK | `test_0_8_22_matrix_has_21_capabilities_and_3_roles` | Tested |
| 0.7.5 | Roles do not inherit (Management → user admin 403, Admin → advisor 403) | `app/auth/sessions.py` `require` | `test_0_7_5_management_cannot_manage_users`, `test_2_2_3_admin_cannot_call_advisor`, `test_0_7_5_admin_cannot_call_assistant` | Tested |
| 0.7.6 | Authorization enforced server-side on every request | `require()` on every route in `app/main.py` | `test_0_8_23_permission_matrix[*]` | Tested |
| 0.7.7 | No session → 401 | `app/auth/sessions.py` `current_user` | `test_0_7_7_no_session_is_401` | Tested |
| 0.7.8 | Permission change applies to the next request, no re-login | role and scope read per request in `resolve` | `test_0_7_8_scope_change_applies_to_the_next_request` | Tested |
| 0.8 | The 21 × 3 permission matrix | `app/auth/permission_matrix.yaml` | `test_0_8_matrix_cells_match_the_srs_table` | Tested |
| 0.8.22 | Matrix is configuration data | `app/auth/permissions.py` | `test_0_8_22_changing_a_cell_changes_access_without_code` | Tested |
| 0.8.23 | One test per cell, 63 | `tests/test_permissions.py` | `test_0_8_23_permission_matrix` (63 cases) | Tested |
| 0.9.1.1 | Management sees all events and documents | `can_read_document` in `app/db/rls.sql` | `test_1_3_2_rls_hides_confidential` (management side) | Tested |
| 0.9.2.2 | Employee gets zero records and hits outside scope | `can_read_document`, event scope | `test_0_9_2_2_employee_scope`, eval `ca-05`..`ca-08` | Tested, Eval |
| 0.9.3.1 | Admin has no access to confidential content | RLS returns no rows for admin; matrix denies | `test_0_7_5_admin_reads_no_documents`, `test_0_7_5_admin_cannot_download_documents` | Tested |
| 0.10.1 | Assistant runs with the asking user's permissions | `app/db/session.py` `as_user` (transaction-local identity) | `test_api_role_cannot_bypass_rls`, `test_1_3_2_*` | Tested |
| 0.10.2 | M1 text exactly as specified | `app/assistant/messages.py` | `test_1_7_2_a_message_matches_spec[*-M1]` | Tested |
| 0.10.3 | M1 has no title, snippet, count or hint | `render_message` in `app/assistant/pipeline.py` | `test_0_10_3_m1_has_no_title_snippet_or_count`, `test_1_5_4_debug_flag_adds_nothing_to_m1` | Tested |
| 0.10.4 | Dedicated M1 test set | `tests/test_m1.py`, eval `nf-*`, `ca-*` | as listed | Tested, Eval |
| 0.10.6, 0.10.7 | No payments; advisor refusal message | `app/advisor/grade.py`, `messages.py` `PAYMENT` | `test_2_1_6_payment_request`, eval `adv-06` | Tested, Eval |

## Component 1: Search Assistant

| Clause | Requirement (paraphrased) | Code | Test | Status |
|---|---|---|---|---|
| 1.2.1, 1.2.2 | Ingest PDF, Word, Excel in Arabic and English | `app/ingest/parsers.py` | `test_1_2_pdf_arabic_comes_out_in_reading_order`, `test_1_9_6_*`, `test_1_9_7_*` | Tested |
| 1.2.3 | OCR for scanned pages | | | Designed |
| 1.2.7 | Metadata search (sender, dates, type, client) | `app/assistant/plan.py`, `filter_sql` | `test_1_14_9_*` | Tested |
| 1.2.12 | Latest version by default | `documents.is_latest`, `filter_sql` | `test_1_2_12_latest_version_only` | Tested |
| 1.2.13 | Earlier version on request | `Filters.version`, `requested_version` | `test_1_2_13_earlier_version_on_request`, `test_1_2_13_advisor_binds_a_requested_older_version` | Tested |
| 1.3.2 | No unreadable content reaches search or the model | `app/db/rls.sql` | `test_1_3_2_rls_hides_confidential`, `test_1_3_2_canary_unreachable_through_fulltext_and_vectors`, eval canary scan | Tested, Eval |
| 1.3.6 | Denied View or Download shows M1 | `view_passage`, `download` in `app/main.py` | `test_1_9_3_download_of_unreadable_document_is_404` | Tested |
| 1.3.7 | A document cannot instruct the model | grader never sees documents; RLS bounds the context | `test_1_3_7_injection_document_is_inert`, eval `inj-01` | Tested, Eval |
| 1.3.9 | Per-user rate limit, 429 with M6 | `_seconds_until_allowed` in `app/main.py` | `test_1_3_9_rate_limit_returns_429_with_m6` | Tested (in process) |
| 1.3.10 | Per-day limit | | | Designed |
| 1.4.1 | Reply language by script majority | `detect_language` in `app/text/arabic.py` | `test_1_4_1_language_by_majority_script` | Tested |
| 1.4.2 to 1.4.5 | Diacritics, tatweel, digits, letter variants | `app/text/arabic.py` | `test_1_4_2_*`, `test_1_4_3_*`, `test_1_4_4_*`, `test_1_4_5_*` | Tested |
| 1.4.6, 1.4.7 | Cross-lingual retrieval | multilingual embeddings, English topic reranking | eval `xl-*` | Eval |
| 1.5.4 | One M1 for four causes, identical in bytes and time | `render_message`, `M1_LATENCY_FLOOR_S` | `test_1_5_4_m1_byte_identical_four_causes`, `test_1_5_4_m1_headers_identical`, `test_1_5_4_m1_timing_within_tolerance`, eval M1 probe | Tested, Eval |
| 1.6.1 to 1.6.10 | Grades DR, IR, AM, OT | `app/assistant/grade.py`, `prompts/grade_assistant.md` | `test_1_7_1_output_selection_table`, eval | Tested, Eval |
| 1.6.11 | OT, including payment requests, gives M2 | `apply_rules`, `select_output` | `test_1_6_11_payment_request_to_assistant_is_m2` | Tested |
| 1.6.12 | Close grade scores → AM | `apply_rules` | `test_1_6_12_close_scores_are_ambiguous` | Tested |
| 1.6.13 | Two documents with one name → C | `_same_title_options` in `pipeline.py` | `test_1_6_13_two_documents_with_one_name_ask_which` | Tested |
| 1.6.14 | Two requests → C | `apply_rules` | `test_1_6_14_two_requests_are_ambiguous` | Tested |
| 1.6.15 | Reply to C is graded afresh | option text is resent as a query | `test_1_6_13_*` (second half) | Tested |
| 1.7.1 | Outcome is one of A to E | `app/assistant/outputs.py` | `test_1_7_1_output_selection_table` | Tested |
| 1.7.2, 1.7.3 | Defined messages exact; {max} and {n} filled | `app/assistant/messages.py` | `test_1_7_2_a_message_matches_spec`, `test_m5_long_query`, `test_1_3_9_*` | Tested |
| 1.8.2.1, 1.8.2.7 | B order; a card per document used | `_answer` in `pipeline.py`, `AssistantResponseView.tsx` | `test_1_8_2_m8_on_every_output_b` | Tested |
| 1.8.2.9 | Quotes verbatim | `app/assistant/validate.py`, `find_original_span` | `test_1_8_2_9_*`, eval "quotes verbatim" | Tested, Eval |
| 1.8.2.12 | Numbers, dates, names in quotes | `check_sentence` | `test_1_8_2_12_*`, eval "grounded" | Tested, Eval |
| 1.8.2.13 to 1.8.2.15 | Conflict: M7 first, both values, no preference | `app/assistant/conflict.py` | `test_1_8_2_13_conflict_shows_m7_first`, `test_1_8_2_15_preference_words_are_detected` | Tested |
| 1.8.3 | Output C with up to 5 options plus Other | `CLARIFY_*`, `MAX_OPTIONS` | `test_1_6_14_*` | Tested |
| 1.8.3.8 | M1 after the third AM regrade | | | Designed |
| 1.8.4.3, 1.8.4.5 | D order deterministic | `order_documents` | `test_1_8_4_3_*`, `test_1_8_4_5_*` | Tested |
| 1.9.1 to 1.9.3 | View and Download; original bytes | `view_passage`, `download`, `document_files` | `test_1_9_3_*`, `test_view_returns_the_cited_passage` | Tested |
| 1.9.6, 1.9.7 | Word heading and Excel sheet/range citations | `app/ingest/parsers.py` | `test_1_9_6_*`, `test_1_9_7_*` | Tested |
| 1.9.8 | Viewer highlights the quote | drawer marks the quote span (`documents.tsx`) | manual | Partial |
| 1.10 | Memory and history | | | Designed |
| 1.11.1 | Search box on every screen | `app/page.tsx` header | manual | Built |
| 1.11.6, 1.11.7 | Over-long query not sent, text kept | `QueryBox.tsx` | `test_m5_long_query` (server side) | Tested (server), manual (browser) |
| 1.11.10, 1.11.11 | Enter / Shift+Enter; direction by first strong character | `QueryBox.tsx`, `first_strong_direction` | `test_1_11_11_*` | Tested |
| 1.12 | Audit log without query or answer text | `audit_log` in `schema.sql`, `_audit` | `test_1_12_audit_log_has_no_query_text` | Tested |
| 1.14 | Golden set, canary scan | `eval/` | `docs/EVAL_REPORT.md` | Eval |
| 1.14.9 | The Ministry example | `build_plan` dependent lookup | `test_1_14_9_*`, eval `en-01`, `en-02`, `ar-01` | Tested, Eval |

## Component 2: Operational Advisor

| Clause | Requirement (paraphrased) | Code | Test | Status |
|---|---|---|---|---|
| 2.1.3 | No stored formula library | `app/advisor/formula.py` | `test_2_1_3_no_stored_formula_library` | Tested |
| 2.1.6 | No payments; 0.10.7 message | `app/advisor/grade.py` | `test_2_1_6_payment_request` | Tested |
| 2.2.1 | Employee access: TBD | `poc_decisions` in `permission_matrix.yaml` | `test_tbd_cells_are_denied_unless_the_poc_decided_them` | PoC decision |
| 2.2.3 | Admin → 403 | matrix 0.8.2 | `test_2_2_3_admin_cannot_call_advisor` | Tested |
| 2.6.1, 2.6.2 | User formula applied exactly | `parse_formula` (keeps the user's text and brackets) | `test_2_6_1_formula_kept_exactly_as_written`, `test_2_6_*` | Tested |
| 2.6.3 | No formula given → labelled AI-selected definition | `proposed_formula` in `advisor/grade.py` | eval (live only) | Partial |
| 2.7.1 | Same inputs, same result | `app/advisor/evaluate.py` | `test_2_7_1_same_inputs_same_result_20_runs` | Tested |
| 2.7.3 | Full precision, round once | `evaluate`, `round_result` | `test_2_7_3_full_precision_round_final_only` | Tested |
| 2.7.5 | Every figure has a unit | unit algebra in `evaluate.py` | `test_2_7_5_*` | Tested |
| 2.7.6 | Mixed currencies without a rate → Q | `MixedCurrencies` | `test_2_7_6_mixed_currencies_without_rate` | Tested |
| 2.7.7 | No tax rate → "before tax" | `_render_r` notes | `test_2_7_7_money_results_are_labelled_before_tax` | Tested |
| 2.7.8 | Division by zero, negative quantity → M12 | `CalculationError` | `test_2_7_8_*` | Tested |
| 2.7.9 | Booth counts round up, with a note | `round_result` | `test_2_7_9_booths_round_up_with_note` | Tested |
| 2.8 | Every term bound to a verified figure | `app/advisor/bind.py` | `test_2_8_*`, eval "traced" | Tested, Eval |
| 2.8.8 | User value overrides document value, both shown | `bind_terms` | `test_2_8_8_*` | Tested |
| 2.8.12 | M10 after the third Q | | | Designed |
| 2.9.1 | M9 to M12 defined and used | `messages.py`, `advisor/pipeline.py` | `test_2_9_1_*`, `test_1_7_2_a_message_matches_spec` | Tested |
| 2.9.3 | M9 identical whether absent or hidden | RLS before binding | `test_2_9_3_missing_figure_is_m9_whether_absent_or_hidden` | Tested |
| 2.14 | Advisor golden set | `eval/golden_advisor.yaml` | `docs/EVAL_REPORT.md` | Eval |
