"""
tests/test_gps.py

Unit tests for the Goal-Preservation Score formula (approved Q2).
"""

from __future__ import annotations

import pytest

from echolock.gps import compute_gps
from echolock.models import AdaptationType, ImageResolution, PatchCandidate


def _make_patch(
    image_count: int | None = None,
    resolution: ImageResolution | None = None,
    power_pct: float | None = None,
    delay_minutes: float = 0.0,
    types: list[AdaptationType] | None = None,
) -> PatchCandidate:
    return PatchCandidate(
        adaptation_types=types or [],
        adapted_image_count=image_count,
        adapted_resolution=resolution,
        adapted_power_pct=power_pct,
        delay_minutes=delay_minutes,
    )


def test_gps_no_adaptation_is_one(sealed_command, envelope) -> None:
    """A patch identical to original should score 1.0 (all dimensions fully preserved)."""
    patch = _make_patch()  # no changes — all None
    gps = compute_gps(patch, sealed_command, envelope)
    assert gps == pytest.approx(1.0, abs=0.001)


def test_gps_minimum_images_full_power(sealed_command, envelope) -> None:
    """3 images at 4K full power: quantity = 0.30, utility = 0.30, timeliness = 1.0, prefs = 1.0."""
    patch = _make_patch(
        image_count=3,
        types=[AdaptationType.REDUCE_IMAGE_COUNT],
    )
    gps = compute_gps(patch, sealed_command, envelope)
    # d1 = (3*1.0)/(10*1.0) = 0.30   × 0.50 = 0.150
    # d2 = 3/10 = 0.30                × 0.25 = 0.075
    # d3 = 1.0 (no delay)             × 0.15 = 0.150
    # d4 = 1.0 (no pref changes)      × 0.10 = 0.100
    # total = 0.475
    assert gps == pytest.approx(0.475, abs=0.005)


def test_gps_max_delay_timeliness_is_zero(sealed_command, envelope) -> None:
    """At the maximum delay (45 min), timeliness dimension = 0."""
    patch = _make_patch(delay_minutes=45.0, types=[AdaptationType.DELAY])
    gps = compute_gps(patch, sealed_command, envelope)
    # timeliness contribution = 0.0 * 0.15 = 0
    # d1 = 1.0 * 0.50 = 0.50
    # d2 = 1.0 * 0.25 = 0.25
    # d3 = 0.0 * 0.15 = 0.00
    # d4 = 1.0 * 0.10 = 0.10
    # total = 0.85
    assert gps == pytest.approx(0.85, abs=0.005)


def test_gps_resolution_reduction_lowers_score(sealed_command, envelope) -> None:
    """Reducing resolution to 1080p lowers scientific utility and preferences."""
    patch = _make_patch(
        resolution=ImageResolution.P1080,
        types=[AdaptationType.REDUCE_RESOLUTION],
    )
    gps = compute_gps(patch, sealed_command, envelope)
    assert gps < 1.0
    assert gps > 0.0


def test_gps_all_dimensions_combined(sealed_command, envelope) -> None:
    """A combined patch: 5 images, 1080p, 70 % power, no delay."""
    patch = _make_patch(
        image_count=5,
        resolution=ImageResolution.P1080,
        power_pct=70.0,
        types=[
            AdaptationType.REDUCE_IMAGE_COUNT,
            AdaptationType.REDUCE_RESOLUTION,
            AdaptationType.REDUCE_POWER,
        ],
    )
    gps = compute_gps(patch, sealed_command, envelope)
    assert 0.0 < gps <= 1.0


def test_gps_above_threshold_for_reasonable_adaptation(sealed_command, envelope) -> None:
    """7 images at 4K full power should achieve GPS ≥ 0.70.

    5/10 images scores 0.625 (below threshold); 7/10 scores ~0.775 (above).
    """
    patch = _make_patch(
        image_count=7,
        types=[AdaptationType.REDUCE_IMAGE_COUNT],
    )
    gps = compute_gps(patch, sealed_command, envelope)
    assert gps >= 0.70


def test_gps_three_images_below_threshold(sealed_command, envelope) -> None:
    """3 images at 4K should score below 0.70 (quantity and utility both at 30 %)."""
    patch = _make_patch(
        image_count=3,
        types=[AdaptationType.REDUCE_IMAGE_COUNT],
    )
    gps = compute_gps(patch, sealed_command, envelope)
    assert gps < 0.70


def test_gps_clamped_to_zero_one_range(sealed_command, envelope) -> None:
    patch = _make_patch()
    gps = compute_gps(patch, sealed_command, envelope)
    assert 0.0 <= gps <= 1.0
