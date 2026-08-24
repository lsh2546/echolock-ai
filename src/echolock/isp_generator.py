"""
ISPCandidateGenerator — deterministic enumeration of Intent-Safe Patches.

Generates all adaptation combinations within MIE-authorised boundaries (AT-1–AT-6).
Assigns a GPS to each candidate using the frozen Q2 formula.

AI integration:
  The generator accepts an optional `ai_provider` callable with the signature:
      ai_provider(candidates: list[PatchCandidate], context: dict) -> list[str]
  It returns one explanation string per candidate.
  This callable is NEVER called in offline mode (the default).
  It is provider-neutral: any callable matching the signature can be injected.

Design rule: offline / deterministic path has no AI dependency.
"""

from __future__ import annotations

from typing import Callable

from .gps import compute_gps
from .models import (
    AdaptationType,
    ImageResolution,
    MissionIntentEnvelope,
    PatchCandidate,
    RawCommand,
)

# Type alias for the optional AI explanation provider
AIExplanationProvider = Callable[[list[PatchCandidate], dict], list[str]]


def generate(
    original: RawCommand,
    envelope: MissionIntentEnvelope,
    *,
    ai_provider: AIExplanationProvider | None = None,
) -> list[PatchCandidate]:
    """Generate all authorised patch candidates, ordered by GPS descending.

    Args:
        original:    The sealed original command.
        envelope:    The Mission Intent Envelope.
        ai_provider: Optional provider-neutral AI callable for explanations.
                     Omit (or pass None) for fully deterministic offline operation.

    Returns:
        List of PatchCandidate objects, GPS descending. Empty list if the original
        command is already safe (caller should check with SafetyGate first).
    """
    auth = envelope.adaptation_authority
    candidates: list[PatchCandidate] = []

    # --- AT-2 image count range ---
    image_counts = list(range(auth.min_images, original.image_count + 1))

    # --- AT-3 resolutions ---
    resolutions: list[ImageResolution | None] = [None]  # None = keep original
    if auth.allow_resolution_reduction and original.requested_resolution == ImageResolution.K4:
        resolutions.append(ImageResolution.P1080)

    # --- AT-5 power levels ---
    power_levels: list[float | None] = [None]  # None = keep original
    power_steps = [100.0, 70.0, auth.min_transmission_power_pct]
    for p in power_steps:
        if p < original.requested_power_pct:
            power_levels.append(p)

    # --- AT-1 delay steps [minutes] ---
    delay_steps = [0.0, 15.0, 30.0, auth.max_delay_minutes]

    for n_images in image_counts:
        for resolution in resolutions:
            for power in power_levels:
                for delay in delay_steps:
                    adaptation_types = _collect_types(
                        original, n_images, resolution, power, delay,
                        compression=False,
                    )
                    if not adaptation_types:
                        # No change from original — skip (VerdictEngine handles EXECUTE)
                        continue
                    c = PatchCandidate(
                        adaptation_types=adaptation_types,
                        adapted_image_count=n_images if n_images != original.image_count else None,
                        adapted_resolution=resolution,
                        adapted_power_pct=power,
                        compression_applied=False,
                        delay_minutes=delay,
                        batch_count=1,
                        rationale=_build_rationale(
                            original, n_images, resolution, power, delay, compressed=False
                        ),
                    )
                    gps = compute_gps(c, original, envelope)
                    candidates.append(c.model_copy(update={"gps": gps}))

                    # AT-4: also try with compression if authorised
                    if auth.allow_compression:
                        c_comp = c.model_copy(
                            update={
                                "compression_applied": True,
                                "adaptation_types": adaptation_types + [AdaptationType.APPLY_COMPRESSION],
                                "rationale": _build_rationale(
                                    original, n_images, resolution, power, delay, compressed=True
                                ),
                            }
                        )
                        gps_comp = compute_gps(c_comp, original, envelope)
                        candidates.append(c_comp.model_copy(update={"gps": gps_comp}))

    # Sort by GPS descending (deterministic tiebreak: fewer adaptation types first)
    candidates.sort(key=lambda c: (-c.gps, len(c.adaptation_types)))

    # --- Optional AI explanations (provider-neutral, offline fallback) ---
    if ai_provider is not None:
        context = {
            "command_description": original.description,
            "goal": envelope.goal,
        }
        try:
            explanations = ai_provider(candidates, context)
            if len(explanations) == len(candidates):
                candidates = [
                    c.model_copy(update={"ai_explanation": exp})
                    for c, exp in zip(candidates, explanations)
                ]
        except Exception:  # noqa: BLE001
            # AI failure is non-fatal; proceed without explanations
            pass

    return candidates


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_types(
    original: RawCommand,
    n_images: int,
    resolution: ImageResolution | None,
    power: float | None,
    delay: float,
    compression: bool,
) -> list[AdaptationType]:
    types: list[AdaptationType] = []
    if n_images != original.image_count:
        types.append(AdaptationType.REDUCE_IMAGE_COUNT)
    if resolution is not None and resolution != original.requested_resolution:
        types.append(AdaptationType.REDUCE_RESOLUTION)
    if power is not None and power < original.requested_power_pct:
        types.append(AdaptationType.REDUCE_POWER)
    if delay > 0:
        types.append(AdaptationType.DELAY)
    if compression:
        types.append(AdaptationType.APPLY_COMPRESSION)
    return types


def _build_rationale(
    original: RawCommand,
    n_images: int,
    resolution: ImageResolution | None,
    power: float | None,
    delay: float,
    compressed: bool,
) -> str:
    parts: list[str] = []
    if n_images != original.image_count:
        parts.append(f"transmit {n_images}/{original.image_count} images")
    if resolution is not None and resolution != original.requested_resolution:
        parts.append(f"reduce resolution to {resolution.value}")
    if power is not None and power < original.requested_power_pct:
        parts.append(f"reduce power to {power:.0f} %")
    if delay > 0:
        parts.append(f"delay {delay:.0f} min")
    if compressed:
        parts.append("apply compression")
    return "; ".join(parts) if parts else "no adaptation"
