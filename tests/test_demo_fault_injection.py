from tollgate.demo_fault_injection import build_scenarios, compare, run_with_gate, run_without_gate


def test_without_gate_every_wrong_fix_becomes_a_bad_outcome():
    scenarios = build_scenarios()
    result = run_without_gate(scenarios)
    wrong_fixes = [s for s in scenarios if not s.is_correct_fix]
    assert result["bad_outcome_count"] == len(wrong_fixes) == 8  # 5 missing_process + 3 confidently_wrong


def test_with_gate_catches_missing_process_but_not_confidently_wrong():
    scenarios = build_scenarios()
    result = run_with_gate(scenarios)
    by_name = {d["name"]: d["outcome"] for d in result["decisions"]}
    assert all(by_name[f"missing-process-{n}"] != "ALLOWED" for n in range(5))
    assert all(by_name[f"confidently-wrong-{n}"] == "ALLOWED" for n in range(3))
    # so: 3 bad outcomes remain (the confidently-wrong ones), down from 8 without the gate
    assert result["bad_outcome_count"] == 3


def test_with_gate_also_blocks_some_legitimate_over_cap_actions_honestly():
    scenarios = build_scenarios()
    result = run_with_gate(scenarios)
    assert len(result["legitimate_actions_blocked"]) == 2
    assert all(n.startswith("legit-but-over-cap") for n in result["legitimate_actions_blocked"])


def test_compare_reports_a_real_reduction_and_states_the_caveat():
    summary = compare()["summary"]
    assert summary["bad_outcomes_without_gate"] == 8
    assert summary["bad_outcomes_with_gate"] == 3
    assert summary["bad_outcomes_prevented"] == 5
    assert summary["legitimate_actions_blocked_by_gate"] == 2
    assert "checks that evidence exists, not that" in summary["caveat"]
