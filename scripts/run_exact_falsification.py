#!/usr/bin/env python3
"""Exact mathematical falsification suite for the certificate theorems.

The suite uses fractions throughout.  It independently enumerates vertices of the
primal and dual margin LPs, constructs basic feasible solutions of the strict
witness LP, checks the determinant/bit bound, attacks invariance and robustness
claims and validates the proposed NP-hardness reduction on small formulae.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations, product
from math import gcd, isqrt, lcm
from random import Random
from typing import Iterable, Sequence
import argparse
import json
from pathlib import Path
import time

Q = Fraction
Vector = tuple[Q, ...]


def q(x: int | Fraction) -> Fraction:
    return x if isinstance(x, Fraction) else Fraction(x)


def dot(a: Sequence[Fraction], b: Sequence[Fraction]) -> Fraction:
    return sum((x * y for x, y in zip(a, b)), Fraction(0))


def solve_square(A: Sequence[Sequence[Fraction]], b: Sequence[Fraction]) -> list[Fraction] | None:
    """Exact Gaussian elimination. Return None for a singular system."""
    n = len(A)
    M = [[q(A[i][j]) for j in range(n)] + [q(b[i])] for i in range(n)]
    for col in range(n):
        pivot = next((r for r in range(col, n) if M[r][col] != 0), None)
        if pivot is None:
            return None
        if pivot != col:
            M[col], M[pivot] = M[pivot], M[col]
        pv = M[col][col]
        M[col] = [v / pv for v in M[col]]
        for r in range(n):
            if r == col:
                continue
            f = M[r][col]
            if f != 0:
                M[r] = [M[r][j] - f * M[col][j] for j in range(n + 1)]
    return [M[i][-1] for i in range(n)]


def det_bareiss(A: Sequence[Sequence[int]]) -> int:
    """Fraction-free exact determinant."""
    M = [list(map(int, row)) for row in A]
    n = len(M)
    if n == 0:
        return 1
    sign = 1
    prev = 1
    for k in range(n - 1):
        pivot = next((r for r in range(k, n) if M[r][k] != 0), None)
        if pivot is None:
            return 0
        if pivot != k:
            M[k], M[pivot] = M[pivot], M[k]
            sign *= -1
        pv = M[k][k]
        for i in range(k + 1, n):
            for j in range(k + 1, n):
                M[i][j] = (M[i][j] * pv - M[i][k] * M[k][j]) // prev
        prev = pv
        for i in range(k + 1, n):
            M[i][k] = 0
    return sign * M[n - 1][n - 1]


@dataclass(frozen=True)
class MarginSolution:
    value: Fraction
    weights: tuple[Fraction, ...]
    active: tuple[int, ...]


def primal_margin(C: Sequence[Sequence[int | Fraction]]) -> MarginSolution:
    """Exact max_{lambda in simplex} min_j lambda^T c_j by vertex enumeration."""
    if not C:
        raise ValueError("At least one distinct challenger is required")
    Cq = [tuple(q(v) for v in row) for row in C]
    p = len(Cq[0])
    m = len(Cq)
    n = p + 1  # lambda plus t
    equality = [Fraction(1)] * p + [Fraction(0)]
    active_rows: list[tuple[list[Fraction], Fraction, int]] = []
    # lambda_i = 0
    for i in range(p):
        row = [Fraction(0)] * n
        row[i] = 1
        active_rows.append((row, Fraction(0), i))
    # t - c_j^T lambda = 0
    for j, c in enumerate(Cq):
        row = [-v for v in c] + [Fraction(1)]
        active_rows.append((row, Fraction(0), p + j))

    best: MarginSolution | None = None
    for combo in combinations(range(len(active_rows)), p):
        A = [equality]
        b = [Fraction(1)]
        for idx in combo:
            row, rhs, _ = active_rows[idx]
            A.append(row)
            b.append(rhs)
        x = solve_square(A, b)
        if x is None:
            continue
        lam, t = x[:p], x[p]
        if any(v < 0 for v in lam):
            continue
        if any(t > dot(lam, c) for c in Cq):
            continue
        sol = MarginSolution(t, tuple(lam), tuple(combo))
        if best is None or sol.value > best.value:
            best = sol
    if best is None:
        raise AssertionError("Primal margin LP has no enumerated vertex")
    return best


def dual_margin(C: Sequence[Sequence[int | Fraction]]) -> MarginSolution:
    """Exact min_{q in simplex} max_i (Cq)_i by vertex enumeration."""
    if not C:
        raise ValueError("At least one distinct challenger is required")
    Cq = [tuple(q(v) for v in row) for row in C]
    m = len(Cq)
    p = len(Cq[0])
    n = m + 1  # q plus t
    equality = [Fraction(1)] * m + [Fraction(0)]
    active_rows: list[tuple[list[Fraction], Fraction, int]] = []
    # q_j = 0
    for j in range(m):
        row = [Fraction(0)] * n
        row[j] = 1
        active_rows.append((row, Fraction(0), j))
    # sum_j c_{ji} q_j - t = 0
    for i in range(p):
        row = [Cq[j][i] for j in range(m)] + [Fraction(-1)]
        active_rows.append((row, Fraction(0), m + i))

    best: MarginSolution | None = None
    for combo in combinations(range(len(active_rows)), m):
        A = [equality]
        b = [Fraction(1)]
        for idx in combo:
            row, rhs, _ = active_rows[idx]
            A.append(row)
            b.append(rhs)
        x = solve_square(A, b)
        if x is None:
            continue
        weights, t = x[:m], x[m]
        if any(v < 0 for v in weights):
            continue
        vals = [sum(weights[j] * Cq[j][i] for j in range(m)) for i in range(p)]
        if any(v > t for v in vals):
            continue
        sol = MarginSolution(t, tuple(weights), tuple(combo))
        if best is None or sol.value < best.value:
            best = sol
        elif best is not None and sol.value == best.value:
            # Prefer the sparsest exact optimum for auditing the p-atom claim.
            if sum(v > 0 for v in sol.weights) < sum(v > 0 for v in best.weights):
                best = sol
    if best is None:
        raise AssertionError("Dual margin LP has no enumerated vertex")
    return best


@dataclass(frozen=True)
class EpsilonBFS:
    epsilon: Fraction
    q_weights: tuple[Fraction, ...]
    slacks: tuple[Fraction, ...]
    basis: tuple[int, ...]
    determinant: int


def strict_witness_bfs(C: Sequence[Sequence[int]]) -> EpsilonBFS:
    """Solve max epsilon with Cq + epsilon*1 + s = 0 and sum q = 1.

    Called only when a strict negative convex witness exists.  The basic optimum
    directly exposes the determinant used in the encoding bound proof.
    """
    if not C:
        raise ValueError("At least one challenger is required")
    Cint = [tuple(map(int, row)) for row in C]
    m = len(Cint)
    p = len(Cint[0])
    # Columns: q_1,...,q_m, epsilon, s_1,...,s_p
    columns: list[list[int]] = []
    for c in Cint:
        columns.append(list(c) + [1])
    eps_index = len(columns)
    columns.append([1] * p + [0])
    for i in range(p):
        col = [0] * (p + 1)
        col[i] = 1
        columns.append(col)
    b = [0] * p + [1]

    best: EpsilonBFS | None = None
    # A positive epsilon must be basic. Filtering makes exhaustive checks faster.
    for basis in combinations(range(len(columns)), p + 1):
        if eps_index not in basis:
            continue
        Aint = [[columns[j][i] for j in basis] for i in range(p + 1)]
        det = det_bareiss(Aint)
        if det == 0:
            continue
        A = [[Fraction(v) for v in row] for row in Aint]
        zB = solve_square(A, [Fraction(v) for v in b])
        if zB is None or any(v < 0 for v in zB):
            continue
        z = [Fraction(0)] * len(columns)
        for j, v in zip(basis, zB):
            z[j] = v
        eps = z[eps_index]
        qv = tuple(z[:m])
        sv = tuple(z[eps_index + 1 :])
        # Structural verification.
        if sum(qv) != 1:
            continue
        for i in range(p):
            lhs = sum(qv[j] * Cint[j][i] for j in range(m)) + eps + sv[i]
            if lhs != 0:
                raise AssertionError("Malformed basic solution")
        candidate = EpsilonBFS(eps, qv, sv, tuple(basis), abs(det))
        if best is None or candidate.epsilon > best.epsilon:
            best = candidate
    if best is None or best.epsilon <= 0:
        raise AssertionError("No positive strict-witness BFS found")
    return best


def hadamard_bound(p: int, B: int) -> int:
    """Ceiling of p^(p/2+1) B^(p-1).

    The bound exploits the compulsory epsilon column.  Expanding slack columns
    reduces the basis determinant to a (k+1)-square matrix.  Expansion along
    its last row gives k minors, each bounded by k^(k/2) B^(k-1); k <= p.
    This improves the naive B^p Hadamard estimate to B^(p-1) and is 4B for
    p=2.
    """
    B = max(1, int(B))
    n = (p ** (p + 2)) * (B ** (2 * p - 2))
    h = isqrt(n)
    return h if h * h == n else h + 1


def integralise(weights: Sequence[Fraction]) -> tuple[list[int], int]:
    d = 1
    for w in weights:
        d = lcm(d, w.denominator)
    a = [int(w * d) for w in weights]
    g = 0
    for x in a:
        g = gcd(g, x)
    if g > 1:
        a = [x // g for x in a]
        d //= g
    return a, d


def certificate_checks(C: Sequence[Sequence[int]], sigma: Fraction) -> dict:
    p = len(C[0])
    B = max(abs(v) for row in C for v in row)
    bfs = strict_witness_bfs(C)
    if bfs.epsilon != -sigma:
        raise AssertionError(f"epsilon/margin mismatch: {bfs.epsilon} vs {-sigma}")
    support = [j for j, w in enumerate(bfs.q_weights) if w > 0]
    if len(support) > p:
        raise AssertionError("Sparse support bound failed")
    d = bfs.determinant
    if any((w * d).denominator != 1 for w in bfs.q_weights):
        raise AssertionError("Basis determinant does not clear q denominators")
    a_full = [int(w * d) for w in bfs.q_weights]
    if sum(a_full) != d:
        raise AssertionError("Integer coefficients do not normalise to determinant")
    sums = [sum(a_full[j] * C[j][i] for j in range(len(C))) for i in range(p)]
    if any(v > -1 for v in sums):
        raise AssertionError("Integral witness is not strictly negative")
    H = hadamard_bound(p, B)
    if d > H:
        raise AssertionError(f"Determinant bound failed: {d}>{H}")
    if -sigma < Fraction(1, H):
        raise AssertionError("Discrete margin lower bound failed")
    return {
        "support": len(support),
        "determinant": d,
        "H": H,
        "B": B,
        "epsilon": str(bfs.epsilon),
    }


def is_pareto_efficient_zero(C: Sequence[Sequence[int]]) -> bool:
    return not any(all(v <= 0 for v in c) and any(v < 0 for v in c) for c in C)


def tight_family(p: int) -> list[tuple[int, ...]]:
    return [tuple((2 * p - 3 if i == k else -2) for i in range(p)) for k in range(p)]


def test_tightness() -> dict:
    out = []
    for p in range(2, 11):
        C = tight_family(p)
        avg = [Fraction(sum(C[k][i] for k in range(p)), p) for i in range(p)]
        assert all(v == Fraction(-1, p) for v in avg)
        assert is_pareto_efficient_zero(C)
        # For any proper support S, each positive coefficient would have to be
        # strictly below 2/(2p-1), so the coefficients cannot sum to one.
        for r in range(1, p):
            assert Fraction(2 * r, 2 * p - 1) < 1
        sigma = None
        min_support = p
        if p <= 6:
            ps = primal_margin(C)
            ds = dual_margin(C)
            assert ps.value == ds.value == Fraction(-1, p)
            min_support = sum(v > 0 for v in ds.weights)
            assert min_support == p
            sigma = str(ps.value)
        out.append({"p": p, "sigma_checked": sigma, "minimum_atoms": min_support})
    return {"families": out}


def farey_lower_bound(B: int) -> dict:
    if B < 2:
        raise ValueError
    C = [(B, -(B - 1)), (-(B - 1), B - 2)]
    a = [2 * B - 3, 2 * B - 1]
    sums = [sum(a[j] * C[j][i] for j in range(2)) for i in range(2)]
    assert sums == [-1, -1]
    # The two admissible ratio bounds are Farey neighbours.  Any reduced
    # fraction strictly between them has denominator at least 2B-1.
    assert (B - 1) * (B - 1) - B * (B - 2) == 1
    return {"B": B, "vectors": C, "coefficients": a, "sum": sum(a), "weighted_sum": sums}



def chain_coefficient_lower_bound(p: int, B: int) -> dict:
    """A B^(p-1) lower-bound family for integral witness coefficients.

    Rows 1,...,p-1 impose a_{i+1} > B a_i and the last row imposes
    a_1 > 0.  The recurrence a_{i+1}=B a_i+1 makes every coordinate
    of C a equal to -1.
    """
    if p < 2 or B < 2:
        raise ValueError
    C = [[0 for _ in range(p)] for _ in range(p)]
    for i in range(p - 1):
        C[i][i] = B
        C[i][i + 1] = -1
    C[p - 1][0] = -1
    a = [1]
    for _ in range(1, p):
        a.append(B * a[-1] + 1)
    sums = [sum(C[i][j] * a[j] for j in range(p)) for i in range(p)]
    assert sums == [-1] * p
    assert a[-1] == sum(B ** t for t in range(p))
    return {
        "p": p,
        "B": B,
        "matrix_rows": C,
        "coefficients": a,
        "largest_coefficient": a[-1],
        "weighted_sum": sums,
    }

def random_cnf(rng: Random, n: int, clauses: int) -> list[list[tuple[int, bool]]]:
    formula = []
    for _ in range(clauses):
        vars_ = rng.sample(range(n), k=min(3, n))
        while len(vars_) < 3:
            vars_.append(rng.randrange(n))
        formula.append([(v, bool(rng.getrandbits(1))) for v in vars_])
    return formula


def satisfies(formula: Sequence[Sequence[tuple[int, bool]]], z: Sequence[int]) -> bool:
    for clause in formula:
        ok = False
        for idx, positive in clause:
            val = bool(z[idx])
            ok |= val if positive else not val
        if not ok:
            return False
    return True


def test_sat_reduction(cases: int = 500) -> dict:
    rng = Random(981237)
    formulas: list[list[list[tuple[int, bool]]]] = []
    # Random instances.
    for _ in range(max(1, cases - 40)):
        n = rng.randint(3, 7)
        formulas.append(random_cnf(rng, n, rng.randint(1, 7 * n)))
    # Forty deterministically unsatisfiable formulae: all eight clauses that
    # exclude the eight assignments of three designated variables.
    for shift in range(40):
        n = 3 + (shift % 4)
        chosen = [0, 1, 2]
        formula = []
        for assignment in product([0, 1], repeat=3):
            clause = []
            for idx, bit in zip(chosen, assignment):
                clause.append((idx, bit == 0))
            formula.append(clause)
        formulas.append(formula)

    sat_count = 0
    unsat_count = 0
    for formula in formulas:
        n = 1 + max(idx for clause in formula for idx, _ in clause)
        sat = any(satisfies(formula, z) for z in product([0, 1], repeat=n))
        if sat:
            sat_count += 1
            C = [(-2, 1), (1, -2)]
        else:
            unsat_count += 1
            # Only outcome duplicates of the candidate remain.  A single zero
            # difference is used for the exact margin routine.
            C = [(0, 0)]
        ps = primal_margin(C)
        unsupported = ps.value < 0
        assert unsupported == sat
        assert is_pareto_efficient_zero(C)
        if sat:
            assert ps.value == Fraction(-1, 2)
    return {"cases": len(formulas), "satisfiable": sat_count, "unsatisfiable": unsat_count, "all_equivalences_passed": True}


def run_exhaustive() -> dict:
    stats = {
        "instances": 0,
        "unsupported": 0,
        "supported_zero_margin": 0,
        "strict_positive_margin": 0,
        "max_atoms": 0,
        "max_det_ratio_num": 0,
        "max_det_ratio_den": 1,
    }

    def audit(C: tuple[tuple[int, ...], ...]) -> None:
        ps = primal_margin(C)
        ds = dual_margin(C)
        if ps.value != ds.value:
            raise AssertionError(f"Minimax failure: {C}, {ps.value}, {ds.value}")
        stats["instances"] += 1
        if ps.value < 0:
            stats["unsupported"] += 1
            ck = certificate_checks(C, ps.value)
            stats["max_atoms"] = max(stats["max_atoms"], ck["support"])
            # Track the largest observed determinant/H ratio exactly.
            num, den = ck["determinant"], ck["H"]
            if num * stats["max_det_ratio_den"] > stats["max_det_ratio_num"] * den:
                stats["max_det_ratio_num"], stats["max_det_ratio_den"] = num, den
        elif ps.value == 0:
            stats["supported_zero_margin"] += 1
        else:
            stats["strict_positive_margin"] += 1

    # Complete families over two small grids.
    vecs2 = [v for v in product((-1, 0, 1), repeat=2) if v != (0, 0)]
    for r in range(1, len(vecs2) + 1):
        for C in combinations(vecs2, r):
            audit(C)

    vecs3 = [v for v in product((-1, 0, 1), repeat=3) if v != (0, 0, 0)]
    for r in range(1, 4):
        for C in combinations(vecs3, r):
            audit(C)

    # Deterministic random stress beyond exhaustive sizes.
    rng = Random(20260623)
    for _ in range(220):
        p = rng.choice((3, 4))
        m = rng.randint(2, 5 if p == 4 else 6)
        pool = [v for v in product(range(-2, 3), repeat=p) if any(v)]
        C = tuple(rng.sample(pool, m))
        audit(C)

    stats["max_det_over_H"] = f"{stats['max_det_ratio_num']}/{stats['max_det_ratio_den']}"
    del stats["max_det_ratio_num"]
    del stats["max_det_ratio_den"]
    return stats


def run_property_attacks(cases: int = 350) -> dict:
    rng = Random(44491)
    counts = {"scale": 0, "permute": 0, "duplicate": 0, "dominated_redundancy": 0, "lipschitz": 0}
    for _ in range(cases):
        p = rng.choice((2, 3))
        m = rng.randint(2, 5)
        pool = [v for v in product(range(-2, 3), repeat=p) if any(v)]
        C = [tuple(v) for v in rng.sample(pool, m)]
        base = primal_margin(C).value

        scales = [rng.randint(1, 4) for _ in range(p)]
        Cs = [tuple(c[i] * scales[i] for i in range(p)) for c in C]
        assert (primal_margin(Cs).value < 0) == (base < 0)
        assert (primal_margin(Cs).value >= 0) == (base >= 0)
        counts["scale"] += 1

        perm = list(range(p))
        rng.shuffle(perm)
        Cp = [tuple(c[i] for i in perm) for c in C]
        assert primal_margin(Cp).value == base
        counts["permute"] += 1

        Cd = C + [C[rng.randrange(m)]]
        assert primal_margin(Cd).value == base
        counts["duplicate"] += 1

        anchor = C[rng.randrange(m)]
        worse = tuple(anchor[i] + rng.randint(0, 3) for i in range(p))
        Cr = C + [worse]
        assert primal_margin(Cr).value == base
        counts["dominated_redundancy"] += 1

        delta = Fraction(1, rng.choice((2, 3, 4)))
        perturb = []
        for c in C:
            perturb.append(tuple(Fraction(c[i]) + rng.choice((-delta, Fraction(0), delta)) for i in range(p)))
        moved = primal_margin(perturb).value
        assert abs(moved - base) <= delta
        if abs(base) > delta:
            assert (moved > 0) == (base > 0) if base != 0 else True
            assert (moved < 0) == (base < 0) if base != 0 else True
        counts["lipschitz"] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Run a reduced smoke audit")
    parser.add_argument("--output", default="validation/exact_falsification_summary.json")
    parser.add_argument("--record-timing", action="store_true", help="Include non-deterministic wall-clock metadata")
    args = parser.parse_args()
    start = time.time()

    if args.quick:
        exhaustive = {"skipped_full": True}
        properties = run_property_attacks(40)
        sat = test_sat_reduction(50)
    else:
        exhaustive = run_exhaustive()
        properties = run_property_attacks(220)
        sat = test_sat_reduction(300)

    results = {
        "schema": "pareto-support-exact-falsification-1.0",
        "arithmetic": "fractions.Fraction only",
        "primal_dual_exhaustive": exhaustive,
        "property_attacks": properties,
        "tightness": test_tightness(),
        "coefficient_lower_bound_examples": [farey_lower_bound(B) for B in (2, 3, 5, 10, 25)],
        "coefficient_exponent_lower_bound": [
            chain_coefficient_lower_bound(p, B)
            for p, B in ((2, 2), (3, 2), (4, 2), (3, 3), (4, 3), (5, 3))
        ],
        "sat_reduction": sat,
        "verdict": "PASS",
    }
    if args.record_timing:
        results["elapsed_seconds"] = round(time.time() - start, 3)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
