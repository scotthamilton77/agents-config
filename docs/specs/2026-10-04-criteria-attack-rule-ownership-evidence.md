# Evidence

How each criterion in the spec beside this file is discharged. States:
`open`; `test: <file>::<test_fn>`; `probe: <file>::<name>`;
`observed: #<PR> <YYYY-MM-DD> <name>`. A criterion whose own text says it is
verified in a browser cannot be discharged by `test:` — a test that never
opens one proves something else.

- ARO-A1 | test: src/user/.claude/skills/ac-attack/emit_prompts_test.py::test_aro_a1_every_rule_of_the_standard_has_exactly_one_owning_lens
- ARO-A2 | test: src/user/.claude/skills/ac-attack/emit_prompts_test.py::test_aro_a2_the_registry_is_the_four_lenses
- ARO-A3 | test: src/user/.claude/skills/ac-attack/emit_prompts_test.py::test_each_prompt_is_its_lens_its_rules_and_the_shared_template
- ARO-A4 | test: src/user/.claude/skills/ac-attack/emit_prompts_test.py::test_each_prompt_is_its_lens_its_rules_and_the_shared_template
- ARO-A5 | test: src/user/.claude/skills/ac-attack/emit_prompts_test.py::test_c7_a_lens_the_standard_or_its_directory_cannot_serve_is_refused
- ARO-A6 | test: src/user/.claude/skills/ac-attack/check_record_test.py::test_aro_a6_an_objection_short_its_target_its_rule_or_a_scenario_part_is_refused
- ARO-A7 | test: src/user/.claude/skills/ac-attack/check_record_test.py::test_c3_no_object_in_the_record_carries_a_field_the_contract_leaves_undeclared
- ARO-A8 | test: src/user/.claude/skills/ac-attack/check_record_test.py::test_aro_a8_workings_missing_or_failing_their_schema_leave_the_round_open
- ARO-A9 | test: src/user/.claude/skills/ac-attack/check_record_test.py::test_an_undischarged_part_needs_an_objection_naming_it
- ARO-A10 | test: src/user/.claude/skills/ac-attack/check_record_test.py::test_an_objection_on_a_rule_its_lens_does_not_enforce_is_refused
- ARO-A11 | test: src/user/.claude/skills/ac-attack/emit_prompts_test.py::test_aro_a11_each_prompt_carries_exactly_the_rules_its_lens_owns
- ARO-A12 | test: src/user/.claude/skills/ac-attack/emit_prompts_test.py::test_aro_a12_a_round_names_the_four_lenses_and_writes_one_prompt_for_each
- ARO-A13 | test: src/user/.claude/skills/ac-attack/check_record_test.py::test_c7_a_lens_that_did_not_report_leaves_the_round_unfinished
- ARO-A14 | test: src/user/.claude/skills/ac-attack/check_record_test.py::test_aro_a14_an_objection_under_any_rule_its_owning_lens_holds_closes_the_round
- ARO-A15 | test: src/user/.claude/skills/ac-attack/emit_prompts_test.py::test_c7_an_empty_lens_registry_is_refused_not_reported_as_an_emitted_round
- ARO-A16 | test: src/user/.claude/skills/ac-attack/emit_prompts_test.py::test_a_missing_or_empty_standard_refuses_before_writing
- ARO-A17 | test: src/user/.claude/skills/ac-attack/emit_prompts_test.py::test_emission_is_deterministic
- ARO-A18 | open
