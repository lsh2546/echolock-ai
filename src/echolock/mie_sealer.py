"""
MIESealer — seals a MissionIntentEnvelope with a SHA-256 fingerprint.

The fingerprint covers the canonical JSON of every MIE field EXCEPT the
mie_fingerprint field itself. The envelope is reconstructed through Pydantic
validation before sealing so nested assumptions are detached and recursively
frozen.

Once sealed the returned object is immutable (Pydantic frozen=True).

Design rule: this module has no AI dependency.
"""

from __future__ import annotations

import hashlib
import json

from .models import MissionIntentEnvelope


def _canonical_mie_json(envelope: MissionIntentEnvelope) -> str:
    """Return a deterministic JSON string of MIE fields used for hashing.

    All fields are included EXCEPT mie_fingerprint itself (which is what we
    are computing).  model_dump(mode='json') deep-copies all nested structures
    including send_time_assumptions, ensuring no mutable reference escapes.
    """
    data = envelope.model_dump(mode="json", exclude={"mie_fingerprint"})
    return json.dumps(data, sort_keys=True, default=str)


def seal(envelope: MissionIntentEnvelope) -> MissionIntentEnvelope:
    """Compute and attach the SHA-256 fingerprint to a MissionIntentEnvelope.

    Returns a new (frozen) MissionIntentEnvelope with mie_fingerprint set.
    The original envelope object is not modified (frozen Pydantic model).

    Args:
        envelope: A MissionIntentEnvelope that has not yet been fingerprinted,
                  or one whose fingerprint needs to be recomputed.

    Returns:
        A new MissionIntentEnvelope with mie_fingerprint set.
    """
    # Revalidate a detached dump so the sealed result cannot share mutable nested
    # references with the caller's envelope.
    detached = MissionIntentEnvelope.model_validate(
        envelope.model_dump(mode="python", exclude={"mie_fingerprint"})
    )
    canonical = _canonical_mie_json(detached)
    fp = hashlib.sha256(canonical.encode()).hexdigest()
    return detached.model_copy(update={"mie_fingerprint": fp})


def verify(envelope: MissionIntentEnvelope) -> bool:
    """Return True if the stored mie_fingerprint matches the recomputed value.

    A return value of False means the envelope has been tampered with, or it
    was never sealed.
    """
    if envelope.mie_fingerprint is None:
        return False
    canonical = _canonical_mie_json(envelope)
    expected = hashlib.sha256(canonical.encode()).hexdigest()
    return envelope.mie_fingerprint == expected
