from __future__ import annotations

import importlib.util
import json
import re
import tomllib
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.6.1"


class ReleaseIntegrityTests(unittest.TestCase):
    def test_version_and_licence_metadata_are_consistent(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
        codemeta = json.loads((ROOT / "codemeta.json").read_text(encoding="utf-8"))
        archive = json.loads((ROOT / ".zenodo.json").read_text(encoding="utf-8"))
        versions = {
            project["project"]["version"],
            str(citation["version"]),
            str(codemeta["version"]),
            str(archive["version"]),
            (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        }
        self.assertEqual(versions, {VERSION})
        self.assertEqual(project["project"]["license"], "BSD-3-Clause")
        self.assertEqual(
            project["project"]["license-files"],
            ["LICENSE", "LICENSE-DATA.md", "NOTICE", "AUTHORS.md"],
        )
        self.assertEqual(citation["license"], "BSD-3-Clause")
        self.assertEqual(archive["license"], "bsd-3-clause")

    def test_public_metadata_contains_no_contact_address_or_release_identifier(self):
        paths = [
            ROOT / "pyproject.toml",
            ROOT / "CITATION.cff",
            ROOT / ".zenodo.json",
            ROOT / "codemeta.json",
            ROOT / "AUTHORS.md",
            ROOT / "NOTICE",
        ]
        email = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
        for path in paths:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(email.search(text), path.name)
        citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
        archive = json.loads((ROOT / ".zenodo.json").read_text(encoding="utf-8"))
        self.assertNotIn("doi", citation)
        self.assertNotIn("doi", archive)

    def test_reference_manifest_and_retained_corpus_are_complete(self):
        reference = json.loads((ROOT / "examples/reference_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(reference["count"], 9)
        certificate_paths = sorted((ROOT / "results/certificates").glob("*.json"))
        instance_paths = sorted((ROOT / "results/instances").glob("*.json"))
        trace_paths = sorted((ROOT / "results/traces").glob("*.json"))
        self.assertEqual((len(certificate_paths), len(instance_paths), len(trace_paths)), (225, 225, 225))
        trust_counts = {"P1_FULLY_CHECKABLE": 0, "P2_TRUSTED_ORACLE": 0}
        for path in certificate_paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            trust_counts[payload["trust_level"]] += 1
            self.assertEqual(payload["provenance"]["generator"]["version"], VERSION)
        self.assertEqual(trust_counts, {"P1_FULLY_CHECKABLE": 213, "P2_TRUSTED_ORACLE": 12})

    def test_standalone_checker_reports_release_version(self):
        checker_path = ROOT / "checker/verify_certificate.py"
        spec = importlib.util.spec_from_file_location("release_checker_test", checker_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec else None)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        instance = module.load_json_strict(str(ROOT / "examples/instances/explicit_tight_negative_p3.json"))
        certificate = module.load_json_strict(str(ROOT / "examples/certificates/explicit_tight_negative_p3_certificate.json"))
        self.assertEqual(module.verify(instance, certificate)["checker"]["version"], VERSION)


if __name__ == "__main__":
    unittest.main()
