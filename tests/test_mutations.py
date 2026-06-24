from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import random
import tempfile
import unittest

from common import CHECKER, example, recompute_negative_payload, reseal


class MutationTests(unittest.TestCase):
    def setUp(self):
        self.neg_instance = example("explicit_tight_negative_p3", "instance")
        self.neg = example("explicit_tight_negative_p3", "certificate")
        self.assignment_instance = example("assignment_positive_p3", "instance")
        self.assignment = example("assignment_positive_p3", "certificate")
        self.shortest_instance = example("shortest_path_positive_p3", "instance")
        self.shortest = example("shortest_path_positive_p3", "certificate")
        self.binary_instance = example("binary_positive_p3_p2", "instance")
        self.binary = example("binary_positive_p3_p2", "certificate")

    def assertRejected(self, instance, certificate, code=None):
        with self.assertRaises(CHECKER.Rejection) as ctx:
            CHECKER.verify(instance, certificate)
        if code is not None:
            self.assertEqual(ctx.exception.code, code)

    def test_controlled_semantic_mutations(self):
        # 1. Alter a coefficient and reseal. The tight witness loses strictness.
        mutant = deepcopy(self.neg)
        mutant["negative_payload"]["atoms"][0]["coefficient"] = "2"
        mutant = recompute_negative_payload(self.neg_instance, mutant)
        self.assertRejected(self.neg_instance, mutant, "NEGATIVE_NOT_STRICT")

        # 2. Remove an atom and recompute every redundant field.
        mutant = deepcopy(self.neg)
        mutant["negative_payload"]["atoms"].pop()
        mutant = recompute_negative_payload(self.neg_instance, mutant)
        self.assertRejected(self.neg_instance, mutant, "NEGATIVE_NOT_STRICT")

        # 3. Duplicate a decision and reseal.
        mutant = deepcopy(self.neg)
        mutant["negative_payload"]["atoms"][1] = deepcopy(mutant["negative_payload"]["atoms"][0])
        mutant = reseal(mutant)
        self.assertRejected(self.neg_instance, mutant, "NEGATIVE_ATOM_ORDER")

        # 4. Multiply all coefficients: valid inequality but non-primitive payload.
        mutant = deepcopy(self.neg)
        for atom in mutant["negative_payload"]["atoms"]:
            atom["coefficient"] = str(2 * int(atom["coefficient"]))
        mutant = recompute_negative_payload(self.neg_instance, mutant)
        self.assertRejected(self.neg_instance, mutant, "NEGATIVE_NOT_PRIMITIVE")

        # 5. Alter a stored outcome independently of its decision.
        mutant = deepcopy(self.neg)
        mutant["negative_payload"]["atoms"][0]["outcome"][0] = "999"
        mutant = reseal(mutant)
        self.assertRejected(self.neg_instance, mutant, "OUTCOME_MISMATCH")

        # 6. Replace a decision with an unlisted decision.
        mutant = deepcopy(self.neg)
        mutant["negative_payload"]["atoms"][0]["decision"] = {"id": "not-listed"}
        mutant["negative_payload"]["atoms"][0]["decision_digest"] = CHECKER.digest_label({"id": "not-listed"})
        mutant = reseal(mutant)
        self.assertRejected(self.neg_instance, mutant, "DECISION_INFEASIBLE")

        # 7. Alter the exact margin.
        mutant = deepcopy(self.neg)
        mutant["negative_payload"]["strict_margin"] = "1/2"
        mutant = reseal(mutant)
        self.assertRejected(self.neg_instance, mutant, "NEGATIVE_MARGIN")

        # 8. Alter the candidate outcome.
        mutant = deepcopy(self.neg)
        mutant["candidate"]["outcome"][0] = "1"
        mutant = reseal(mutant)
        self.assertRejected(self.neg_instance, mutant, "OUTCOME_MISMATCH")

        # 9. Alter one mathematical instance coefficient.
        instance_mutant = deepcopy(self.neg_instance)
        instance_mutant["problem"]["alternatives"][1]["raw_objectives"][0] = "-4"
        self.assertRejected(instance_mutant, self.neg, "INSTANCE_DIGEST_MISMATCH")

        # 10. Leave a stale certificate digest.
        mutant = deepcopy(self.neg)
        mutant["claim"] = "positive_weight_supportable"
        self.assertRejected(self.neg_instance, mutant)

        # 11. Non-reduced rational weight.
        mutant = deepcopy(self.assignment)
        mutant["positive_payload"]["weights"][0] = "2/6"
        mutant = reseal(mutant)
        self.assertRejected(self.assignment_instance, mutant, "RATIONAL_REDUCED")

        # 12. Weights outside the simplex.
        mutant = deepcopy(self.assignment)
        mutant["positive_payload"]["weights"] = ["1/2", "1/2", "1/2"]
        mutant["positive_payload"]["weight_floor"] = "1/2"
        mutant = reseal(mutant)
        self.assertRejected(self.assignment_instance, mutant, "POSITIVE_WEIGHT_SIMPLEX")

        # 13. Alter one assignment potential.
        mutant = deepcopy(self.assignment)
        mutant["positive_payload"]["oracle"]["proof"]["row_potentials"][0] = "999/1"
        mutant = reseal(mutant)
        self.assertRejected(self.assignment_instance, mutant, "ASSIGNMENT_DUAL_INFEASIBLE")

        # 14. Alter one shortest-path potential.
        mutant = deepcopy(self.shortest)
        mutant["positive_payload"]["oracle"]["proof"]["node_potentials"]["t"] = "999/1"
        mutant = reseal(mutant)
        self.assertRejected(self.shortest_instance, mutant, "SHORTEST_DUAL_INFEASIBLE")

        # 15. Upgrade a P2 assertion dishonestly to P1.
        mutant = deepcopy(self.binary)
        mutant["trust_level"] = "P1_FULLY_CHECKABLE"
        mutant = reseal(mutant)
        self.assertRejected(self.binary_instance, mutant, "TRUST_LEVEL")

        # 16. Unknown field injection.
        mutant = deepcopy(self.neg)
        mutant["negative_payload"]["tolerance"] = "forbidden"
        mutant = reseal(mutant)
        self.assertRejected(self.neg_instance, mutant, "UNKNOWN_FIELD")

        # 17. Reverse canonical atom order.
        mutant = deepcopy(self.neg)
        mutant["negative_payload"]["atoms"].reverse()
        mutant = reseal(mutant)
        self.assertRejected(self.neg_instance, mutant, "NEGATIVE_ATOM_ORDER")

        # 18. Inject a binary floating-point value into signed data.
        mutant = deepcopy(self.neg)
        mutant["provenance"]["unsafe_binary_float"] = 0.1
        self.assertRejected(self.neg_instance, mutant, "CANONICALISATION")

    def test_bulk_adversarial_mutations(self):
        rng = random.Random(90125)
        rejected = 0
        # Exact reevaluation attacks.
        for _ in range(1000):
            mutant = deepcopy(self.neg)
            atom = rng.randrange(len(mutant["negative_payload"]["atoms"]))
            coordinate = rng.randrange(3)
            old = int(mutant["negative_payload"]["atoms"][atom]["outcome"][coordinate])
            mutant["negative_payload"]["atoms"][atom]["outcome"][coordinate] = str(old + rng.choice([-9, -1, 1, 7]))
            mutant = reseal(mutant)
            with self.assertRaises(CHECKER.Rejection):
                CHECKER.verify(self.neg_instance, mutant)
            rejected += 1
        # Redundant-field consistency attacks.
        for _ in range(1000):
            mutant = deepcopy(self.neg)
            coordinate = rng.randrange(3)
            old = int(mutant["negative_payload"]["coordinate_sums"][coordinate])
            mutant["negative_payload"]["coordinate_sums"][coordinate] = str(old + rng.choice([-3, -1, 1, 5]))
            mutant = reseal(mutant)
            with self.assertRaises(CHECKER.Rejection):
                CHECKER.verify(self.neg_instance, mutant)
            rejected += 1
        # Integrity attacks without resealing.
        for _ in range(1000):
            mutant = deepcopy(self.assignment)
            mutant["positive_payload"]["candidate_scalar_value"] = f"{rng.randint(-100,100)}/1"
            with self.assertRaises(CHECKER.Rejection):
                CHECKER.verify(self.assignment_instance, mutant)
            rejected += 1
        self.assertEqual(rejected, 3000)

    def test_canonical_equivalence_and_metadata_boundary(self):
        # Parsed-object verification is invariant to key order and whitespace.
        instance_text = json.dumps(self.neg_instance, indent=4, sort_keys=False)
        certificate_text = json.dumps(self.neg, indent=2, sort_keys=False)
        instance = json.loads(instance_text)
        certificate = json.loads(certificate_text)
        self.assertEqual(CHECKER.verify(instance, certificate)["status"], "VERIFIED")

        # Descriptive metadata is intentionally outside the mathematical digest.
        metadata_mutant = deepcopy(self.neg_instance)
        metadata_mutant["metadata"] = {"arbitrary": "changed without changing the model"}
        self.assertEqual(CHECKER.verify(metadata_mutant, self.neg)["status"], "VERIFIED")

        # Semantically unordered alternatives may be reordered without changing the digest.
        reordered = deepcopy(self.neg_instance)
        reordered["problem"]["alternatives"].reverse()
        self.assertEqual(CHECKER.verify(reordered, self.neg)["status"], "VERIFIED")

    def test_duplicate_json_member_is_rejected(self):
        text = '{"a":1,"a":2}'
        with self.assertRaises(CHECKER.Rejection) as ctx:
            json.loads(text, object_pairs_hook=CHECKER._no_duplicate_pairs)
        self.assertEqual(ctx.exception.code, "JSON_DUPLICATE_MEMBER")


if __name__ == "__main__":
    unittest.main()
