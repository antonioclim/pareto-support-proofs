#!/usr/bin/env python3
"""Regenerate every reference proof object deterministically and verify it.

The script writes canonical JSON. It uses the generator package to create proof
objects then loads the standalone checker as an independent module. A second
in-memory generation is compared byte-for-byte before any artefact is kept.
Process isolation is audited separately by the clean-environment test suite.
"""
from __future__ import annotations

import json
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pareto_support_proofs.canonical import canonical_json_bytes, dump_json_canonical, load_json_strict
from pareto_support_proofs.generator import generate_certificate


def load_checker():
    path = ROOT / "checker" / "verify_certificate.py"
    spec = importlib.util.spec_from_file_location("reference_checker", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load standalone checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = load_checker()

CASES = {
    "explicit_positive_p2": ("positive_weight_supportable", "P1_FULLY_CHECKABLE", 0),
    "explicit_boundary_support_p2": ("nonnegative_weight_supportable", "P1_FULLY_CHECKABLE", 0),
    "explicit_tight_negative_p3": ("nonnegative_weight_unsupported", "P1_FULLY_CHECKABLE", 0),
    "assignment_positive_p3": ("positive_weight_supportable", "P1_FULLY_CHECKABLE", 0),
    "assignment_negative_p3": ("nonnegative_weight_unsupported", "P1_FULLY_CHECKABLE", 0),
    "shortest_path_positive_p3": ("positive_weight_supportable", "P1_FULLY_CHECKABLE", 0),
    "shortest_path_negative_p2": ("nonnegative_weight_unsupported", "P1_FULLY_CHECKABLE", 0),
    "binary_positive_p3_p2": ("positive_weight_supportable", "P2_TRUSTED_ORACLE", 2),
    "binary_negative_p2": ("nonnegative_weight_unsupported", "P1_FULLY_CHECKABLE", 0),
}


def main() -> int:
    certificate_dir = ROOT / "examples" / "certificates"
    trace_dir = ROOT / "examples" / "traces"
    report_dir = ROOT / "examples" / "reports"
    for directory in (certificate_dir, trace_dir, report_dir):
        directory.mkdir(parents=True, exist_ok=True)
        for path in directory.glob("*.json"):
            path.unlink()

    summary = []
    for stem, (expected_claim, expected_trust, expected_exit) in CASES.items():
        print(f"[regenerate] {stem}", flush=True)
        instance_path = ROOT / "examples" / "instances" / f"{stem}.json"
        candidate_path = ROOT / "examples" / "candidates" / f"{stem}_candidate.json"
        certificate_path = certificate_dir / f"{stem}_certificate.json"
        trace_path = trace_dir / f"{stem}_trace.json"
        report_path = report_dir / f"{stem}_report.json"

        instance = load_json_strict(instance_path)
        candidate = load_json_strict(candidate_path)
        first = generate_certificate(instance, candidate)
        second = generate_certificate(instance, candidate)
        if canonical_json_bytes(first.certificate) != canonical_json_bytes(second.certificate):
            raise AssertionError(f"non-deterministic certificate for {stem}")
        if canonical_json_bytes(first.trace) != canonical_json_bytes(second.trace):
            raise AssertionError(f"non-deterministic trace for {stem}")
        if first.certificate["claim"] != expected_claim:
            raise AssertionError(f"unexpected claim for {stem}: {first.certificate['claim']}")
        if first.certificate["trust_level"] != expected_trust:
            raise AssertionError(f"unexpected trust level for {stem}")

        dump_json_canonical(first.certificate, certificate_path)
        dump_json_canonical(first.trace, trace_path)
        report = CHECKER.verify(instance, first.certificate)
        expected_status = "VALIDATED_NOT_FULLY_VERIFIED" if expected_exit == 2 else "VERIFIED"
        if report["status"] != expected_status:
            raise AssertionError(f"checker status failed for {stem}: {report}")
        dump_json_canonical(report, report_path)
        summary.append(
            {
                "case": stem,
                "claim": first.certificate["claim"],
                "trust_level": first.certificate["trust_level"],
                "checker_status": report["status"],
                "certificate_digest": first.certificate["integrity"]["certificate_digest"],
            }
        )

    dump_json_canonical({"cases": summary, "count": len(summary)}, ROOT / "examples" / "reference_manifest.json")
    print(json.dumps({"regenerated": len(summary), "status": "ok"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
