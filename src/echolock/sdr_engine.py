"""
SDREngine — State Drift Report computation.

Compares the operator's send-time assumptions (from MissionIntentEnvelope)
against the actual arrival-time StateSnapshot, field by field.

Tags each delta as:
  VIOLATED_INVARIANT — a hard invariant boundary has been crossed
  BROKEN_ASSUMPTION  — a soft assumption is no longer true, but no HI is violated

Design rule: no AI dependency.
"""

from __future__ import annotations

from datetime import timezone

from .models import (
    CommWindowStatus,
    DriftEntry,
    DriftSeverity,
    EmergencyBeaconStatus,
    MissionIntentEnvelope,
    RawCommand,
    StateSnapshot,
    StateDriftReport,
)

UTC = timezone.utc


def compute(
    command: RawCommand,
    envelope: MissionIntentEnvelope,
    send_snapshot: StateSnapshot,
    arrival_snapshot: StateSnapshot,
) -> StateDriftReport:
    """Compute the State Drift Report for one command.

    Args:
        command:          The sealed original command.
        envelope:         The Mission Intent Envelope with hard invariants.
        send_snapshot:    Spacecraft state when the command was transmitted.
        arrival_snapshot: Spacecraft state when the command arrived.

    Returns:
        A StateDriftReport with all field-level deltas tagged by severity.
    """
    deltas: list[DriftEntry] = []

    # --- HI-1: Battery floor ---
    if arrival_snapshot.battery_soc < envelope.battery_floor_pct:
        deltas.append(
            DriftEntry(
                field="battery_soc",
                expected_value=send_snapshot.battery_soc,
                actual_value=arrival_snapshot.battery_soc,
                severity=DriftSeverity.VIOLATED_INVARIANT,
                impact_description=(
                    f"Battery {arrival_snapshot.battery_soc:.1f} % is already below "
                    f"the {envelope.battery_floor_pct:.0f} % hard floor before execution."
                ),
            )
        )
    elif arrival_snapshot.battery_soc != send_snapshot.battery_soc:
        deltas.append(
            DriftEntry(
                field="battery_soc",
                expected_value=send_snapshot.battery_soc,
                actual_value=arrival_snapshot.battery_soc,
                severity=DriftSeverity.BROKEN_ASSUMPTION,
                impact_description=(
                    f"Battery drifted from {send_snapshot.battery_soc:.1f} % to "
                    f"{arrival_snapshot.battery_soc:.1f} %; still above hard floor."
                ),
            )
        )

    # --- HI-2: Temperature ceiling ---
    if arrival_snapshot.equipment_temp_c > envelope.max_equipment_temp_c:
        deltas.append(
            DriftEntry(
                field="equipment_temp_c",
                expected_value=send_snapshot.equipment_temp_c,
                actual_value=arrival_snapshot.equipment_temp_c,
                severity=DriftSeverity.VIOLATED_INVARIANT,
                impact_description=(
                    f"Equipment temperature {arrival_snapshot.equipment_temp_c:.1f} °C "
                    f"exceeds the {envelope.max_equipment_temp_c:.0f} °C hard ceiling."
                ),
            )
        )
    elif arrival_snapshot.equipment_temp_c != send_snapshot.equipment_temp_c:
        deltas.append(
            DriftEntry(
                field="equipment_temp_c",
                expected_value=send_snapshot.equipment_temp_c,
                actual_value=arrival_snapshot.equipment_temp_c,
                severity=DriftSeverity.BROKEN_ASSUMPTION,
                impact_description=(
                    f"Temperature drifted from {send_snapshot.equipment_temp_c:.1f} °C to "
                    f"{arrival_snapshot.equipment_temp_c:.1f} °C; within ceiling."
                ),
            )
        )

    # --- HI-3: Emergency beacon continuity ---
    if arrival_snapshot.emergency_beacon == EmergencyBeaconStatus.INACTIVE:
        deltas.append(
            DriftEntry(
                field="emergency_beacon",
                expected_value=send_snapshot.emergency_beacon,
                actual_value=arrival_snapshot.emergency_beacon,
                severity=DriftSeverity.VIOLATED_INVARIANT,
                impact_description="Emergency beacon is INACTIVE — hard invariant violated.",
            )
        )

    # --- HI-4: Command expiry ---
    exec_time = arrival_snapshot.timestamp
    if exec_time > envelope.expires_at:
        deltas.append(
            DriftEntry(
                field="expires_at",
                expected_value=str(envelope.expires_at),
                actual_value=str(exec_time),
                severity=DriftSeverity.VIOLATED_INVARIANT,
                impact_description=(
                    f"Command arrived at {exec_time.isoformat()} which is after "
                    f"expiration {envelope.expires_at.isoformat()}."
                ),
            )
        )

    # --- Soft assumption: communication window ---
    if arrival_snapshot.comm_window_status != send_snapshot.comm_window_status:
        deltas.append(
            DriftEntry(
                field="comm_window_status",
                expected_value=send_snapshot.comm_window_status,
                actual_value=arrival_snapshot.comm_window_status,
                severity=DriftSeverity.BROKEN_ASSUMPTION,
                impact_description=(
                    f"Communication window changed from {send_snapshot.comm_window_status} "
                    f"to {arrival_snapshot.comm_window_status}."
                ),
            )
        )

    # --- Soft assumption: transmission power ---
    if arrival_snapshot.transmission_power_pct != send_snapshot.transmission_power_pct:
        deltas.append(
            DriftEntry(
                field="transmission_power_pct",
                expected_value=send_snapshot.transmission_power_pct,
                actual_value=arrival_snapshot.transmission_power_pct,
                severity=DriftSeverity.BROKEN_ASSUMPTION,
                impact_description=(
                    f"Transmission power changed from "
                    f"{send_snapshot.transmission_power_pct:.0f} % to "
                    f"{arrival_snapshot.transmission_power_pct:.0f} %."
                ),
            )
        )

    return StateDriftReport(
        command_id=command.command_id,
        send_state_timestamp=send_snapshot.timestamp,
        arrival_state_timestamp=arrival_snapshot.timestamp,
        deltas=deltas,
    )
