# Evidence

How each criterion in the spec beside this file is discharged. States: `open`;
`test: <file>::<test_fn>`; `probe: <file>::<name>`;
`observed: #<PR> <YYYY-MM-DD> <name>`. A criterion whose own text says it is
verified in a browser is dischargeable by `test:` only where the test drives a
real browser over the real launch path — the end-to-end suite (`make e2e-grillui`)
qualifies; a unit test that never renders the page proves something else, and a
hand probe stays `probe:`.

- PND-A1 | test: packages/grillui/tests/e2e/test_tasks.py::test_pnd_a1_a_decision_a_ruling_is_weighing_waits_on_the_board_and_says_on_what
- PND-A1 | test: packages/grillui/tests/unit/test_tasks.py::test_pnd_a1_a_marked_answer_records_a_task_per_target_and_each_target_waits
- PND-A1 | test: packages/grillui/tests/unit/test_tasks.py::test_pnd_a1_an_option_with_no_mark_records_no_task
- PND-A1 | test: packages/grillui/tests/unit/test_tasks.py::test_pnd_a1_a_mark_naming_a_dead_or_absent_decision_records_nothing
- PND-A1 | test: packages/grillui/tests/unit/test_tasks.py::test_pnd_a1_a_restart_keeps_the_waiting_field_and_fails_the_dead_task
- PND-A2 | open
- PND-A3 | test: packages/grillui/tests/e2e/test_tasks.py::test_pnd_a3_a_later_answer_takes_the_ruling_over_and_the_earlier_result_is_dropped
- PND-A3 | test: packages/grillui/tests/unit/test_tasks.py::test_pnd_a3_a_second_gesture_supersedes_the_live_task_and_its_result_is_dropped
- PND-A3 | test: packages/grillui/tests/unit/test_tasks.py::test_pnd_a3_two_gestures_in_one_batch_leave_one_live_task_per_target
- PND-A4 | test: packages/grillui/tests/e2e/test_result_scope.py::test_pnd_a4_a_ruling_lands_on_its_target_and_queues_the_rest_with_before_and_after
- PND-A4 | test: packages/grillui/tests/unit/test_result_scope.py::test_pnd_a4_a_result_invalidating_its_own_target_lands_without_the_human
- PND-A4 | test: packages/grillui/tests/unit/test_result_scope.py::test_pnd_a4_a_result_reaching_past_its_target_waits_in_the_inbox
- PND-A4 | test: packages/grillui/tests/unit/test_result_scope.py::test_pnd_a4_a_revise_supplying_no_structural_field_is_refused_at_the_document_gate
- PND-A4 | test: packages/grillui/tests/unit/test_result_scope.py::test_pnd_a4_an_empty_revise_never_reaches_the_inbox_and_its_retry_quotes_the_fault
- PND-A4 | test: packages/grillui/tests/unit/test_result_scope.py::test_pnd_a4_a_revise_supplying_only_prereqs_is_a_structural_change
- PND-A5 | open
- PND-A6 | open
- PND-A7 | open
- PND-A8 | open
- PND-A9 | open
- PND-A10 | open
- PND-A11 | open
- PND-A12 | test: packages/grillui/tests/e2e/test_result_scope.py::test_pnd_a12_with_the_switch_off_a_qualifying_proposal_waits_in_the_inbox
- PND-A12 | test: packages/grillui/tests/e2e/test_result_scope.py::test_pnd_a12_with_the_switch_on_a_qualifying_proposal_is_applied_as_the_switchs
- PND-A12 | test: packages/grillui/tests/e2e/test_result_scope.py::test_pnd_a12_a_proposal_touching_an_answer_or_carrying_an_unsettle_waits_either_way
- PND-A12 | test: packages/grillui/tests/unit/test_result_scope.py::test_pnd_a12_an_apply_made_by_the_preference_replays_as_the_same_board
- PND-A13 | test: packages/grillui/tests/e2e/test_seat_failure.py::test_pnd_a13_a_turn_no_seat_answers_leaves_a_trace_naming_each_seat_and_cause
- PND-A13 | test: packages/grillui/tests/e2e/test_seat_failure.py::test_pnd_a13_a_map_seat_that_times_out_is_handed_up_and_the_page_says_so
- PND-A13 | test: packages/grillui/tests/unit/test_seat_failure.py::test_pnd_a13_every_cell_of_the_two_seat_ladder_traces_each_seat_and_closes_honestly
- PND-A14 | open
- PND-A15 | test: packages/grillui/tests/unit/test_tasks.py::test_pnd_a15_a_superseded_task_is_closed_by_the_superseding_accepted_entry
- PND-A15 | test: packages/grillui/tests/unit/test_tasks.py::test_pnd_a15_a_restart_after_a_supersession_shows_the_task_superseded
- PND-A15 | test: packages/grillui/tests/unit/test_tasks.py::test_pnd_a15_a_restart_closes_each_overlapping_map_turn_with_its_own_entry
