#!/usr/bin/env python3
"""Run the complete local validation of the retained public release."""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import scan_release
import validate_metadata

VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
VALIDATION = ROOT / "validation"


class DuplicateKeyError(ValueError):
    pass


def strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=strict_pairs)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_checker():
    path = ROOT / "checker" / "verify_certificate.py"
    spec = importlib.util.spec_from_file_location("retained_release_checker", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load standalone checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_tests() -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=300,
    )
    count = 0
    for line in proc.stdout.splitlines():
        if line.startswith("Ran ") and " tests" in line:
            try:
                count = int(line.split()[1])
            except (IndexError, ValueError):
                pass
    return {
        "exit_code": proc.returncode,
        "tests_reported": count,
        "status": "PASS" if proc.returncode == 0 else "FAIL",
    }


def iter_json_files() -> Iterable[Path]:
    for path in sorted(ROOT.rglob("*.json")):
        if any(part in {".git", ".venv", "venv", "__pycache__", "build", "dist"} for part in path.parts):
            continue
        yield path


def validate_json_and_schemas() -> dict[str, Any]:
    parsed = 0
    duplicate_failures: list[str] = []
    for path in iter_json_files():
        try:
            load_json(path)
            parsed += 1
        except Exception as exc:
            duplicate_failures.append(f"{path.relative_to(ROOT).as_posix()}: {type(exc).__name__}: {exc}")

    instance_schema = load_json(ROOT / "schemas/instance-v1.schema.json")
    certificate_schema = load_json(ROOT / "schemas/certificate-v1.schema.json")
    trace_schema = load_json(ROOT / "schemas/trace-v1.schema.json")
    validators = {
        "instances": jsonschema.Draft202012Validator(instance_schema),
        "certificates": jsonschema.Draft202012Validator(certificate_schema),
        "traces": jsonschema.Draft202012Validator(trace_schema),
    }
    counts = {name: 0 for name in validators}
    schema_failures: list[str] = []
    bases = [ROOT / "examples", ROOT / "results"]
    for base in bases:
        for name, validator in validators.items():
            directory = base / name
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.json")):
                try:
                    validator.validate(load_json(path))
                    counts[name] += 1
                except Exception as exc:
                    schema_failures.append(f"{path.relative_to(ROOT).as_posix()}: {type(exc).__name__}: {exc}")
    failures = duplicate_failures + schema_failures
    return {
        "json_files_parsed": parsed,
        "schema_validated": counts,
        "failure_count": len(failures),
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
    }


def replay_corpus() -> dict[str, Any]:
    checker = load_checker()
    certificate_paths = sorted((ROOT / "results/certificates").glob("*.json"))
    p1 = 0
    p2 = 0
    failures: list[str] = []
    for certificate_path in certificate_paths:
        stem = certificate_path.stem
        instance_path = ROOT / "results/instances" / f"{stem}.json"
        try:
            instance = checker.load_json_strict(str(instance_path))
            certificate = checker.load_json_strict(str(certificate_path))
            report = checker.verify(instance, certificate)
            if certificate["trust_level"] == "P1_FULLY_CHECKABLE":
                p1 += 1
                if report["status"] != "VERIFIED":
                    failures.append(f"{stem}: expected VERIFIED, observed {report['status']}")
            elif certificate["trust_level"] == "P2_TRUSTED_ORACLE":
                p2 += 1
                if report["status"] != "VALIDATED_NOT_FULLY_VERIFIED":
                    failures.append(f"{stem}: expected conditional status, observed {report['status']}")
            else:
                failures.append(f"{stem}: unknown trust level")
        except Exception as exc:
            failures.append(f"{stem}: {type(exc).__name__}: {exc}")

    reference_failures: list[str] = []
    for certificate_path in sorted((ROOT / "examples/certificates").glob("*.json")):
        stem = certificate_path.stem.removesuffix("_certificate")
        instance_path = ROOT / "examples/instances" / f"{stem}.json"
        try:
            report = checker.verify(
                checker.load_json_strict(str(instance_path)),
                checker.load_json_strict(str(certificate_path)),
            )
            if report["status"] not in {"VERIFIED", "VALIDATED_NOT_FULLY_VERIFIED"}:
                reference_failures.append(f"{stem}: {report['status']}")
        except Exception as exc:
            reference_failures.append(f"{stem}: {type(exc).__name__}: {exc}")

    failures.extend(reference_failures)
    return {
        "certificates": len(certificate_paths),
        "p1_verified": p1,
        "p2_validated": p2,
        "reference_objects": len(list((ROOT / "examples/certificates").glob("*.json"))),
        "failure_count": len(failures),
        "failures": failures,
        "status": "PASS" if not failures and (len(certificate_paths), p1, p2) == (225, 213, 12) else "FAIL",
    }


def checker_imports() -> dict[str, Any]:
    path = ROOT / "checker/verify_certificate.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    non_standard = sorted(name for name in imports if name not in sys.stdlib_module_names and name != "__future__")
    return {
        "imports": sorted(imports),
        "non_standard_library_imports": non_standard,
        "status": "PASS" if not non_standard and "pareto_support_proofs" not in imports else "FAIL",
    }


def retained_evidence() -> dict[str, Any]:
    study = load_json(ROOT / "results/processed/study_summary.json")
    exact = load_json(ROOT / "validation/exact_falsification_summary.json")
    with (ROOT / "results/raw/mutations.csv").open(encoding="utf-8", newline="") as handle:
        mutations = list(csv.DictReader(handle))
    checks = {
        "study_version": study["software_version"] == VERSION,
        "complete_image_agreement": (study["correctness_agreements"], study["correctness_cases"]) == (190, 190),
        "mutation_rejection": (study["mutations_rejected"], study["mutations"]) == (24, 24),
        "mutation_rows": len(mutations) == 24 and all(row["rejected"].lower() == "true" for row in mutations),
        "study_status": study["validation_status"] == "PASS_WITH_DECLARED_P2_BOUNDARY",
        "exact_status": exact["verdict"] == "PASS",
        "exact_primal_dual_cases": exact["primal_dual_exhaustive"].get("instances") == 3426,
        "property_attacks": sum(exact["property_attacks"].values()) == 1100,
        "sat_cases": exact["sat_reduction"]["cases"] == 300,
    }
    failures = sorted(name for name, passed in checks.items() if not passed)
    return {
        "checks": checks,
        "failure_count": len(failures),
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
    }


def remove_transient_outputs() -> None:
    for directory in sorted(ROOT.rglob("*"), reverse=True):
        if not directory.is_dir():
            continue
        if directory.name in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist"} or directory.name.endswith(".egg-info"):
            shutil.rmtree(directory, ignore_errors=True)
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix in {".pyc", ".pyo", ".tmp", ".bak"}:
            path.unlink(missing_ok=True)


def excluded_from_manifest(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "build", "dist"} for part in relative.parts):
        return True
    if path.name in {"FILE_MANIFEST.sha256", "manifest_summary.json"} or path.suffix in {".pyc", ".pyo"}:
        return True
    return False


def write_manifest() -> dict[str, Any]:
    lines: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or excluded_from_manifest(path):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(ROOT).as_posix()}")
    manifest = VALIDATION / "FILE_MANIFEST.sha256"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "files": len(lines),
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    VALIDATION.mkdir(parents=True, exist_ok=True)

    metadata = validate_metadata.validate()
    write_json(VALIDATION / "metadata_summary.json", metadata)
    json_summary = validate_json_and_schemas()
    write_json(VALIDATION / "json_schema_summary.json", json_summary)
    replay = replay_corpus()
    write_json(VALIDATION / "corpus_replay.json", replay)
    imports = checker_imports()
    write_json(VALIDATION / "checker_imports.json", imports)
    tests = run_tests()
    write_json(VALIDATION / "test_summary.json", tests)
    evidence = retained_evidence()
    write_json(VALIDATION / "evidence_summary.json", evidence)

    remove_transient_outputs()
    hygiene = scan_release.scan(ROOT)
    write_json(VALIDATION / "release_hygiene.json", hygiene)

    components = {
        "metadata": metadata["status"],
        "json_and_schemas": json_summary["status"],
        "corpus_replay": replay["status"],
        "checker_imports": imports["status"],
        "tests": tests["status"],
        "retained_evidence": evidence["status"],
        "release_hygiene": hygiene["status"],
    }
    release = {
        "schema": "pareto-support-release-validation-1.0",
        "software_version": VERSION,
        "components": components,
        "corpus_replay": {
            "certificates": replay["certificates"],
            "p1_verified": replay["p1_verified"],
            "p2_validated": replay["p2_validated"],
        },
        "status": "PASS_WITH_DECLARED_P2_BOUNDARY" if all(value == "PASS" for value in components.values()) else "FAIL",
    }
    write_json(VALIDATION / "release_summary.json", release)

    # The second pass includes the release summary generated above.
    hygiene = scan_release.scan(ROOT)
    write_json(VALIDATION / "release_hygiene.json", hygiene)
    components["release_hygiene"] = hygiene["status"]
    release["components"] = components
    release["status"] = "PASS_WITH_DECLARED_P2_BOUNDARY" if all(value == "PASS" for value in components.values()) else "FAIL"
    write_json(VALIDATION / "release_summary.json", release)
    manifest = write_manifest()
    write_json(VALIDATION / "manifest_summary.json", manifest)

    output = dict(release)
    output["manifest"] = manifest
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if release["status"] == "PASS_WITH_DECLARED_P2_BOUNDARY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
