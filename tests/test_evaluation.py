"""Phase 2 fixed evaluation-harness tests."""

from __future__ import annotations

import json

from echolock.evaluation import evaluate, fixed_scenarios, run_scenario, write_results
from echolock.models import VerdictStatus


def test_fixed_dataset_has_exactly_60_unique_balanced_scenarios():
    scenarios = fixed_scenarios()
    assert len(scenarios) == 60
    assert len({s.scenario_id for s in scenarios}) == 60
    assert {
        verdict: sum(s.expected_verdict == verdict for s in scenarios)
        for verdict in VerdictStatus
    } == {verdict: 15 for verdict in VerdictStatus}


def test_every_scenario_matches_expected_verdict_and_integrity():
    results, _ = evaluate()
    assert all(result.verdict_matches for result in results)
    assert all(result.certificate_valid for result in results)
    assert all(result.semantic_replay_valid for result in results)


def test_required_metrics_meet_phase2_expectations():
    _, summary = evaluate()
    assert summary.verdict_counts == {verdict.value: 15 for verdict in VerdictStatus}
    assert summary.safety_violation_rate == 0.0
    assert summary.unsafe_command_interception_recall == 1.0
    assert summary.safe_command_false_rejection_rate == 0.0
    assert 0.0 <= summary.mean_goal_preservation_score <= 1.0
    assert summary.mean_resource_margin_pct >= 0.0
    assert summary.adaptation_success_rate == 1.0
    assert summary.mean_decision_latency_ms >= 0.0
    assert summary.deterministic_replay_consistency == 1.0


def test_scenario_semantic_replay_is_stable_but_self_hash_is_unique():
    scenario = fixed_scenarios()[17]
    first = run_scenario(scenario)
    second = run_scenario(scenario)
    assert first.semantic_replay_hash == second.semantic_replay_hash
    assert first.certificate_hash != second.certificate_hash


def test_machine_readable_outputs_and_markdown(tmp_path):
    summary = write_results(tmp_path)
    jsonl = tmp_path / "phase2-results.jsonl"
    summary_json = tmp_path / "phase2-summary.json"
    report = tmp_path / "phase2-report.md"
    rows = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 60
    assert json.loads(summary_json.read_text(encoding="utf-8"))["scenario_count"] == 60
    text = report.read_text(encoding="utf-8")
    assert "Unsafe-command interception recall" in text
    assert "Deterministic replay consistency" in text
    assert summary.scenario_count == 60
