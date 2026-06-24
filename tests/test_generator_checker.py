from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import ast
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

from common import CHECKER, ROOT, example
from pareto_support_proofs.canonical import canonical_json_bytes
from pareto_support_proofs.exact import primal_margin_exact
from pareto_support_proofs.generator import generate_certificate


class GeneratorCheckerTests(unittest.TestCase):
    def test_random_explicit_images_against_full_exact_master(self):
        rng = random.Random(235711)
        cases = 0
        for p in (2, 3, 4):
            for _ in range(90):
                m = rng.randint(2, 9)
                y0 = tuple(rng.randint(-5, 5) for _ in range(p))
                outcomes = [y0]
                while len(outcomes) < m:
                    outcomes.append(tuple(rng.randint(-15, 15) for _ in range(p)))
                instance = {
                    "format": "pareto-support-instance",
                    "schema_version": "1.0.0",
                    "objective_transform": [
                        {"sense": "min", "multiplier": "1", "offset": "0"}
                        for _ in range(p)
                    ],
                    "problem": {
                        "type": "explicit_image",
                        "alternatives": [
                            {"id": f"x{idx:02d}", "raw_objectives": [str(v) for v in outcome]}
                            for idx, outcome in enumerate(outcomes)
                        ],
                    },
                }
                candidate = {"id": "x00"}
                distinct = sorted(set(outcomes[1:]) - {y0})
                if distinct:
                    rows = [tuple(v - b for v, b in zip(y, y0)) for y in distinct]
                    supportable = primal_margin_exact(rows).value >= 0
                else:
                    supportable = True
                result = generate_certificate(instance, candidate)
                report = CHECKER.verify(instance, result.certificate)
                self.assertEqual(report["status"], "VERIFIED")
                self.assertEqual(
                    result.certificate["claim"] != "nonnegative_weight_unsupported",
                    supportable,
                )
                if not supportable:
                    self.assertLessEqual(len(result.certificate["negative_payload"]["atoms"]), p)
                self.assertLessEqual(len(result.trace["iterations"]), len(distinct) + 1)
                cases += 1
        self.assertEqual(cases, 270)

    def test_reference_examples_and_p2_boundary(self):
        stems = [
            "explicit_tight_negative_p3",
            "explicit_boundary_support_p2",
            "assignment_positive_p3",
            "assignment_negative_p3",
            "shortest_path_positive_p3",
        ]
        for stem in stems:
            report = CHECKER.verify(example(stem, "instance"), example(stem, "certificate"))
            self.assertEqual(report["status"], "VERIFIED", stem)
        p2 = CHECKER.verify(
            example("binary_positive_p3_p2", "instance"),
            example("binary_positive_p3_p2", "certificate"),
        )
        self.assertEqual(p2["status"], "VALIDATED_NOT_FULLY_VERIFIED")

    def test_deterministic_generation(self):
        for stem in (
            "explicit_tight_negative_p3",
            "assignment_negative_p3",
            "assignment_positive_p3",
            "shortest_path_positive_p3",
            "binary_positive_p3_p2",
        ):
            instance = example(stem, "instance")
            candidate = example(stem, "candidate")
            first = generate_certificate(instance, candidate)
            second = generate_certificate(deepcopy(instance), deepcopy(candidate))
            self.assertEqual(canonical_json_bytes(first.certificate), canonical_json_bytes(second.certificate))
            self.assertEqual(canonical_json_bytes(first.trace), canonical_json_bytes(second.trace))

    def test_clean_environment_checker(self):
        checker = ROOT / "checker" / "verify_certificate.py"
        with tempfile.TemporaryDirectory() as tmp:
            for stem, expected in (
                ("explicit_tight_negative_p3", 0),
                ("assignment_positive_p3", 0),
                ("shortest_path_positive_p3", 0),
                ("binary_positive_p3_p2", 2),
            ):
                instance_path = ROOT / "examples" / "instances" / f"{stem}.json"
                cert_path = ROOT / "examples" / "certificates" / f"{stem}_certificate.json"
                proc = subprocess.run(
                    [sys.executable, "-I", str(checker), "--instance", str(instance_path), "--certificate", str(cert_path)],
                    cwd=tmp,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(proc.returncode, expected, (stem, proc.stdout, proc.stderr))
                self.assertEqual(proc.stderr, "")
                payload = json.loads(proc.stdout)
                self.assertIn(payload["status"], {"VERIFIED", "VALIDATED_NOT_FULLY_VERIFIED"})

    def test_checker_import_independence(self):
        checker = ROOT / "checker" / "verify_certificate.py"
        tree = ast.parse(checker.read_text(encoding="utf-8"))
        forbidden = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                forbidden.extend(alias.name for alias in node.names if alias.name.startswith("pareto_support"))
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("pareto_support"):
                forbidden.append(node.module)
        self.assertEqual(forbidden, [])
        self.assertNotIn("jsonschema", checker.read_text(encoding="utf-8"))
        self.assertNotIn("scipy", checker.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
