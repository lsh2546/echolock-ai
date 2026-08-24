"""
tests/test_models.py

Unit tests for all Pydantic v2 data models.
Covers schema validation, field types, and timezone enforcement.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from echolock.models import (
    AdaptationAuthority,
    CommWindowStatus,
    DeltaCertificate,
    EmergencyBeaconStatus,
    ImageResolution,
    MissionIntentEnvelope,
    RawCommand,
    StateSnapshot,
    VerdictStatus,
)
from echolock.simulator import base_timestamps

UTC = timezone.utc


# ---------------------------------------------------------------------------
# StateSnapshot
# ---------------------------------------------------------------------------


def test_state_snapshot_valid() -> None:
    ts = base_timestamps()
    snap = StateSnapshot(
        battery_soc=85.0,
        equipment_temp_c=42.0,
        comm_window_status=CommWindowStatus.OPEN,
        emergency_beacon=EmergencyBeaconStatus.ACTIVE,
        stored_image_count=0,
        transmission_power_pct=100.0,
        available_resolution=ImageResolution.K4,
        timestamp=ts["sent_at"],
    )
    assert snap.battery_soc == 85.0
    assert snap.comm_window_status == CommWindowStatus.OPEN


def test_state_snapshot_battery_bounds() -> None:
    ts = base_timestamps()
    with pytest.raises(ValidationError):
        StateSnapshot(
            battery_soc=101.0,  # invalid
            equipment_temp_c=42.0,
            comm_window_status=CommWindowStatus.OPEN,
            emergency_beacon=EmergencyBeaconStatus.ACTIVE,
            stored_image_count=0,
            transmission_power_pct=100.0,
            available_resolution=ImageResolution.K4,
            timestamp=ts["sent_at"],
        )


def test_state_snapshot_closed_window_requires_next_open() -> None:
    ts = base_timestamps()
    with pytest.raises(ValidationError):
        StateSnapshot(
            battery_soc=80.0,
            equipment_temp_c=42.0,
            comm_window_status=CommWindowStatus.CLOSED,
            next_comm_window_open=None,  # must be set when CLOSED
            emergency_beacon=EmergencyBeaconStatus.ACTIVE,
            stored_image_count=0,
            transmission_power_pct=100.0,
            available_resolution=ImageResolution.K4,
            timestamp=ts["sent_at"],
        )


def test_state_snapshot_is_frozen(sealed_command, envelope) -> None:
    from echolock.simulator import send_state
    snap = send_state()
    with pytest.raises(Exception):  # frozen model
        snap.battery_soc = 50.0  # type: ignore[misc]


def test_raw_command_is_frozen(sealed_command) -> None:
    with pytest.raises(Exception):
        sealed_command.image_count = 5  # type: ignore[misc]


def test_mie_weights_must_sum_to_one() -> None:
    ts = base_timestamps()
    with pytest.raises(ValidationError):
        MissionIntentEnvelope(
            goal="Test",
            intended_execution_at=ts["intended_execution_at"],
            expires_at=ts["expires_at"],
            gps_weight_scientific_utility=0.60,
            gps_weight_output_quantity=0.25,
            gps_weight_timeliness=0.15,
            gps_weight_operator_preferences=0.10,  # sum = 1.10 → invalid
        )


def test_mie_expiry_must_be_after_execution() -> None:
    ts = base_timestamps()
    with pytest.raises(ValidationError):
        MissionIntentEnvelope(
            goal="Test",
            intended_execution_at=ts["expires_at"],   # swapped
            expires_at=ts["intended_execution_at"],   # earlier than execution
        )


def test_adaptation_authority_min_images_floor() -> None:
    with pytest.raises(ValidationError):
        AdaptationAuthority(min_images=2)  # must be >= 3


def test_adaptation_authority_power_floor() -> None:
    with pytest.raises(ValidationError):
        AdaptationAuthority(min_transmission_power_pct=39.0)  # must be >= 40


def test_raw_command_timestamps_require_timezone() -> None:
    ts = base_timestamps()
    naive = datetime(2026, 8, 23, 12, 0, 0)  # no tzinfo
    with pytest.raises(ValidationError):
        RawCommand(
            description="test",
            image_count=5,
            sent_at=naive,
            arrived_at=ts["arrived_at"],
            intended_execution_at=ts["intended_execution_at"],
            expires_at=ts["expires_at"],
        )
