from __future__ import annotations

from fractions import Fraction
from itertools import combinations
import random
import unittest

from common import ROOT
from pareto_support_proofs.exact import (
    dual_margin_exact,
    dot,
    primal_margin_exact,
    primitive_integer_certificate,
    solve_square,
)


def support_feasible_independent(rows):
    d = tuple(tuple(Fraction(v) for v in row) for row in rows)
    p = len(d[0])
    inequalities = []
    for i in range(p):
        row = [Fraction(0)] * p
        row[i] = 1
        inequalities.append(tuple(row))
    inequalities.extend(d)
    if p == 1:
        return all(row[0] >= 0 for row in d)
    for active in combinations(range(len(inequalities)), p - 1):
        a = [[Fraction(1)] * p]
        b = [Fraction(1)]
        for idx in active:
            a.append(list(inequalities[idx]))
            b.append(Fraction(0))
        solution = solve_square(a, b)
        if solution is None or any(v < 0 for v in solution):
            continue
        if all(dot(row, solution) >= 0 for row in d):
            return True
    return False


class ExactMasterTests(unittest.TestCase):
    def test_primal_dual_and_independent_feasibility(self):
        rng = random.Random(31072026)
        cases = 0
        schedule = {2: 120, 3: 100, 4: 45, 5: 8}
        for p, repetitions in schedule.items():
            for _ in range(repetitions):
                m = rng.randint(1, min(7, p + 3))
                rows = [tuple(rng.randint(-8, 8) for _ in range(p)) for _ in range(m)]
                primal = primal_margin_exact(rows)
                dual = dual_margin_exact(rows)
                self.assertEqual(primal.value, dual.value)
                self.assertEqual(support_feasible_independent(rows), primal.value >= 0)
                self.assertLessEqual(len(dual.support), p)
                if dual.value < 0:
                    support, coefficients, q, sums, margin = primitive_integer_certificate(rows, dual)
                    self.assertLessEqual(len(support), p)
                    self.assertEqual(sum(coefficients), q)
                    self.assertTrue(all(v <= -1 for v in sums))
                    self.assertGreater(margin, 0)
                cases += 1
        self.assertEqual(cases, sum(schedule.values()))

    def test_tight_support_family(self):
        # Exact optimisation is exercised through p=5. For larger p the
        # combinatorial prototype would intentionally be expensive, so the
        # construction is checked directly.
        for p in range(2, 6):
            rows = [tuple(-p if i == j else 1 for i in range(p)) for j in range(p)]
            dual = dual_margin_exact(rows)
            self.assertLess(dual.value, 0)
            self.assertEqual(len(dual.support), p)
        for p in range(6, 11):
            rows = [tuple(-p if i == j else 1 for i in range(p)) for j in range(p)]
            mixture = [sum(row[i] for row in rows) for i in range(p)]
            self.assertTrue(all(value == -1 for value in mixture))
            for omitted in range(p):
                retained = [row for j, row in enumerate(rows) if j != omitted]
                self.assertTrue(all(row[omitted] == 1 for row in retained))


if __name__ == "__main__":
    unittest.main()
