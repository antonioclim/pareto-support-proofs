from __future__ import annotations

from fractions import Fraction
from itertools import product
import json
import unittest

from common import ROOT
from pareto_support_proofs.exact import primal_margin_exact


class MathematicalEdgeCaseTests(unittest.TestCase):
    def test_farey_family_has_the_claimed_minimum_coefficient_mass(self):
        for B in range(2, 26):
            u = (B, -(B - 1))
            v = (-(B - 1), B - 2)
            expected_a = 2 * B - 3
            expected_b = 2 * B - 1
            expected_mass = 4 * B - 4
            self.assertEqual(
                tuple(expected_a * u[i] + expected_b * v[i] for i in range(2)),
                (-1, -1),
            )
            first_mass = None
            first_pair = None
            for mass in range(2, expected_mass + 1):
                for a in range(1, mass):
                    b = mass - a
                    sums = tuple(a * u[i] + b * v[i] for i in range(2))
                    if all(value < 0 for value in sums):
                        first_mass = mass
                        first_pair = (a, b)
                        break
                if first_mass is not None:
                    break
            self.assertEqual(first_mass, expected_mass)
            self.assertEqual(first_pair, (expected_a, expected_b))

    def test_chain_family_uses_the_correct_acyclic_matrix_and_forces_B_power_p_minus_1(self):
        for p in range(2, 9):
            for B in range(2, 8):
                matrix = [[0 for _ in range(p)] for _ in range(p)]
                for i in range(p - 1):
                    matrix[i][i] = B
                    matrix[i][i + 1] = -1
                matrix[p - 1][0] = -1
                coefficients = [1]
                for _ in range(1, p):
                    coefficients.append(B * coefficients[-1] + 1)
                weighted = [
                    sum(matrix[i][j] * coefficients[j] for j in range(p))
                    for i in range(p)
                ]
                self.assertEqual(weighted, [-1] * p)
                self.assertEqual(coefficients[-1], sum(B**t for t in range(p)))
                self.assertGreaterEqual(coefficients[-1], B ** (p - 1))
                # The last row forces a_1 >= 1. Each preceding row then forces
                # a_{i+1} >= B a_i + 1 for integral strictness.
                lower = 1
                for i in range(p - 1):
                    lower = B * lower + 1
                self.assertEqual(lower, coefficients[-1])

        # Exhaustive kill test on small parameters: no non-negative integer
        # vector with a smaller final coefficient can make every row strict.
        for p, B in [(3, 2), (4, 2), (3, 3)]:
            minimum = sum(B**t for t in range(p))
            matrix = [[0 for _ in range(p)] for _ in range(p)]
            for i in range(p - 1):
                matrix[i][i] = B
                matrix[i][i + 1] = -1
            matrix[p - 1][0] = -1
            for values in product(range(minimum), repeat=p):
                if values[-1] >= minimum:
                    continue
                weighted = [sum(matrix[i][j] * values[j] for j in range(p)) for i in range(p)]
                self.assertFalse(all(value < 0 for value in weighted))

    def test_three_sat_reduction_equivalence_and_pareto_efficiency(self):
        formulas = [
            [[(0, True), (0, True), (0, True)]],
            [[(0, True), (0, True), (0, True)], [(0, False), (0, False), (0, False)]],
            [[(0, True), (1, True), (2, True)], [(0, False), (1, False), (2, False)]],
            [[(0, True), (1, False), (2, True)], [(0, False), (1, True), (2, False)]],
        ]

        def clause_satisfied(clause, assignment):
            return any(assignment[var] if positive else not assignment[var] for var, positive in clause)

        for formula in formulas:
            n = 1 + max(var for clause in formula for var, _ in clause)
            satisfying = []
            outcomes = {(0, 0)}
            for assignment in product([False, True], repeat=n):
                sat = all(clause_satisfied(clause, assignment) for clause in formula)
                if sat:
                    satisfying.append(assignment)
                    outcomes.add((-2, 1))
                    outcomes.add((1, -2))
            if satisfying:
                rows = [outcome for outcome in sorted(outcomes) if outcome != (0, 0)]
                margin = primal_margin_exact(rows)
                self.assertEqual(margin.value, Fraction(-1, 2))
                self.assertTrue(all(not (a <= 0 and b <= 0 and (a < 0 or b < 0)) for a, b in rows))
            else:
                self.assertEqual(outcomes, {(0, 0)})

    def test_public_metadata_and_evidence_locks(self):
        zenodo = json.loads((ROOT / '.zenodo.json').read_text(encoding='utf-8'))
        cff = (ROOT / 'CITATION.cff').read_text(encoding='utf-8')
        self.assertEqual(zenodo['version'], '0.6.1')
        self.assertNotIn('doi', zenodo)
        self.assertNotIn('\ndoi:', cff)
        self.assertNotIn('@', json.dumps(zenodo))
        certificates = [
            json.loads(path.read_text(encoding='utf-8'))
            for path in sorted((ROOT / 'results/certificates').glob('*.json'))
        ]
        self.assertEqual(len(certificates), 225)
        self.assertEqual(sum(item['trust_level'] == 'P1_FULLY_CHECKABLE' for item in certificates), 213)
        self.assertEqual(sum(item['trust_level'] == 'P2_TRUSTED_ORACLE' for item in certificates), 12)


if __name__ == '__main__':
    unittest.main()
