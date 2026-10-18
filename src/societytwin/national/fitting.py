"""Numerical fitting: integer allocation, two-way IPF with structural zeros, and weight raking.

All routines are small, dependency-free and deterministic. They report convergence diagnostics
instead of silently accepting a poor fit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def largest_remainder(shares: dict, total: int, floor: dict | None = None) -> dict:
    """Integer allocation of ``total`` proportional to ``shares`` (Hamilton method); ties broken by key order.

    ``floor`` gives a minimum per key (applied first). Every key with zero share gets zero unless floored.
    """
    keys = sorted(shares)
    floor = floor or {}
    out = {k: int(floor.get(k, 0)) for k in keys}
    remaining = total - sum(out.values())
    if remaining < 0:
        raise ValueError("floors exceed the total")
    mass = math.fsum(shares[k] for k in keys)
    if remaining == 0:
        return out
    if mass <= 0:
        raise ValueError("no positive shares to allocate")
    quotas = {k: remaining * shares[k] / mass for k in keys}
    base = {k: int(math.floor(quotas[k])) for k in keys}
    left = remaining - sum(base.values())
    rank = {k: i for i, k in enumerate(keys)}
    order = sorted(keys, key=lambda k: (-(quotas[k] - base[k]), rank[k]))
    for k in order[:left]:
        base[k] += 1
    return {k: out[k] + base[k] for k in keys}


@dataclass
class IpfResult:
    table: list[list[float]]
    iterations: int
    converged: bool
    max_abs_residual: float
    column_scale: float  # source column total ÷ row total before scaling (1.0 = consistent sources)


def ipf_2d(row_targets: list[float], col_targets: list[float], seed: list[list[float]], tol: float = 1e-9,
           max_iter: int = 2000) -> IpfResult:
    """Maximum-entropy table matching both margins, starting from ``seed`` (zeros are structural and stay zero).

    Column targets are rescaled to the row total first; the ratio is reported so that inconsistent
    sources (different years or universes) are visible instead of hidden.
    """
    rows, cols = len(row_targets), len(col_targets)
    row_total, col_total = math.fsum(row_targets), math.fsum(col_targets)
    if row_total <= 0 or col_total <= 0:
        raise ValueError("margins must have a positive total")
    scale = col_total / row_total
    col_targets = [c / scale for c in col_targets]
    table = [[float(seed[i][j]) for j in range(cols)] for i in range(rows)]
    residual = math.inf
    for iteration in range(1, max_iter + 1):
        for i in range(rows):
            s = math.fsum(table[i])
            if s > 0:
                f = row_targets[i] / s
                table[i] = [v * f for v in table[i]]
        for j in range(cols):
            s = math.fsum(table[i][j] for i in range(rows))
            if s > 0:
                f = col_targets[j] / s
                for i in range(rows):
                    table[i][j] *= f
        residual = max([abs(math.fsum(table[i]) - row_targets[i]) for i in range(rows)]
                       + [abs(math.fsum(table[i][j] for i in range(rows)) - col_targets[j]) for j in range(cols)])
        if residual <= tol * max(row_total, 1.0):
            return IpfResult(table, iteration, True, residual, scale)
    return IpfResult(table, max_iter, False, residual, scale)


@dataclass
class Margin:
    name: str
    cells: list[tuple]                    # cell keys, in report order
    targets: list[float]
    membership: list[int | None]          # cell index per record, None when the record is outside the margin's universe


@dataclass
class RakeReport:
    converged: bool
    iterations: int
    max_relative_error: float
    unreachable_cells: list[dict] = field(default_factory=list)


def rake(weights: list[float], margins: list[Margin], tol: float = 1e-10, max_iter: int = 500) -> RakeReport:
    """Iterative proportional fitting of record weights to every margin (raking ratio estimation).

    Cells with a positive target but no records cannot be matched; they are reported and excluded
    from the convergence test. Weights are modified in place and stay strictly positive.
    """
    unreachable = []
    reachable: list[list[bool]] = []
    for m in margins:
        present = [False] * len(m.cells)
        for c in m.membership:
            if c is not None:
                present[c] = True
        for k, ok in enumerate(present):
            if not ok and m.targets[k] > 0:
                unreachable.append({"margin": m.name, "cell": list(m.cells[k]), "target": m.targets[k]})
            if ok and m.targets[k] <= 0:
                raise ValueError(f"{m.name}: records fall in cell {m.cells[k]} whose target is zero")
        reachable.append(present)
    worst = math.inf
    for iteration in range(1, max_iter + 1):
        for m, present in zip(margins, reachable):
            sums = [0.0] * len(m.cells)
            for i, c in enumerate(m.membership):
                if c is not None:
                    sums[c] += weights[i]
            factors = [m.targets[k] / sums[k] if present[k] else 1.0 for k in range(len(m.cells))]
            for i, c in enumerate(m.membership):
                if c is not None:
                    weights[i] *= factors[c]
        worst = 0.0
        for m, present in zip(margins, reachable):
            sums = [0.0] * len(m.cells)
            for i, c in enumerate(m.membership):
                if c is not None:
                    sums[c] += weights[i]
            for k in range(len(m.cells)):
                if present[k]:
                    worst = max(worst, abs(sums[k] / m.targets[k] - 1.0))
        if worst <= tol:
            return RakeReport(True, iteration, worst, unreachable)
    return RakeReport(False, max_iter, worst, unreachable)
