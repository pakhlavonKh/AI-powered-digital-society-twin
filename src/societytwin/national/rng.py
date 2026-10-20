"""Deterministic pseudo-random stream independent of the Python version's ``random`` module.

SHA-256 in counter mode keyed by (namespace, seed), as in ``societytwin.sampling.srs``. Every draw is
reproducible from the population or cohort manifest alone. Bump ``STREAM_VERSION`` if anything here changes.
"""

from __future__ import annotations

import bisect
import hashlib

STREAM_VERSION = "sha256-ctr-v1"
MAX_SEED = 2**63 - 1


class Stream:
    __slots__ = ("_prefix", "_counter", "_buffer")

    def __init__(self, namespace: str, seed: int):
        if not 0 <= seed <= MAX_SEED:
            raise ValueError(f"seed must be an integer in 0..{MAX_SEED}")
        self._prefix = f"societytwin:{STREAM_VERSION}:{namespace}:{seed}:".encode()
        self._counter = 0
        self._buffer: list[int] = []

    def next_u64(self) -> int:
        if not self._buffer:
            block = hashlib.sha256(self._prefix + str(self._counter).encode()).digest()
            self._counter += 1
            self._buffer = [int.from_bytes(block[i:i + 8], "big") for i in (24, 16, 8, 0)]
        return self._buffer.pop()

    def random(self) -> float:
        """Uniform float in [0, 1) with 53 bits of precision."""
        return (self.next_u64() >> 11) / float(1 << 53)

    def below(self, bound: int) -> int:
        """Uniform integer in [0, bound) by rejection sampling (no modulo bias)."""
        if bound <= 0:
            raise ValueError("bound must be positive")
        limit = (1 << 64) - ((1 << 64) % bound)
        while True:
            value = self.next_u64()
            if value < limit:
                return value % bound

    def weighted_index(self, cumulative: list[float]) -> int:
        """Index drawn proportionally to the increments of a cumulative weight list (last element = total)."""
        total = cumulative[-1]
        if not total > 0:
            raise ValueError("weights must have a positive total")
        return bisect.bisect_right(cumulative, self.random() * total)

    def shuffle(self, items: list) -> list:
        out = list(items)
        for i in range(len(out) - 1, 0, -1):
            j = self.below(i + 1)
            out[i], out[j] = out[j], out[i]
        return out


def cumulative(weights: list[float]) -> list[float]:
    total, out = 0.0, []
    for w in weights:
        if w < 0:
            raise ValueError("negative weight")
        total += w
        out.append(total)
    return out
