"""Exact rational utilities and finite support-margin master programmes."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from math import gcd
from typing import Iterable, Sequence

Q = Fraction
Vector = tuple[Fraction, ...]


def dot(a: Sequence[Fraction], b: Sequence[Fraction]) -> Fraction:
    return sum((x * y for x, y in zip(a, b)), Fraction(0))


def lcm(a: int, b: int) -> int:
    return abs(a // gcd(a, b) * b) if a and b else 0


def common_denominator(values: Iterable[Fraction]) -> int:
    out = 1
    for value in values:
        out = lcm(out, value.denominator)
    return out


def scaled_integer_weights(weights: Sequence[Fraction]) -> tuple[int, tuple[int, ...]]:
    if not weights or any(value < 0 for value in weights) or sum(weights, Fraction(0)) != 1:
        raise ValueError("weights must form a non-negative simplex vector")
    scale = common_denominator(weights)
    integers = tuple(value.numerator * (scale // value.denominator) for value in weights)
    divisor = 0
    for value in integers:
        divisor = gcd(divisor, abs(value))
    if divisor > 1:
        scale //= divisor
        integers = tuple(value // divisor for value in integers)
    if sum(integers) != scale:
        raise AssertionError("scaled weights do not sum to their scale")
    return scale, integers


def solve_square(a: Sequence[Sequence[Fraction]], b: Sequence[Fraction]) -> list[Fraction] | None:
    n = len(a)
    if n == 0 or len(b) != n or any(len(row) != n for row in a):
        raise ValueError("a non-empty square system is required")
    matrix = [[Fraction(value) for value in row] + [Fraction(rhs)] for row, rhs in zip(a, b)]
    for column in range(n):
        pivot = next((row for row in range(column, n) if matrix[row][column] != 0), None)
        if pivot is None:
            return None
        if pivot != column:
            matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        pivot_value = matrix[column][column]
        matrix[column] = [value / pivot_value for value in matrix[column]]
        for row in range(n):
            if row == column:
                continue
            factor = matrix[row][column]
            if factor:
                matrix[row] = [
                    matrix[row][idx] - factor * matrix[column][idx] for idx in range(n + 1)
                ]
    return [matrix[idx][-1] for idx in range(n)]


@dataclass(frozen=True)
class PrimalMargin:
    value: Fraction
    weights: Vector


@dataclass(frozen=True)
class DualMargin:
    value: Fraction
    coefficients: Vector
    support: tuple[int, ...]
    active_coordinates: tuple[int, ...]


def _canonical_d(rows: Iterable[Sequence[int | Fraction]]) -> tuple[Vector, ...]:
    matrix = tuple(tuple(Fraction(value) for value in row) for row in rows)
    if not matrix:
        raise ValueError("at least one challenger is required")
    width = len(matrix[0])
    if width == 0 or any(len(row) != width for row in matrix):
        raise ValueError("a non-empty rectangular matrix is required")
    return matrix


def primal_margin_exact(rows: Iterable[Sequence[int | Fraction]]) -> PrimalMargin:
    """Solve ``max_lambda min_j lambda^T d^j`` by exact vertex enumeration."""
    d = _canonical_d(rows)
    m = len(d)
    p = len(d[0])
    best: PrimalMargin | None = None
    for k in range(1, p + 1):
        for support in combinations(range(p), k):
            for active_rows in combinations(range(m), k):
                a: list[list[Fraction]] = []
                b: list[Fraction] = []
                for row_idx in active_rows:
                    a.append([d[row_idx][idx] for idx in support] + [Fraction(-1)])
                    b.append(Fraction(0))
                a.append([Fraction(1)] * k + [Fraction(0)])
                b.append(Fraction(1))
                solution = solve_square(a, b)
                if solution is None:
                    continue
                partial, margin = solution[:-1], solution[-1]
                if any(value < 0 for value in partial):
                    continue
                weights = [Fraction(0)] * p
                for idx, value in zip(support, partial):
                    weights[idx] = value
                if any(dot(row, weights) < margin for row in d):
                    continue
                candidate = PrimalMargin(margin, tuple(weights))
                if best is None or (candidate.value, candidate.weights) > (best.value, best.weights):
                    best = candidate
    if best is None:
        raise AssertionError("the primal master has no enumerated vertex")
    return best


def dual_margin_exact(rows: Iterable[Sequence[int | Fraction]]) -> DualMargin:
    """Solve ``min_q max_i (Dq)_i`` by exact vertex enumeration."""
    d = _canonical_d(rows)
    m = len(d)
    p = len(d[0])
    best: DualMargin | None = None
    for k in range(1, min(p, m) + 1):
        for support in combinations(range(m), k):
            for active in combinations(range(p), k):
                a: list[list[Fraction]] = []
                b: list[Fraction] = []
                for coordinate in active:
                    a.append([d[idx][coordinate] for idx in support] + [Fraction(-1)])
                    b.append(Fraction(0))
                a.append([Fraction(1)] * k + [Fraction(0)])
                b.append(Fraction(1))
                solution = solve_square(a, b)
                if solution is None:
                    continue
                partial, margin = solution[:-1], solution[-1]
                if any(value <= 0 for value in partial):
                    continue
                mixture = tuple(
                    sum((partial[pos] * d[idx][coordinate] for pos, idx in enumerate(support)), Fraction(0))
                    for coordinate in range(p)
                )
                if any(value > margin for value in mixture):
                    continue
                coefficients = [Fraction(0)] * m
                for idx, value in zip(support, partial):
                    coefficients[idx] = value
                candidate = DualMargin(margin, tuple(coefficients), tuple(support), tuple(active))
                key = (candidate.value, len(candidate.support), candidate.coefficients)
                if best is None:
                    best = candidate
                else:
                    best_key = (best.value, len(best.support), best.coefficients)
                    if key < best_key:
                        best = candidate
    if best is None:
        raise AssertionError("the dual master has no enumerated vertex")
    return best


def primitive_integer_certificate(
    rows: Sequence[Sequence[int]], dual: DualMargin
) -> tuple[tuple[int, ...], tuple[int, ...], int, tuple[int, ...], Fraction]:
    """Convert a strict rational dual witness into primitive positive integers."""
    support = tuple(idx for idx, value in enumerate(dual.coefficients) if value > 0)
    rationals = [dual.coefficients[idx] for idx in support]
    denominator = common_denominator(rationals)
    coefficients = [int(value * denominator) for value in rationals]
    divisor = 0
    for value in coefficients:
        divisor = gcd(divisor, value)
    if divisor > 1:
        coefficients = [value // divisor for value in coefficients]
    coefficient_sum = sum(coefficients)
    coordinate_sums = tuple(
        sum(coefficients[pos] * int(rows[idx][coordinate]) for pos, idx in enumerate(support))
        for coordinate in range(len(rows[0]))
    )
    if any(value >= 0 for value in coordinate_sums):
        raise AssertionError("dual conversion did not produce a strict negative witness")
    depth = Fraction(min(-value for value in coordinate_sums), coefficient_sum)
    return support, tuple(coefficients), coefficient_sum, coordinate_sums, depth
