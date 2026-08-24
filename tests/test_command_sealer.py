"""
tests/test_command_sealer.py

Tests for CommandSealer: immutability, fingerprint computation, tamper detection.
"""

from __future__ import annotations

import pytest

from echolock import command_sealer
from echolock.models import ImageResolution, RawCommand
from echolock.simulator import base_timestamps


def test_seal_sets_fingerprint(base_command) -> None:
    sealed = command_sealer.seal(base_command)
    assert sealed.fingerprint is not None
    assert len(sealed.fingerprint) == 64  # SHA-256 hex


def test_verify_sealed_command_passes(sealed_command) -> None:
    assert command_sealer.verify(sealed_command) is True


def test_verify_unsealed_command_fails(base_command) -> None:
    assert command_sealer.verify(base_command) is False


def test_fingerprint_is_deterministic(base_command) -> None:
    sealed_a = command_sealer.seal(base_command)
    sealed_b = command_sealer.seal(base_command)
    assert sealed_a.fingerprint == sealed_b.fingerprint


def test_tamper_detection_image_count(sealed_command) -> None:
    """Modifying image_count after sealing produces a different fingerprint → verify fails."""
    tampered = sealed_command.model_copy(update={"image_count": 5})
    assert command_sealer.verify(tampered) is False


def test_tamper_detection_description(sealed_command) -> None:
    tampered = sealed_command.model_copy(update={"description": "DIFFERENT COMMAND"})
    assert command_sealer.verify(tampered) is False


def test_tamper_detection_power(sealed_command) -> None:
    tampered = sealed_command.model_copy(update={"requested_power_pct": 50.0})
    assert command_sealer.verify(tampered) is False


def test_original_command_not_modified_by_seal(base_command) -> None:
    """Sealing must not mutate the original RawCommand object."""
    original_fp = base_command.fingerprint
    _ = command_sealer.seal(base_command)
    assert base_command.fingerprint == original_fp  # still None
