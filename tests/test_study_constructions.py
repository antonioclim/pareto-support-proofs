from __future__ import annotations

from fractions import Fraction
import unittest

from common import CHECKER
from pareto_support_proofs.generator import generate_certificate
from pareto_support_proofs.study_instances import (
    enumerate_evaluated,
    make_grid_interval_explicit,
    make_large_shortest_path,
    make_random_explicit,
    make_tight_explicit,
    select_candidates_independently,
)


class StudyConstructionTests(unittest.TestCase):
    def test_tight_family_attains_the_dimension_bound(self):
        for p in range(2, 7):
            instance, candidate = make_tight_explicit(p=p)
            result = generate_certificate(instance, candidate)
            self.assertEqual(result.certificate["claim"], "nonnegative_weight_unsupported")
            self.assertEqual(len(result.certificate["negative_payload"]["atoms"]), p)
            self.assertEqual(CHECKER.verify(instance, result.certificate)["status"], "VERIFIED")

    def test_narrow_interval_is_exactly_supported_but_grid_hostile(self):
        q = 100_000
        instance, candidate, (ln, ld, un, ud) = make_grid_interval_explicit(q=q)
        result = generate_certificate(instance, candidate)
        self.assertNotEqual(result.certificate["claim"], "nonnegative_weight_unsupported")
        weight = Fraction(result.certificate["positive_payload"]["weights"][0])
        lower, upper = Fraction(ln, ld), Fraction(un, ud)
        self.assertLessEqual(lower, weight)
        self.assertLessEqual(weight, upper)
        for denominator in (100, 1_000, 10_000):
            self.assertFalse(any(lower <= Fraction(k, denominator) <= upper for k in range(denominator + 1)))
        self.assertEqual(CHECKER.verify(instance, result.certificate)["status"], "VERIFIED")

    def test_candidate_selection_is_deterministic_and_certificate_blind(self):
        instance = make_random_explicit(p=4, alternatives=24, seed=9917)
        evaluated = enumerate_evaluated(instance)
        first = select_candidates_independently(evaluated, seed=17)
        second = select_candidates_independently(evaluated, seed=17)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        self.assertNotEqual(first[0][1].decision, first[1][1].decision)

    def test_large_shortest_path_negative_object_is_local_and_sparse(self):
        instance, candidate, _ = make_large_shortest_path(
            p=4, path_length=20, claim="unsupported", seed=7781
        )
        result = generate_certificate(instance, candidate)
        self.assertEqual(result.certificate["claim"], "nonnegative_weight_unsupported")
        self.assertEqual(result.certificate["trust_level"], "P1_FULLY_CHECKABLE")
        self.assertLessEqual(len(result.certificate["negative_payload"]["atoms"]), 4)
        report = CHECKER.verify(instance, result.certificate)
        self.assertEqual(report["status"], "VERIFIED")
        self.assertEqual(report["trusted_global_optimisation_calls"], 0)


if __name__ == "__main__":
    unittest.main()
