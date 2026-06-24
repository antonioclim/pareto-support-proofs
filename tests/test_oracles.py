from __future__ import annotations

from fractions import Fraction
from itertools import permutations
import random
import unittest

from common import CHECKER
from pareto_support_proofs.generator import generate_certificate
from pareto_support_proofs.oracles import _hungarian, solve_scalar


class OracleTests(unittest.TestCase):
    def test_exact_hungarian_against_bruteforce(self):
        rng = random.Random(8722026)
        cases = 0
        for n in range(2, 7):
            for _ in range(50):
                matrix = [
                    [Fraction(rng.randint(-12, 24), rng.randint(1, 7)) for _ in range(n)]
                    for _ in range(n)
                ]
                solution = _hungarian(matrix)
                brute = min(
                    sum(matrix[row][perm[row]] for row in range(n))
                    for perm in permutations(range(n))
                )
                self.assertEqual(solution.value, brute)
                self.assertEqual(
                    sum(solution.row_potentials, Fraction(0))
                    + sum(solution.column_potentials, Fraction(0)),
                    brute,
                )
                cases += 1
        self.assertEqual(cases, 250)

    def test_random_assignment_p1_proofs(self):
        rng = random.Random(14591)
        cases = 0
        for p in (2, 3, 4):
            for _ in range(35):
                n = rng.randint(2, 5)
                instance = {
                    "format": "pareto-support-instance",
                    "schema_version": "1.0.0",
                    "objective_transform": [
                        {"sense": "min", "multiplier": "1", "offset": "0"}
                        for _ in range(p)
                    ],
                    "problem": {
                        "type": "assignment",
                        "n": n,
                        "objectives": [
                            {
                                "costs": [
                                    [str(rng.randint(0, 40)) for _ in range(n)]
                                    for _ in range(n)
                                ],
                                "constant": str(rng.randint(-3, 3)),
                            }
                            for _ in range(p)
                        ],
                    },
                }
                weights = tuple(Fraction(1, p) for _ in range(p))
                answer = solve_scalar(instance, weights)
                result = generate_certificate(instance, answer.decision)
                report = CHECKER.verify(instance, result.certificate)
                self.assertEqual(report["status"], "VERIFIED")
                self.assertEqual(result.certificate["trust_level"], "P1_FULLY_CHECKABLE")
                cases += 1
        self.assertEqual(cases, 105)

    def test_random_dag_shortest_path_p1_proofs(self):
        rng = random.Random(64329)
        cases = 0
        for p in (2, 3, 4):
            for _ in range(35):
                n = rng.randint(4, 8)
                nodes = [f"v{i}" for i in range(n)] + ["unreachable"]
                edges = []
                edge_no = 0
                # Guaranteed chain.
                for i in range(n - 1):
                    edge_no += 1
                    edges.append({
                        "id": f"e{edge_no:03d}",
                        "tail": f"v{i}",
                        "head": f"v{i+1}",
                        "costs": [str(rng.randint(0, 15)) for _ in range(p)],
                    })
                for i in range(n - 1):
                    for j in range(i + 2, n):
                        if rng.random() < 0.35:
                            edge_no += 1
                            edges.append({
                                "id": f"e{edge_no:03d}",
                                "tail": f"v{i}",
                                "head": f"v{j}",
                                "costs": [str(rng.randint(0, 15)) for _ in range(p)],
                            })
                edge_no += 1
                edges.append({
                    "id": f"e{edge_no:03d}",
                    "tail": "unreachable",
                    "head": f"v{n-1}",
                    "costs": ["0"] * p,
                })
                instance = {
                    "format": "pareto-support-instance",
                    "schema_version": "1.0.0",
                    "objective_transform": [
                        {"sense": "min", "multiplier": "1", "offset": "0"}
                        for _ in range(p)
                    ],
                    "problem": {
                        "type": "shortest_path",
                        "nodes": nodes,
                        "source": "v0",
                        "target": f"v{n-1}",
                        "edges": edges,
                        "objective_constants": [str(rng.randint(-2, 2)) for _ in range(p)],
                    },
                }
                weights = tuple(Fraction(1, p) for _ in range(p))
                answer = solve_scalar(instance, weights)
                result = generate_certificate(instance, answer.decision)
                report = CHECKER.verify(instance, result.certificate)
                self.assertEqual(report["status"], "VERIFIED")
                cases += 1
        self.assertEqual(cases, 105)


if __name__ == "__main__":
    unittest.main()
