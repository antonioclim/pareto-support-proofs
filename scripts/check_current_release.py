#!/usr/bin/env python3
"""Read-only metadata and source checks for the current repository root.

The frozen ESM preserves the canonical engine and historical scripts. This
operational overlay neither regenerates nor rewrites retained evidence.
"""
from __future__ import annotations

import argparse
import ast
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import tomllib

import yaml

ROOT = Path(__file__).resolve().parents[1]
CURRENT_VERSION = "0.6.2"
RETAINED_GENERATOR_VERSION = "0.6.1"
STANDALONE_CHECKER_VERSION = "0.6.1"
DISTRIBUTION_VERSION = "OPTL-R1-20261017"
COMPANION_DOI = "10.5281/zenodo.23440598"
COMPANION_DATE = "2026-10-17"
COMPANION_TITLE = "Pareto Support Proofs: repaired R1 controlled-reproduction companion"
COMPANION_URL = "https://zenodo.org/records/23440598"
EXPECTED_TITLE = "Pareto Support Proofs: exact certificates and standalone verification"
CORE_PREFIXES = ("src/", "checker/", "schemas/", "tests/")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate(root: Path = ROOT) -> dict:
    checks: dict[str, bool] = {}
    details: dict = {}
    errors: dict[str, str] = {}

    def check(name, operation):
        try:
            value = operation()
            checks[name] = True
            if value is not None:
                details[name] = value
        except Exception as exc:
            checks[name] = False
            errors[name] = f"{type(exc).__name__}: {exc}"

    def metadata():
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        citation = yaml.safe_load((root / "CITATION.cff").read_text(encoding="utf-8"))
        archive = load_json(root / ".zenodo.json")
        codemeta = load_json(root / "codemeta.json")
        versions = {str(project["version"]), str(citation["version"]), str(archive["version"]),
                    str(codemeta["version"]), (root / "VERSION").read_text().strip()}
        assert versions == {CURRENT_VERSION}, f"Version mismatch: {sorted(versions)}"
        init = ast.parse((root / "src/pareto_support_proofs/__init__.py").read_text())
        init_version = next(ast.literal_eval(n.value) for n in init.body
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__version__" for t in n.targets))
        assert init_version == CURRENT_VERSION
        assert citation["title"] == archive["title"] == EXPECTED_TITLE
        assert project["name"] == "pareto-support-proofs"
        assert project["requires-python"] == ">=3.11"
        assert project["license"] == citation["license"] == "BSD-3-Clause"
        assert archive["license"] == "bsd-3-clause"
        assert project["license-files"] == ["LICENSE", "LICENSE-DATA.md", "NOTICE", "AUTHORS.md"]
        assert citation["type"] == "software" and archive["upload_type"] == "software"
        orcid = "0000-0003-4745-0431"
        assert citation["authors"][0]["orcid"].endswith(orcid)
        assert archive["creators"][0]["orcid"] == orcid
        assert codemeta["author"][0]["identifier"].endswith(orcid)
        assert citation["authors"][0]["affiliation"] == archive["creators"][0]["affiliation"] == codemeta["author"][0]["affiliation"]["name"]
        # Root records identify engine0.6.2; the exact DOI/date belong to the
        # published companion relation, not a newly archived source snapshot.
        companion = citation["preferred-citation"]
        assert companion["type"] == "software" and companion["title"] == COMPANION_TITLE
        assert str(companion["version"]) == DISTRIBUTION_VERSION
        assert companion["doi"] == COMPANION_DOI
        assert str(companion["date-released"]) == COMPANION_DATE
        assert companion["url"] == COMPANION_URL
        assert companion["authors"] == citation["authors"]
        assert companion["license"] == ["BSD-3-Clause", "CC-BY-4.0"]
        assert {"relation": "isPartOf", "identifier": COMPANION_DOI,
                "scheme": "doi"} in archive["related_identifiers"]
        part = codemeta["isPartOf"]
        assert part["@type"] == "SoftwareSourceCode" and part["name"] == COMPANION_TITLE
        assert part["version"] == DISTRIBUTION_VERSION
        assert part["identifier"] == "https://doi.org/" + COMPANION_DOI
        assert part["url"] == COMPANION_URL and part["datePublished"] == COMPANION_DATE
        assert all("unpublished" not in value for value in
                   [citation["message"], archive["description"], codemeta["description"]])
        assert all(COMPANION_DOI in value for value in
                   [archive["description"], codemeta["description"]])
        assert "doi" not in citation and "doi" not in archive
        assert "date-released" not in citation and "publication_date" not in archive
        assert "datePublished" not in codemeta
        return {"current_generator": CURRENT_VERSION,
                "metadata_state": "source engine linked to published companion",
                "distribution_version": DISTRIBUTION_VERSION,
                "companion_DOI": COMPANION_DOI, "companion_date": COMPANION_DATE,
                "retained_generator": RETAINED_GENERATOR_VERSION,
                "standalone_checker": STANDALONE_CHECKER_VERSION}

    def manifest():
        manifest = load_json(root / "CURRENT_SOURCE_MANIFEST.json")
        assert manifest["current_generator"] == CURRENT_VERSION
        assert manifest["retained_generator"] == RETAINED_GENERATOR_VERSION
        rows = manifest["files"]
        assert len(rows) == len(set(rows))
        for rel, expected in rows.items():
            posix = PurePosixPath(rel)
            assert not posix.is_absolute() and ".." not in posix.parts and "\\" not in rel and ":" not in rel
            path = root / rel
            assert path.is_file(), f"Missing pinned file: {rel}"
            data = path.read_bytes()
            assert len(data) == expected["bytes"] and sha256(data).hexdigest() == expected["sha256"], f"Pinned file differs: {rel}"
        actual_core = set()
        for prefix in CORE_PREFIXES:
            for path in (root / prefix).rglob("*"):
                if path.is_file() and not any(part == "__pycache__" or part.endswith(".egg-info") for part in path.relative_to(root).parts) and path.suffix not in [".pyc", ".pyo"]:
                    actual_core.add(path.relative_to(root).as_posix())
        expected_core = {rel for rel in rows if rel.startswith(CORE_PREFIXES)}
        assert actual_core == expected_core, f"Core path-set mismatch: {sorted(actual_core ^ expected_core)}"
        return {"pinned_files": len(rows), "canonical_core_files": len(expected_core),
                "scope": manifest["scope"], "not_a_signature": True}

    def syntax_and_suite():
        methods = []
        modules = []
        for prefix in ["src", "checker", "tests"]:
            for path in sorted((root / prefix).rglob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                modules.append(path.relative_to(root).as_posix())
                if prefix == "tests":
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                            methods.append(path.relative_to(root).as_posix() + "::" + node.name)
        assert len(methods) == 37, f"Expected37 test methods, found {len(methods)}"
        return {"parsed_Python_modules": len(modules), "test_methods": len(methods),
                "test_execution": "Separate unittest step; not implied by AST inspection"}

    def retained_evidence():
        reference = load_json(root / "examples/reference_manifest.json")
        assert reference["count"] == 9
        certificates = sorted((root / "results/certificates").glob("*.json"))
        assert len(certificates) == len(list((root / "results/instances").glob("*.json"))) == len(list((root / "results/traces").glob("*.json"))) == 225
        counts = {"P1_FULLY_CHECKABLE": 0, "P2_TRUSTED_ORACLE": 0}
        for path in certificates:
            cert = load_json(path)
            assert cert["provenance"]["generator"]["version"] == RETAINED_GENERATOR_VERSION
            counts[cert["trust_level"]] += 1
        assert counts == {"P1_FULLY_CHECKABLE": 213, "P2_TRUSTED_ORACLE": 12}
        return {"objects": 225, "trust_counts": counts,
                "scope": "Count/provenance checks, not regenerated certificates, new global proofs or timing experiments"}

    check("current_metadata", metadata)
    check("pinned_current_and_retained_files", manifest)
    check("Python_syntax_and_37_test_inventory", syntax_and_suite)
    check("retained_061_evidence_boundary", retained_evidence)
    failures = sorted(name for name, passed in checks.items() if not passed)
    return {"schema": "pareto-support-current-root-check-1", "status": "PASS" if not failures else "FAIL",
            "current_generator": CURRENT_VERSION, "retained_generator": RETAINED_GENERATOR_VERSION,
            "standalone_checker": STANDALONE_CHECKER_VERSION, "checks": checks, "details": details,
            "failure_count": len(failures), "failures": failures, "errors": errors,
            "scientific_campaign_executed": False, "publication_action_executed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, help="Optional explicit report path; no default evidence overwrite")
    args = parser.parse_args()
    result = validate(args.root.resolve())
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
