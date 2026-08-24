"""
GPS (Goal-Preservation Score) calculator — approved Q2 formula.

Formula: GPS = Σ(weight_i × achieved_i)

Dimensions and weights (frozen Q2):
  scientific_utility    0.50   — fraction of nominal scientific value delivered
  output_quantity       0.25   — images_transmitted / images_requested
  timeliness            0.15   — 1.0 at 0 delay, 0.0 at max_delay_minutes delay
  operator_preferences  0.10   — fraction of optional preferences preserved

Hard-invariant failure forces eligibility GPS to 0 (handled by SafetyGate).

Design rule: no AI dependency.
"""

from __future__ import annotations

from .models import ImageResolution, MissionIntentEnvelope, PatchCandidate, RawCommand

# Resolution quality factor used for scientific utility computation
_RESOLUTION_QUALITY: dict[str, float] = {
    ImageResolution.K4.value: 1.0,
    ImageResolution.P1080.value: 0.6,
}


def compute_gps(
    candidate: PatchCandidate,
    original: RawCommand,
    envelope: MissionIntentEnvelope,
) -> float:
    """Compute the goal-preservation score for a patch candidate.

    Args:
        candidate: The patch candidate being evaluated.
        original:  The sealed original command.
        envelope:  The Mission Intent Envelope with GPS weights.

    Returns:
        GPS ∈ [0.00, 1.00] rounded to 4 decimal places.
    """
    # --- Dimension 1: Scientific utility (weight 0.50) ---
    eff_images = (
        candidate.adapted_image_count
        if candidate.adapted_image_count is not None
        else original.image_count
    )
    eff_resolution = (
        candidate.adapted_resolution.value
        if candidate.adapted_resolution is not None
        else original.requested_resolution.value
    )
    nominal_utility = original.image_count * _RESOLUTION_QUALITY.get(
        original.requested_resolution.value, 1.0
    )
    achieved_utility = eff_images * _RESOLUTION_QUALITY.get(eff_resolution, 1.0)
    d1 = achieved_utility / nominal_utility if nominal_utility > 0 else 0.0

    # --- Dimension 2: Output quantity (weight 0.25) ---
    d2 = eff_images / original.image_count if original.image_count > 0 else 0.0

    # --- Dimension 3: Timeliness (weight 0.15) ---
    max_delay = envelope.adaptation_authority.max_delay_minutes
    if max_delay <= 0:
        d3 = 1.0 if candidate.delay_minutes == 0 else 0.0
    else:
        d3 = max(0.0, 1.0 - (candidate.delay_minutes / max_delay))

    # --- Dimension 4: Operator preferences (weight 0.10) ---
    # Preferences = resolution at requested level and power at requested level.
    resolution_preserved = (
        1.0 if candidate.adapted_resolution is None or candidate.adapted_resolution == original.requested_resolution
        else 0.5  # partial credit: 1080p is lower but still useful
    )
    power_preserved = 1.0
    if candidate.adapted_power_pct is not None:
        power_preserved = candidate.adapted_power_pct / original.requested_power_pct
    d4 = (resolution_preserved + power_preserved) / 2.0

    gps = (
        envelope.gps_weight_scientific_utility * d1
        + envelope.gps_weight_output_quantity * d2
        + envelope.gps_weight_timeliness * d3
        + envelope.gps_weight_operator_preferences * d4
    )

    return round(min(max(gps, 0.0), 1.0), 4)
