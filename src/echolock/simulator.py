"""
SpacecraftStateSimulator — deterministic seed-based state evolution.

Produces StateSnapshot pairs (send-time expected state, arrival-time actual state)
for the four canonical EchoLock demo seeds.

All physics are deliberately simplified toy models.
This is a proof-of-concept simulator — NOT flight-accurate.

Design rule: no AI dependency.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum

from .models import (
    CommWindowStatus,
    EmergencyBeaconStatus,
    ImageResolution,
    StateSnapshot,
)

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Seed definitions
# ---------------------------------------------------------------------------


class SimulatorSeed(str, Enum):
    """The four canonical scenario seeds."""

    NOMINAL = "NOMINAL"
    LOW_BATTERY = "LOW_BATTERY"
    OVERHEAT = "OVERHEAT"
    COMM_LOSS = "COMM_LOSS"


# ---------------------------------------------------------------------------
# Seed parameters — all values deterministic and hardcoded
# ---------------------------------------------------------------------------

# Delay between send time and arrival time in minutes
_COMM_DELAY_MINUTES = 14.0  # representative Earth–Mars one-way light-time (minutes)

# Base timestamps fixed so every test run is identical
_SEND_TIME = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)
_INTENDED_EXEC = _SEND_TIME + timedelta(minutes=_COMM_DELAY_MINUTES)
_ARRIVAL_TIME = _SEND_TIME + timedelta(minutes=_COMM_DELAY_MINUTES)
_EXPIRES_AT = _SEND_TIME + timedelta(minutes=_COMM_DELAY_MINUTES + 60)


def base_timestamps() -> dict[str, datetime]:
    """Return the fixed timestamps used by all seeds."""
    return {
        "sent_at": _SEND_TIME,
        "arrived_at": _ARRIVAL_TIME,
        "intended_execution_at": _INTENDED_EXEC,
        "expires_at": _EXPIRES_AT,
    }


# ---------------------------------------------------------------------------
# Send-time expected state (same for all seeds — operator's assumption)
# ---------------------------------------------------------------------------

def send_state() -> StateSnapshot:
    """The spacecraft state the operator assumed when writing the command."""
    return StateSnapshot(
        battery_soc=85.0,
        equipment_temp_c=42.0,
        comm_window_status=CommWindowStatus.OPEN,
        next_comm_window_open=None,
        emergency_beacon=EmergencyBeaconStatus.ACTIVE,
        stored_image_count=0,
        transmission_power_pct=100.0,
        available_resolution=ImageResolution.K4,
        timestamp=_SEND_TIME,
    )


# ---------------------------------------------------------------------------
# Arrival-time actual states per seed
# ---------------------------------------------------------------------------

def arrival_state(seed: SimulatorSeed) -> StateSnapshot:
    """Return the arrival-time spacecraft state for the given seed."""
    if seed == SimulatorSeed.NOMINAL:
        return _nominal_arrival()
    if seed == SimulatorSeed.LOW_BATTERY:
        return _low_battery_arrival()
    if seed == SimulatorSeed.OVERHEAT:
        return _overheat_arrival()
    if seed == SimulatorSeed.COMM_LOSS:
        return _comm_loss_arrival()
    raise ValueError(f"Unknown seed: {seed}")  # pragma: no cover


def _nominal_arrival() -> StateSnapshot:
    """NOMINAL — all assumptions valid; EXECUTE expected."""
    return StateSnapshot(
        battery_soc=83.0,        # slight drain during comm delay, well above 20 % floor
        equipment_temp_c=43.5,   # within 75 °C ceiling
        comm_window_status=CommWindowStatus.OPEN,
        next_comm_window_open=None,
        emergency_beacon=EmergencyBeaconStatus.ACTIVE,
        stored_image_count=0,
        transmission_power_pct=100.0,
        available_resolution=ImageResolution.K4,
        timestamp=_ARRIVAL_TIME,
    )


def _low_battery_arrival() -> StateSnapshot:
    """LOW_BATTERY — battery has drained; original command would violate HI-1; ADAPT expected."""
    return StateSnapshot(
        battery_soc=28.0,        # executing 10 images at full power costs ~12 % → post = 16 % < 20 %
        equipment_temp_c=44.0,
        comm_window_status=CommWindowStatus.OPEN,
        next_comm_window_open=None,
        emergency_beacon=EmergencyBeaconStatus.ACTIVE,
        stored_image_count=0,
        transmission_power_pct=100.0,
        available_resolution=ImageResolution.K4,
        timestamp=_ARRIVAL_TIME,
    )


def _overheat_arrival() -> StateSnapshot:
    """OVERHEAT — temperature at HI-2 limit; no patch can cool equipment; REJECT expected."""
    return StateSnapshot(
        battery_soc=75.0,
        equipment_temp_c=76.5,   # already above 75 °C ceiling
        comm_window_status=CommWindowStatus.OPEN,
        next_comm_window_open=None,
        emergency_beacon=EmergencyBeaconStatus.ACTIVE,
        stored_image_count=0,
        transmission_power_pct=100.0,
        available_resolution=ImageResolution.K4,
        timestamp=_ARRIVAL_TIME,
    )


def _comm_loss_arrival() -> StateSnapshot:
    """COMM_LOSS — communication window closed; next window opens within 45-minute delay; DEFER expected."""
    next_window = _ARRIVAL_TIME + timedelta(minutes=30)
    return StateSnapshot(
        battery_soc=80.0,
        equipment_temp_c=43.0,
        comm_window_status=CommWindowStatus.CLOSED,
        next_comm_window_open=next_window,
        emergency_beacon=EmergencyBeaconStatus.ACTIVE,
        stored_image_count=0,
        transmission_power_pct=100.0,
        available_resolution=ImageResolution.K4,
        timestamp=_ARRIVAL_TIME,
    )
