"""Deterministic Phase 2 evaluation harness with 60 fixed scenarios.

The state evolution and counterfactual physics are simplified PoC models, not
flight-accurate spacecraft simulation. The measured latency field is observational;
all decisions, hashes, scenario inputs, and non-latency metrics are deterministic.
"""

from __future__ import annotations

import json
import time
from datetime import timedelta
from pathlib import Path
from statistics import mean

from pydantic import BaseModel, ConfigDict

from . import command_sealer, mie_sealer
from .certificate_builder import build
from .counterfactual import predict
from .isp_generator import generate
from .models import (
    AdaptationAuthority,
    CommWindowStatus,
    EmergencyBeaconStatus,
    ImageResolution,
    MissionIntentEnvelope,
    RawCommand,
    StateSnapshot,
    VerdictStatus,
)
from .safety_gate import validate_candidate
from .sdr_engine import compute as compute_sdr
from .simulator import base_timestamps, send_state
from .verdict_engine import decide


class FixedScenario(BaseModel):
    model_config = ConfigDict(frozen=True)
    scenario_id: str
    expected_verdict: VerdictStatus
    arrival_state: StateSnapshot


class EvaluationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    scenario_id: str
    expected_verdict: VerdictStatus
    actual_verdict: VerdictStatus
    verdict_matches: bool
    decision_latency_ms: float
    certificate_hash: str
    semantic_replay_hash: str
    certificate_valid: bool
    semantic_replay_valid: bool
    counterfactual: dict


class EvaluationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    scenario_count: int
    verdict_counts: dict[str, int]
    safety_violation_rate: float
    unsafe_command_interception_recall: float
    safe_command_false_rejection_rate: float
    mean_goal_preservation_score: float
    mean_resource_margin_pct: float
    adaptation_success_rate: float
    mean_decision_latency_ms: float
    deterministic_replay_consistency: float


def _command_and_envelope() -> tuple[RawCommand, MissionIntentEnvelope]:
    ts = base_timestamps()
    command = command_sealer.seal(RawCommand(
        description="Transmit 10 rock images at 4K resolution and high power",
        image_count=10,
        requested_resolution=ImageResolution.K4,
        requested_power_pct=100.0,
        **ts,
    ))
    envelope = mie_sealer.seal(MissionIntentEnvelope(
        goal="Transmit 10 high-quality rock images to Earth for geological analysis",
        send_time_assumptions={
            "battery_soc": 85.0,
            "equipment_temp_c": 42.0,
            "comm_window_status": "OPEN",
            "emergency_beacon": "ACTIVE",
        },
        intended_execution_at=ts["intended_execution_at"],
        expires_at=ts["expires_at"],
        adaptation_authority=AdaptationAuthority(),
    ))
    return command, envelope


def fixed_scenarios() -> list[FixedScenario]:
    """Return 15 fixed scenarios for each verdict, in stable order."""
    timestamp = send_state().timestamp.replace(minute=14)
    scenarios: list[FixedScenario] = []
    for i in range(15):
        scenarios.append(FixedScenario(
            scenario_id=f"EXECUTE-{i + 1:02d}", expected_verdict=VerdictStatus.EXECUTE,
            arrival_state=StateSnapshot(
                battery_soc=78.0 + i * 0.5, equipment_temp_c=40.0 + i * 0.5,
                comm_window_status=CommWindowStatus.OPEN,
                emergency_beacon=EmergencyBeaconStatus.ACTIVE, stored_image_count=i,
                transmission_power_pct=100.0, available_resolution=ImageResolution.K4,
                timestamp=timestamp,
            ),
        ))
        scenarios.append(FixedScenario(
            scenario_id=f"ADAPT-{i + 1:02d}", expected_verdict=VerdictStatus.ADAPT,
            arrival_state=StateSnapshot(
                battery_soc=27.0 + i * 0.2, equipment_temp_c=43.0 + i * 0.2,
                comm_window_status=CommWindowStatus.OPEN,
                emergency_beacon=EmergencyBeaconStatus.ACTIVE, stored_image_count=i,
                transmission_power_pct=100.0, available_resolution=ImageResolution.K4,
                timestamp=timestamp,
            ),
        ))
        window_delay = (15.0, 30.0, 45.0)[i % 3]
        scenarios.append(FixedScenario(
            scenario_id=f"DEFER-{i + 1:02d}", expected_verdict=VerdictStatus.DEFER,
            arrival_state=StateSnapshot(
                battery_soc=76.0 + i * 0.3, equipment_temp_c=41.0 + i * 0.2,
                comm_window_status=CommWindowStatus.CLOSED,
                next_comm_window_open=timestamp + timedelta(minutes=window_delay),
                emergency_beacon=EmergencyBeaconStatus.ACTIVE, stored_image_count=i,
                transmission_power_pct=100.0, available_resolution=ImageResolution.K4,
                timestamp=timestamp,
            ),
        ))
        scenarios.append(FixedScenario(
            scenario_id=f"REJECT-{i + 1:02d}", expected_verdict=VerdictStatus.REJECT,
            arrival_state=StateSnapshot(
                battery_soc=70.0 + i * 0.4, equipment_temp_c=75.1 + i * 0.3,
                comm_window_status=CommWindowStatus.OPEN,
                emergency_beacon=EmergencyBeaconStatus.ACTIVE, stored_image_count=i,
                transmission_power_pct=100.0, available_resolution=ImageResolution.K4,
                timestamp=timestamp,
            ),
        ))
    return scenarios


def run_scenario(scenario: FixedScenario) -> EvaluationResult:
    """Run one complete deterministic EchoLock scenario."""
    command, envelope = _command_and_envelope()
    if not command_sealer.verify(command) or not mie_sealer.verify(envelope):
        raise ValueError("Scenario trust inputs failed seal verification")
    started = time.perf_counter_ns()
    sdr = compute_sdr(command, envelope, send_state(), scenario.arrival_state)
    candidates = generate(command, envelope)
    validated = [
        validate_candidate(candidate, envelope, command, scenario.arrival_state)
        for candidate in candidates
    ]
    verdict = decide(command, envelope, scenario.arrival_state, sdr, validated)
    counterfactual = predict(command, envelope, scenario.arrival_state, verdict)
    certificate = build(
        command, envelope, sdr, verdict, scenario.arrival_state,
        scenario_id=scenario.scenario_id, counterfactual=counterfactual,
    )
    latency_ms = (time.perf_counter_ns() - started) / 1_000_000
    return EvaluationResult(
        scenario_id=scenario.scenario_id,
        expected_verdict=scenario.expected_verdict,
        actual_verdict=certificate.verdict,
        verdict_matches=certificate.verdict == scenario.expected_verdict,
        decision_latency_ms=round(latency_ms, 4),
        certificate_hash=certificate.certificate_hash or "",
        semantic_replay_hash=certificate.semantic_replay_hash or "",
        certificate_valid=certificate.verify_hash(),
        semantic_replay_valid=certificate.verify_semantic_replay_hash(),
        counterfactual=counterfactual.model_dump(mode="json"),
    )


def _branch(result: EvaluationResult, strategy: str) -> dict:
    return next(branch for branch in result.counterfactual["branches"] if branch["strategy"] == strategy)


def evaluate() -> tuple[list[EvaluationResult], EvaluationSummary]:
    scenarios = fixed_scenarios()
    results = [run_scenario(scenario) for scenario in scenarios]
    replay_results = [run_scenario(scenario) for scenario in scenarios]
    force = [_branch(result, "FORCE_ORIGINAL") for result in results]
    echo = [_branch(result, "ECHOLOCK_VERIFIED") for result in results]
    unsafe_indexes = [i for i, branch in enumerate(force) if branch["safety_violations"]]
    safe_indexes = [i for i, branch in enumerate(force) if not branch["safety_violations"]]
    intercepted = sum(results[i].actual_verdict != VerdictStatus.EXECUTE for i in unsafe_indexes)
    false_rejects = sum(results[i].actual_verdict == VerdictStatus.REJECT for i in safe_indexes)
    adapt_indexes = [i for i, s in enumerate(scenarios) if s.expected_verdict == VerdictStatus.ADAPT]
    adapt_success = sum(
        results[i].actual_verdict == VerdictStatus.ADAPT and not echo[i]["safety_violations"]
        for i in adapt_indexes
    )
    replay_matches = sum(
        a.semantic_replay_hash == b.semantic_replay_hash
        for a, b in zip(results, replay_results)
    )
    margins = [branch["final_battery_pct"] - 20.0 for branch in echo if branch["final_battery_pct"] is not None]
    counts = {verdict.value: sum(r.actual_verdict == verdict for r in results) for verdict in VerdictStatus}
    summary = EvaluationSummary(
        scenario_count=len(results), verdict_counts=counts,
        safety_violation_rate=round(sum(bool(b["safety_violations"]) for b in echo) / len(echo), 4),
        unsafe_command_interception_recall=round(intercepted / len(unsafe_indexes), 4),
        safe_command_false_rejection_rate=round(false_rejects / len(safe_indexes), 4),
        mean_goal_preservation_score=round(mean(b["goal_preservation_score"] for b in echo), 4),
        mean_resource_margin_pct=round(mean(margins), 4),
        adaptation_success_rate=round(adapt_success / len(adapt_indexes), 4),
        mean_decision_latency_ms=round(mean(r.decision_latency_ms for r in results), 4),
        deterministic_replay_consistency=round(replay_matches / len(results), 4),
    )
    return results, summary


def write_results(output_dir: Path) -> EvaluationSummary:
    """Write JSONL scenario records, JSON summary, and concise Markdown report."""
    results, summary = evaluate()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "phase2-results.jsonl").write_text(
        "\n".join(result.model_dump_json() for result in results) + "\n", encoding="utf-8"
    )
    (output_dir / "phase2-summary.json").write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown = f"""# EchoLock Phase 2 Evaluation

- Scenarios: {summary.scenario_count} (15 per verdict)
- Verdict counts: {summary.verdict_counts}
- Safety violation rate: {summary.safety_violation_rate:.2%}
- Unsafe-command interception recall: {summary.unsafe_command_interception_recall:.2%}
- Safe-command false rejection rate: {summary.safe_command_false_rejection_rate:.2%}
- Mean goal-preservation score: {summary.mean_goal_preservation_score:.4f}
- Mean battery margin above 20% floor: {summary.mean_resource_margin_pct:.4f} percentage points
- Adaptation success rate: {summary.adaptation_success_rate:.2%}
- Mean measured decision latency: {summary.mean_decision_latency_ms:.4f} ms
- Deterministic replay consistency: {summary.deterministic_replay_consistency:.2%}

The spacecraft physics and thermal behavior are deterministic toy models for a PoC,
not flight-accurate predictions. Measured latency varies by host; decisions and all
non-latency metrics are deterministic.
"""
    (output_dir / "phase2-report.md").write_text(markdown, encoding="utf-8")
    return summary


if __name__ == "__main__":  # pragma: no cover
    write_results(Path("outputs/evaluation"))
