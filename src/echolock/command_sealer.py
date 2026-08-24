"""
CommandSealer — seals a RawCommand with a SHA-256 fingerprint.

The fingerprint is computed over the canonical JSON of the command's
stable fields (everything except the fingerprint field itself).
Once sealed, the returned object is immutable (Pydantic frozen=True).

Design rule: this module has no AI dependency.
"""

from __future__ import annotations

import hashlib
import json

from .models import RawCommand


def _canonical_command_json(cmd: RawCommand) -> str:
    """Return a deterministic JSON string of command fields used for hashing."""
    data = cmd.model_dump(mode="json", exclude={"fingerprint"})
    return json.dumps(data, sort_keys=True, default=str)


def seal(cmd: RawCommand) -> RawCommand:
    """Compute and attach the SHA-256 fingerprint to a RawCommand.

    Returns a new (frozen) RawCommand with the fingerprint field set.
    The original command object is not modified (frozen Pydantic model).

    Args:
        cmd: A RawCommand that has not yet been fingerprinted, or one
             whose fingerprint needs to be recomputed.

    Returns:
        A new RawCommand with fingerprint set.
    """
    canonical = _canonical_command_json(cmd)
    fp = hashlib.sha256(canonical.encode()).hexdigest()
    return cmd.model_copy(update={"fingerprint": fp})


def verify(cmd: RawCommand) -> bool:
    """Return True if the stored fingerprint matches the recomputed value.

    A return value of False means the command has been tampered with.
    """
    if cmd.fingerprint is None:
        return False
    canonical = _canonical_command_json(cmd)
    expected = hashlib.sha256(canonical.encode()).hexdigest()
    return cmd.fingerprint == expected
