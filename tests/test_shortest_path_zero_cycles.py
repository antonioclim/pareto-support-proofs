"""Regression tests for exact shortest paths with zero-cost cycles.

The first two instances preserve the AC2 CODE-001 counterexamples. The small
graph catalogue uses a separate simple-path DFS for the scalar optimum; it
does not call the project's enumeration or restricted-master routines.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from itertools import permutations
import unittest

from common import CHECKER
from pareto_support_proofs.canonical import canonical_json_bytes
from pareto_support_proofs.generator import generate_certificate
from pareto_support_proofs.instance import InstanceError, evaluate_decision, validate_instance
from pareto_support_proofs.oracles import solve_scalar


def graph(nodes, edges, *, source="s", target="t"):
    return {
        "format": "pareto-support-instance",
        "schema_version": "1.0.0",
        "objective_transform": [
            {"sense": "min", "multiplier": "1", "offset": "0"}
            for _ in range(2)
        ],
        "problem": {
            "type": "shortest_path",
            "nodes": list(nodes),
            "source": source,
            "target": target,
            "edges": [
                {"id": eid, "tail": tail, "head": head, "costs": [str(v) for v in costs]}
                for eid, tail, head, costs in edges
            ],
            "objective_constants": ["0", "0"],
        },
    }


def two_vertex_cycle():
    return graph(
        ["s", "a", "b", "t"],
        [
            ("z1", "s", "a", (0, 0)),
            ("z2", "s", "b", (0, 0)),
            ("a1", "a", "b", (0, 0)),
            ("a2", "b", "a", (0, 0)),
            ("t1", "a", "t", (1, 1)),
        ],
    )


def independent_simple_path_minimum(instance, weights):
    """Enumerate simple paths without importing the project's enumerator."""
    problem = instance["problem"]
    outgoing = {node: [] for node in problem["nodes"]}
    for edge in problem["edges"]:
        outgoing[edge["tail"]].append(edge)
    best = None

    def visit(node, visited, raw):
        nonlocal best
        if node == problem["target"]:
            outcome = [
                (1 if transform["sense"] == "min" else -1)
                * int(transform["multiplier"]) * value + int(transform["offset"])
                for transform, value in zip(instance["objective_transform"], raw)
            ]
            value = sum((weight * v for weight, v in zip(weights, outcome)), Fraction(0))
            best = value if best is None else min(best, value)
            return
        for edge in outgoing[node]:
            if edge["head"] not in visited:
                visit(
                    edge["head"],
                    visited | {edge["head"]},
                    [value + int(cost) for value, cost in zip(raw, edge["costs"])],
                )

    visit(
        problem["source"],
        {problem["source"]},
        [int(value) for value in problem["objective_constants"]],
    )
    return best


class ShortestPathZeroCycleTests(unittest.TestCase):
    def assertScalarOptimum(self, instance, weights):
        validate_instance(instance)
        expected = independent_simple_path_minimum(instance, weights)
        self.assertIsNotNone(expected)
        answer = solve_scalar(instance, weights)
        self.assertEqual(answer.scalar_value, expected)
        self.assertEqual(evaluate_decision(instance, answer.decision), answer.outcome)
        self.assertEqual(answer.trust_level, "P1_FULLY_CHECKABLE")
        return answer

    def assertP1Candidate(self, instance, edge_ids):
        candidate = {"edge_ids": edge_ids}
        evaluate_decision(instance, candidate)  # Also checks that the path is simple.
        generated = generate_certificate(instance, candidate)
        report = CHECKER.verify(instance, generated.certificate)
        self.assertEqual(report["status"], "VERIFIED")
        self.assertEqual(report["verification_level"], "P1_FULLY_CHECKABLE")
        self.assertNotEqual(generated.certificate["claim"], "nonnegative_weight_unsupported")
        return generated

    def test_ac2_target_zero_selfloop(self):
        instance = graph(
            ["s", "t"],
            [("z", "s", "t", (1, 1)), ("a", "t", "t", (0, 0))],
        )
        answer = self.assertScalarOptimum(instance, (Fraction(1, 2), Fraction(1, 2)))
        self.assertEqual(answer.decision, {"edge_ids": ["z"]})
        self.assertEqual(answer.scalar_value, 1)
        self.assertP1Candidate(instance, ["z"])

    def test_ac2_zero_cycle_without_selfloops(self):
        instance = two_vertex_cycle()
        answer = self.assertScalarOptimum(instance, (Fraction(1, 2), Fraction(1, 2)))
        self.assertEqual(answer.scalar_value, 1)
        self.assertP1Candidate(instance, ["z1", "t1"])
        with self.assertRaises(InstanceError):
            generate_certificate(instance, {"edge_ids": ["z1", "a1", "a2", "t1"]})

    def test_parallel_equal_edges_remain_deterministic_under_reordering(self):
        instance = graph(
            ["s", "t"],
            [("z", "s", "t", (1, 1)), ("a", "s", "t", (1, 1))],
        )
        answer = self.assertScalarOptimum(instance, (Fraction(1, 2), Fraction(1, 2)))
        self.assertEqual(answer.decision, {"edge_ids": ["a"]})
        first = self.assertP1Candidate(instance, ["z"])
        reordered = deepcopy(instance)
        reordered["problem"]["nodes"].reverse()
        reordered["problem"]["edges"].reverse()
        second = self.assertP1Candidate(reordered, ["z"])
        self.assertEqual(canonical_json_bytes(first.certificate), canonical_json_bytes(second.certificate))
        self.assertEqual(canonical_json_bytes(first.trace), canonical_json_bytes(second.trace))

    def test_zero_scalar_weight_creates_zero_cycle_and_boundary_support(self):
        instance = graph(
            ["s", "a", "b", "t"],
            [
                ("z1", "s", "a", (0, 1)),
                ("a1", "a", "b", (0, 2)),
                ("a2", "b", "a", (0, 2)),
                ("t1", "a", "t", (1, 0)),
                ("zz", "s", "t", (1, 0)),
            ],
        )
        answer = self.assertScalarOptimum(instance, (Fraction(1), Fraction(0)))
        self.assertEqual(answer.scalar_value, 1)
        generated = self.assertP1Candidate(instance, ["z1", "t1"])
        self.assertEqual(generated.certificate["claim"], "nonnegative_weight_supportable")
        self.assertEqual(generated.certificate["positive_payload"]["weights"], ["1/1", "0/1"])
        self.assertEqual(generated.certificate["positive_payload"]["weight_floor"], "0/1")
        self.assertEqual(len(generated.trace["iterations"]), 2)

    def test_unreachable_components_and_incoming_edges_do_not_enter_potentials(self):
        instance = two_vertex_cycle()
        instance["problem"]["nodes"].extend(["u", "v", "isolated"])
        instance["problem"]["edges"].extend([
            {"id": "u_a", "tail": "u", "head": "a", "costs": ["0", "0"]},
            {"id": "u_v", "tail": "u", "head": "v", "costs": ["0", "0"]},
            {"id": "v_u", "tail": "v", "head": "u", "costs": ["0", "0"]},
        ])
        answer = self.assertScalarOptimum(instance, (Fraction(1, 2), Fraction(1, 2)))
        self.assertEqual(set(answer.proof["node_potentials"]), {"s", "a", "b", "t"})
        self.assertP1Candidate(instance, ["z1", "t1"])

    def test_unreachable_target_is_reported_finitely(self):
        instance = graph(
            ["s", "a", "t"],
            [("s_a", "s", "a", (0, 0)), ("a_s", "a", "s", (0, 0))],
        )
        validate_instance(instance)
        self.assertIsNone(independent_simple_path_minimum(instance, (Fraction(1), Fraction(0))))
        with self.assertRaisesRegex(InstanceError, "no source-to-target path"):
            solve_scalar(instance, (Fraction(1), Fraction(0)))

    def test_zero_cycle_through_source_retains_source_normalisation(self):
        instance = graph(
            ["s", "a", "t"],
            [("s_a", "s", "a", (0, 0)), ("a_s", "a", "s", (0, 0)),
             ("s_t", "s", "t", (1, 1))],
        )
        answer = self.assertScalarOptimum(instance, (Fraction(1, 2), Fraction(1, 2)))
        self.assertEqual(answer.proof["node_potentials"]["s"], "0/1")
        self.assertP1Candidate(instance, ["s_t"])

    def test_strict_improvement_still_replaces_a_worse_predecessor(self):
        instance = graph(
            ["s", "a", "t"],
            [("direct", "s", "t", (10, 10)), ("via", "s", "a", (1, 1)),
             ("finish", "a", "t", (2, 2))],
        )
        answer = self.assertScalarOptimum(instance, (Fraction(1, 2), Fraction(1, 2)))
        self.assertEqual(answer.scalar_value, 3)
        self.assertEqual(answer.decision, {"edge_ids": ["via", "finish"]})
        self.assertP1Candidate(instance, ["via", "finish"])

    def test_all_three_node_directed_subgraphs_against_simple_path_dfs(self):
        nodes = ["s", "a", "t"]
        possible = list(permutations(nodes, 2))
        weights_to_check = [
            (Fraction(1), Fraction(0)),
            (Fraction(0), Fraction(1)),
            (Fraction(1, 3), Fraction(2, 3)),
        ]
        feasible_checks = unreachable_checks = 0
        for mask in range(1, 1 << len(possible)):
            edges = [
                (f"e{idx}", tail, head, (idx % 2, (idx // 2) % 2))
                for idx, (tail, head) in enumerate(possible)
                if mask & (1 << idx)
            ]
            instance = graph(nodes, edges)
            validate_instance(instance)
            for weights in weights_to_check:
                with self.subTest(mask=mask, weights=weights):
                    expected = independent_simple_path_minimum(instance, weights)
                    if expected is None:
                        with self.assertRaises(InstanceError):
                            solve_scalar(instance, weights)
                        unreachable_checks += 1
                    else:
                        self.assertScalarOptimum(instance, weights)
                        feasible_checks += 1
        self.assertEqual(feasible_checks, 120)
        self.assertEqual(unreachable_checks, 69)  # The empty edge set is outside the instance contract.


if __name__ == "__main__":
    unittest.main()
