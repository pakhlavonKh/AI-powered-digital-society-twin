"""Seeded simple random sampling without replacement.

The pseudo-random stream is SHA-256 in counter mode, so realised IDs do not depend on the
Python version's ``random`` implementation. Bump ALGORITHM_VERSION if anything here changes.
"""

from __future__ import annotations

import hashlib

ALGORITHM_VERSION = "srs-sha256-fisher-yates-v1"
MAX_SEED = 2**63 - 1


class SamplingError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class _Stream:
    def __init__(self, seed: int):
        self._prefix = f"societytwin:{ALGORITHM_VERSION}:{seed}:".encode()
        self._counter = 0

    def next_u64(self) -> int:
        block = hashlib.sha256(self._prefix + str(self._counter).encode()).digest()
        self._counter += 1
        return int.from_bytes(block[:8], "big")

    def below(self, bound: int) -> int:
        """Uniform integer in [0, bound) by rejection sampling (no modulo bias)."""
        limit = (1 << 64) - ((1 << 64) % bound)
        while True:
            value = self.next_u64()
            if value < limit:
                return value % bound


def simple_random_sample(frame_ids: list[str], size: int, seed: int) -> list[str]:
    """Return ``size`` IDs in selection order. The frame is sorted first so input order never matters."""
    if not 0 <= seed <= MAX_SEED:
        raise SamplingError("invalid_seed", f"seed must be an integer in 0..{MAX_SEED}")
    frame = sorted(frame_ids)
    if len(frame) != len(set(frame)):
        raise SamplingError("duplicate_ids", "sampling frame contains duplicate IDs")
    if size < 1:
        raise SamplingError("invalid_size", "sample size must be at least 1")
    if size > len(frame):
        raise SamplingError("oversample", f"requested {size} but only {len(frame)} records match; sampling is without replacement")
    stream = _Stream(seed)
    pool = list(frame)
    for i in range(size):
        j = i + stream.below(len(pool) - i)
        pool[i], pool[j] = pool[j], pool[i]
    return pool[:size]


def design_weights(eligible: int, selected: int) -> dict:
    """Inclusion probability and expansion weight relative to the eligible synthetic frame only."""
    return {
        "inclusion_probability": selected / eligible,
        "synthetic_frame_expansion_weight": eligible / selected,
        "weight_scope": (
            "Relative to the eligible records of this synthetic build only. These are not validated "
            "population weights and do not scale to real residents."
        ),
    }
