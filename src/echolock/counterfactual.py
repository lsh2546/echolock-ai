"""Deterministic three-branch counterfactual predictor.

The predictor is explanatory only. It never changes a SafetyGate result or verdict.
Physics are deliberately conservative toy models and are not flight-qualified.
"""

from __future__ import annotations

from datetime import timedelta

from .models import (
    CounterfactualBranch,
    CounterfactualBundle,
    EmergencyBeaconStatus,
    ImageResolution,
    MissionIntentEnvelope,
    PatchCandidate,
    RawCommand,
    StateSnapshot,
    VerdictStatus,
)
from .safety_gate import estimate_battery_cost
from .verdict_engine import VerdictResult

_QUALITY = {ImageResolution.K4: 1.0, ImageResolution.P1080: 0.6}


def _outcome(
    strategy: str,
    command: RawCommand,
    envelope: MissionIntentEnvelope,
    state: StateSnapshot,
    patch: PatchCandidate | None,
    *,
    execute: bool,
    available: bool = True,
    gps: float = 0.0,
    notes: str = "",
) -> CounterfactualBranch:
    if not execute:
        return CounterfactualBranch(
            strategy=strategy,
            predicted_battery_after_pct=state.battery_soc,
            predicted_temp_after_c=state.equipment_temp_c,
            predicted_images_transmitted=0,
            predicted_comm_window_used=False,
            predicted_gps=0.0,
            scientific_value=0.0,
            final_battery_pct=state.battery_soc,
            maximum_temp_c=state.equipment_temp_c,
            safety_violations=[],
            goal_preservation_score=0.0,
            available=available,
            notes=notes,
        )

    images = patch.adapted_image_count if patch and patch.adapted_image_count is not None else command.image_count
    resolution = patch.adapted_resolution if patch and patch.adapted_resolution is not None else command.requested_resolution
    power = patch.adapted_power_pct if patch and patch.adapted_power_pct is not None else command.requested_power_pct
    batches = patch.batch_count if patch else 1
    delay = patch.delay_minutes if patch else 0.0
    drain = estimate_battery_cost(images, resolution.value, power, batches)
    final_battery = round(state.battery_soc - drain, 4)
    execution_time = state.timestamp + timedelta(minutes=delay)
    comm_open = state.comm_window_status.value == "OPEN" or (
        state.next_comm_window_open is not None and execution_time >= state.next_comm_window_open
    )
    violations = []
    if final_battery < envelope.battery_floor_pct:
        violations.append("HI-1")
    if state.equipment_temp_c > envelope.max_equipment_temp_c:
        violations.append("HI-2")
    if state.emergency_beacon == EmergencyBeaconStatus.INACTIVE:
        violations.append("HI-3")
    if execution_time > envelope.expires_at:
        violations.append("HI-4")
    if not comm_open:
        violations.append("HI-COMM")
    science = round((images / command.image_count) * _QUALITY[resolution], 4)
    return CounterfactualBranch(
        strategy=strategy,
        predicted_battery_after_pct=final_battery,
        predicted_temp_after_c=state.equipment_temp_c,
        predicted_images_transmitted=images,
        predicted_comm_window_used=comm_open,
        predicted_gps=round(gps, 4),
        scientific_value=science,
        final_battery_pct=final_battery,
        maximum_temp_c=state.equipment_temp_c,
        safety_violations=violations,
        goal_preservation_score=round(gps, 4),
        available=available,
        notes=notes,
    )


def predict(
    command: RawCommand,
    envelope: MissionIntentEnvelope,
    arrival_state: StateSnapshot,
    verdict_result: VerdictResult,
) -> CounterfactualBundle:
    """Compare force-original, reject-entirely, and EchoLock verified action."""
    force = _outcome(
        "FORCE_ORIGINAL", command, envelope, arrival_state, None,
        execute=True, gps=1.0, notes="Force the unmodified command at arrival.",
    )
    reject = _outcome(
        "REJECT_ENTIRELY", command, envelope, arrival_state, None,
        execute=False, notes="Reject without executing the science command.",
    )
    winner = verdict_result.winning_candidate
    if verdict_result.verdict == VerdictStatus.EXECUTE:
        verified = _outcome(
            "ECHOLOCK_VERIFIED", command, envelope, arrival_state, None,
            execute=True, gps=1.0, notes="Original command verified safe.",
        )
    elif verdict_result.verdict in (VerdictStatus.ADAPT, VerdictStatus.DEFER) and winner is not None:
        verified = _outcome(
            "ECHOLOCK_VERIFIED", command, envelope, arrival_state, winner.candidate,
            execute=True, gps=winner.eligibility_gps,
            notes=f"Verified {verdict_result.verdict.value.lower()} action.",
        )
    else:
        verified = _outcome(
            "ECHOLOCK_VERIFIED", command, envelope, arrival_state, None,
            execute=False, available=verdict_result.verdict == VerdictStatus.REJECT,
            notes="No verified executable adaptation; command rejected.",
        )
    return CounterfactualBundle(
        command_id=command.command_id,
        arrival_state_timestamp=arrival_state.timestamp,
        branches=[force, reject, verified],
    )
