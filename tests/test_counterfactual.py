"""Phase 2 deterministic counterfactual predictor tests."""

from __future__ import annotations

from echolock.counterfactual import predict
from echolock.evaluation import fixed_scenarios
from echolock.isp_generator import generate
from echolock.models import VerdictStatus
from echolock.safety_gate import validate_candidate
from echolock.sdr_engine import compute as compute_sdr
from echolock.simulator import send_state
from echolock.pipeline import run
from echolock.simulator import SimulatorSeed
from echolock.verdict_engine import decide


def _prediction_for(scenario, sealed_command, envelope):
    state = scenario.arrival_state
    sdr = compute_sdr(sealed_command, envelope, send_state(), state)
    candidates = generate(sealed_command, envelope)
    validated = [validate_candidate(c, envelope, sealed_command, state) for c in candidates]
    verdict = decide(sealed_command, envelope, state, sdr, validated)
    return verdict, predict(sealed_command, envelope, state, verdict)


def test_predictor_always_returns_three_ordered_branches(sealed_command, envelope):
    verdict, bundle = _prediction_for(fixed_scenarios()[0], sealed_command, envelope)
    assert verdict.verdict == VerdictStatus.EXECUTE
    assert [b.strategy for b in bundle.branches] == [
        "FORCE_ORIGINAL", "REJECT_ENTIRELY", "ECHOLOCK_VERIFIED"
    ]


def test_force_original_exposes_low_battery_violation(sealed_command, envelope):
    scenario = next(s for s in fixed_scenarios() if s.scenario_id == "ADAPT-01")
    verdict, bundle = _prediction_for(scenario, sealed_command, envelope)
    force, reject, verified = bundle.branches
    assert verdict.verdict == VerdictStatus.ADAPT
    assert "HI-1" in force.safety_violations
    assert reject.scientific_value == 0.0
    assert reject.safety_violations == []
    assert verified.safety_violations == []
    assert verified.goal_preservation_score >= 0.70
    assert verified.final_battery_pct >= envelope.battery_floor_pct


def test_defer_uses_future_comm_window_without_violation(sealed_command, envelope):
    scenario = next(s for s in fixed_scenarios() if s.scenario_id == "DEFER-02")
    verdict, bundle = _prediction_for(scenario, sealed_command, envelope)
    assert verdict.verdict == VerdictStatus.DEFER
    assert "HI-COMM" in bundle.branches[0].safety_violations
    assert bundle.branches[2].predicted_comm_window_used is True
    assert bundle.branches[2].safety_violations == []


def test_reject_branch_preserves_resources(sealed_command, envelope):
    scenario = next(s for s in fixed_scenarios() if s.scenario_id == "REJECT-01")
    verdict, bundle = _prediction_for(scenario, sealed_command, envelope)
    force, reject, verified = bundle.branches
    assert verdict.verdict == VerdictStatus.REJECT
    assert "HI-2" in force.safety_violations
    assert reject.final_battery_pct == scenario.arrival_state.battery_soc
    assert verified.final_battery_pct == scenario.arrival_state.battery_soc
    assert verified.scientific_value == 0.0


def test_boundary_exact_temperature_ceiling_is_safe(sealed_command, envelope):
    base = fixed_scenarios()[0]
    scenario = base.model_copy(update={
        "arrival_state": base.arrival_state.model_copy(update={"equipment_temp_c": 75.0})
    })
    verdict, bundle = _prediction_for(scenario, sealed_command, envelope)
    assert verdict.verdict == VerdictStatus.EXECUTE
    assert "HI-2" not in bundle.branches[0].safety_violations


def test_predictor_is_bitwise_reproducible(sealed_command, envelope):
    scenario = next(s for s in fixed_scenarios() if s.scenario_id == "ADAPT-07")
    verdict_a, bundle_a = _prediction_for(scenario, sealed_command, envelope)
    verdict_b, bundle_b = _prediction_for(scenario, sealed_command, envelope)
    assert verdict_a.verdict == verdict_b.verdict
    assert bundle_a.model_dump(mode="json", exclude={"command_id"}) == bundle_b.model_dump(
        mode="json", exclude={"command_id"}
    )


def test_canonical_pipeline_is_end_to_end_for_all_four_verdicts(sealed_command, envelope):
    expected = {
        SimulatorSeed.NOMINAL: VerdictStatus.EXECUTE,
        SimulatorSeed.LOW_BATTERY: VerdictStatus.ADAPT,
        SimulatorSeed.COMM_LOSS: VerdictStatus.DEFER,
        SimulatorSeed.OVERHEAT: VerdictStatus.REJECT,
    }
    for seed, verdict in expected.items():
        certificate = run(sealed_command, envelope, seed=seed, record_audit=False)
        assert certificate.verdict == verdict
        assert certificate.counterfactual is not None
        assert len(certificate.counterfactual.branches) == 3
        assert certificate.verify_hash()


def test_counterfactual_tamper_invalidates_certificate(sealed_command, envelope):
    certificate = run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)
    assert certificate.counterfactual is not None
    changed_branch = certificate.counterfactual.branches[0].model_copy(
        update={"final_battery_pct": 99.0}
    )
    changed_bundle = certificate.counterfactual.model_copy(
        update={"branches": [changed_branch, *certificate.counterfactual.branches[1:]]}
    )
    tampered = certificate.model_copy(update={"counterfactual": changed_bundle})
    assert not tampered.verify_hash()
    assert not tampered.verify_semantic_replay_hash()
