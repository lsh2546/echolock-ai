"""
Shared test fixtures for EchoLock.

Provides a sealed RawCommand and a sealed MissionIntentEnvelope
for the first vertical slice (EXECUTE + ADAPT scenarios).
"""

from __future__ import annotations

import pytest

from echolock import command_sealer, mie_sealer
from echolock.models import (
    AdaptationAuthority,
    ImageResolution,
    MissionIntentEnvelope,
    RawCommand,
)
from echolock.simulator import base_timestamps


@pytest.fixture()
def base_command() -> RawCommand:
    """Unsealed RawCommand for the demo scenario."""
    ts = base_timestamps()
    return RawCommand(
        description="Transmit 10 rock images at 4K resolution and high power",
        image_count=10,
        requested_resolution=ImageResolution.K4,
        requested_power_pct=100.0,
        sent_at=ts["sent_at"],
        arrived_at=ts["arrived_at"],
        intended_execution_at=ts["intended_execution_at"],
        expires_at=ts["expires_at"],
    )


@pytest.fixture()
def sealed_command(base_command: RawCommand) -> RawCommand:
    """SHA-256 sealed version of base_command."""
    return command_sealer.seal(base_command)


@pytest.fixture()
def envelope(sealed_command: RawCommand) -> MissionIntentEnvelope:
    """Standard MissionIntentEnvelope for the demo scenario — sealed with MIESealer.

    mie_fingerprint is set; pipeline will reject an unsealed envelope.
    """
    ts = base_timestamps()
    raw_envelope = MissionIntentEnvelope(
        goal="Transmit 10 high-quality rock images to Earth for geological analysis",
        send_time_assumptions={
            "battery_soc": 85.0,
            "equipment_temp_c": 42.0,
            "comm_window_status": "OPEN",
            "emergency_beacon": "ACTIVE",
        },
        battery_floor_pct=20.0,
        max_equipment_temp_c=75.0,
        emergency_beacon_must_remain_active=True,
        intended_execution_at=ts["intended_execution_at"],
        expires_at=ts["expires_at"],
        adaptation_authority=AdaptationAuthority(
            max_delay_minutes=45.0,
            min_images=3,
            allow_resolution_reduction=True,
            allow_compression=True,
            min_transmission_power_pct=40.0,
            allow_batch_split=True,
        ),
        priority=1,
    )
    return mie_sealer.seal(raw_envelope)
