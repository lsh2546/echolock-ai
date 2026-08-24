"""Local demo facade for the deterministic EchoLock pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from . import command_sealer, mie_sealer
from .certificate_builder import get_audit_log, verify_log_chain
from .models import AdaptationAuthority, ImageResolution, MissionIntentEnvelope, RawCommand
from .pipeline import run
from .simulator import SimulatorSeed, arrival_state, base_timestamps

SCENARIO_COPY = {
    SimulatorSeed.NOMINAL: {
        "title": "Clear channel",
        "summary": "Arrival state remains safe. EchoLock releases the original command unchanged.",
    },
    SimulatorSeed.LOW_BATTERY: {
        "title": "Battery drift",
        "summary": "The original transmission would breach reserve power. EchoLock applies a verified patch.",
    },
    SimulatorSeed.COMM_LOSS: {
        "title": "Window closed",
        "summary": "The radio window is unavailable. EchoLock defers until the next safe opportunity.",
    },
    SimulatorSeed.OVERHEAT: {
        "title": "Thermal redline",
        "summary": "Equipment is already above its hard ceiling. No authorised patch can make execution safe.",
    },
}


def demo_inputs() -> tuple[RawCommand, MissionIntentEnvelope]:
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


def scenario_catalog() -> list[dict]:
    return [
        {"id": seed.value, "expected_verdict": verdict, **SCENARIO_COPY[seed]}
        for seed, verdict in (
            (SimulatorSeed.NOMINAL, "EXECUTE"),
            (SimulatorSeed.LOW_BATTERY, "ADAPT"),
            (SimulatorSeed.COMM_LOSS, "DEFER"),
            (SimulatorSeed.OVERHEAT, "REJECT"),
        )
    ]


def run_demo(seed: SimulatorSeed) -> dict:
    command, envelope = demo_inputs()
    certificate = run(command, envelope, seed=seed, record_audit=True)
    state = arrival_state(seed)
    patch = certificate.applied_patch
    result = {
        "scenario": {"id": seed.value, **SCENARIO_COPY[seed]},
        "verdict": certificate.verdict.value,
        "precedence_step": certificate.verdict_precedence_step,
        "arrival_state": state.model_dump(mode="json"),
        "original_command": command.model_dump(mode="json"),
        "intent_envelope": envelope.model_dump(mode="json"),
        "state_drift": certificate.sdr_summary.model_dump(mode="json"),
        "applied_patch": patch.model_dump(mode="json") if patch else None,
        "goal_preservation_score": certificate.gps,
        "counterfactual": certificate.counterfactual.model_dump(mode="json") if certificate.counterfactual else None,
        "certificate": certificate.model_dump(mode="json"),
        "integrity": {
            "certificate_hash_valid": certificate.verify_hash(),
            "semantic_replay_hash_valid": certificate.verify_semantic_replay_hash(),
            "mie_seal_present": bool(envelope.mie_fingerprint),
            "command_seal_present": bool(command.fingerprint),
        },
    }
    return result


def audit_snapshot() -> dict:
    valid, reason = verify_log_chain()
    return {
        "chain_valid": valid,
        "reason": reason,
        "entries": [entry.model_dump(mode="json") for entry in get_audit_log()],
        "known_limitation": "In-memory PoC chain; tail truncation requires a persisted trusted-head anchor.",
    }


def evaluation_summary() -> dict:
    path = Path(__file__).resolve().parents[2] / "outputs" / "evaluation" / "phase2-summary.json"
    return json.loads(path.read_text(encoding="utf-8"))
