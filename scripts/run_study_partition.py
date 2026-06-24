#!/usr/bin/env python3
"""Partitioned execution wrapper for the computational study."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time
from hashlib import sha256
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import run_study as s

from pareto_support_proofs.canonical import canonical_json_bytes
from pareto_support_proofs.generator import generate_certificate
from pareto_support_proofs.study_instances import (
    enumerate_evaluated,
    make_grid_interval_explicit,
    make_large_assignment_positive,
    make_large_shortest_path,
    make_random_assignment,
    make_random_explicit,
    make_random_knapsack,
    make_random_shortest_path,
    make_tight_explicit,
    select_candidates_independently,
)

PARTIAL = s.RESULTS / "partial"
PARTIAL.mkdir(parents=True, exist_ok=True)


def save(name: str, payload: dict[str, Any]) -> None:
    s.write_json(PARTIAL / f"{name}.json", payload)
    print(PARTIAL / f"{name}.json")


def correctness_family(family: str, p: int, seed_only: int | None = None) -> int:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if family == "explicit":
        seeds = range(1001, 1016)
        constructor = lambda seed: make_random_explicit(p=p, alternatives=24, seed=seed + 10000 * p)
        label = "explicit_image"
        offset = 11
    elif family == "assignment":
        seeds = range(2001, 2006)
        constructor = lambda seed: make_random_assignment(n=5, p=p, seed=seed + 10000 * p)
        label = "assignment"
        offset = 13
    elif family == "shortest_path":
        seeds = range(3001, 3006)
        constructor = lambda seed: make_random_shortest_path(n=8, p=p, seed=seed + 10000 * p)
        label = "shortest_path"
        offset = 17
    elif family == "knapsack":
        seeds = range(4001, 4005)
        constructor = lambda seed: make_random_knapsack(n=10, p=p, seed=seed + 10000 * p)
        label = "binary_knapsack"
        offset = 19
    else:
        raise ValueError(family)
    if seed_only is not None:
        if seed_only not in seeds:
            raise ValueError(f"seed {seed_only} is outside the preregistered partition for {family}")
        seeds = (seed_only,)
    for seed in seeds:
        print(f"[{family}] p={p} seed={seed}", flush=True)
        instance = constructor(seed)
        evaluated = enumerate_evaluated(instance)
        for origin, item in select_candidates_independently(evaluated, seed=seed + offset * p):
            case_id = f"{family}_p{p}_s{seed}_{origin}"
            rows.append(s.process_correctness_case(case_id=case_id, family=label, source="random", instance=instance, candidate=item.decision, evaluated=evaluated, candidate_origin=origin, failures=failures))
    suffix = f"_s{seed_only}" if seed_only is not None else ""
    save(f"correctness_{family}_p{p}{suffix}", {"kind": "correctness", "rows": rows, "failures": failures})
    return 0 if not any(x.get("severity") == "critical" for x in failures) else 3


def controlled() -> int:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for p in (2, 3, 4, 5):
        print(f"[controlled tight] p={p}", flush=True)
        instance, candidate = make_tight_explicit(p=p)
        evaluated = enumerate_evaluated(instance)
        rows.append(s.process_correctness_case(case_id=f"tight_explicit_p{p}", family="explicit_image", source="controlled_tight", instance=instance, candidate=candidate, evaluated=evaluated, candidate_origin="fixed_algebraically", failures=failures))
    for q in (100000, 1000000, 10000000):
        print(f"[controlled grid] q={q}", flush=True)
        instance, candidate, _ = make_grid_interval_explicit(q=q)
        evaluated = enumerate_evaluated(instance)
        rows.append(s.process_correctness_case(case_id=f"narrow_interval_q{q}", family="explicit_image", source="controlled_grid", instance=instance, candidate=candidate, evaluated=evaluated, candidate_origin="fixed_algebraically", failures=failures))
    save("correctness_controlled", {"kind": "correctness", "rows": rows, "failures": failures})
    return 0 if not any(x.get("severity") == "critical" for x in failures) else 3


def reference() -> int:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    manifest = json.loads((s.ROOT / "examples" / "reference_manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["cases"]:
        stem = entry["case"]
        print(f"[reference] {stem}", flush=True)
        instance = json.loads((s.ROOT / "examples" / "instances" / f"{stem}.json").read_text(encoding="utf-8"))
        candidate = json.loads((s.ROOT / "examples" / "candidates" / f"{stem}_candidate.json").read_text(encoding="utf-8"))
        evaluated = enumerate_evaluated(instance)
        rows.append(s.process_correctness_case(case_id=f"reference_{stem}", family=instance["problem"]["type"], source="reference_regression", instance=instance, candidate=candidate, evaluated=evaluated, candidate_origin="reference_fixed", failures=failures))
    save("correctness_reference", {"kind": "correctness", "rows": rows, "failures": failures})
    return 0 if not any(x.get("severity") == "critical" for x in failures) else 3


def scaling_assignment(n: int) -> int:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for p in (2, 3, 4):
        print(f"[scaling assignment] n={n} p={p}", flush=True)
        instance, candidate = make_large_assignment_positive(n=n, p=p, seed=5100 + n * 10 + p)
        rows.append(s.process_scaling_case(f"assignment_n{n}_p{p}_supportable", "assignment", instance, candidate, "supportable", s.factorial_log10(n), failures))
    save(f"scaling_assignment_n{n}", {"kind": "scaling", "rows": rows, "failures": failures})
    return 0 if not any(x.get("severity") == "critical" for x in failures) else 3


def scaling_shortest(length: int, p: int | None = None) -> int:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    dimensions = (p,) if p is not None else (2, 3, 4)
    for dim in dimensions:
        for claim in ("supportable", "unsupported"):
            print(f"[scaling shortest] L={length} p={dim} {claim}", flush=True)
            instance, candidate, logcat = make_large_shortest_path(p=dim, path_length=length, claim=claim, seed=6200 + length * 10 + dim)
            rows.append(s.process_scaling_case(f"shortest_path_L{length}_p{dim}_{claim}", "shortest_path", instance, candidate, claim, logcat, failures))
    suffix = f"_p{p}" if p is not None else ""
    save(f"scaling_shortest_L{length}{suffix}", {"kind": "scaling", "rows": rows, "failures": failures})
    return 0 if not any(x.get("severity") == "critical" for x in failures) else 3


def timing_one(case_id: str) -> int:
    matches = [item for item in s.timing_case_definitions() if item[0] == case_id]
    if len(matches) != 1:
        raise SystemExit(f"unknown timing case {case_id}")
    case_id, instance, candidate = matches[0]
    instance_path, candidate_path, certificate_path, trace_path = s.case_paths(case_id)
    s.write_json(instance_path, instance)
    s.write_json(candidate_path, candidate)
    base = generate_certificate(instance, candidate, context={"case_id": case_id, "protocol_sha256": s.PROTOCOL_DIGEST})
    s.write_json(certificate_path, base.certificate, canonical=True)
    s.write_json(trace_path, base.trace, canonical=True)
    digest = sha256(canonical_json_bytes(base.certificate)).hexdigest()
    for _ in range(3):
        generate_certificate(instance, candidate, context={"case_id": case_id, "protocol_sha256": s.PROTOCOL_DIGEST})
        s.checker_file(instance_path, certificate_path)
    raw: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for repetition in range(1, 31):
        start = time.perf_counter_ns()
        generated = generate_certificate(instance, candidate, context={"case_id": case_id, "protocol_sha256": s.PROTOCOL_DIGEST})
        generation_ms = (time.perf_counter_ns() - start) / 1_000_000
        current_digest = sha256(canonical_json_bytes(generated.certificate)).hexdigest()
        code, report, checker_ms = s.checker_file(instance_path, certificate_path)
        if code not in (0, 2):
            failures.append({"severity": "critical", "component": "timing", "case_id": case_id, "category": "checker_failure", "message": json.dumps(report, sort_keys=True)})
        raw.append({"case_id": case_id, "repetition": repetition, "generation_ms": generation_ms, "checker_kernel_ms": checker_ms, "digest_match": current_digest == digest, "claim": base.certificate["claim"], "trust_level": base.certificate["trust_level"], **s.certificate_metrics(generated.certificate, generated.trace)})
    generation = [float(row["generation_ms"]) for row in raw]
    checking = [float(row["checker_kernel_ms"]) for row in raw]
    gq1, gq3 = s.quartile(generation, 0.25), s.quartile(generation, 0.75)
    cq1, cq3 = s.quartile(checking, 0.25), s.quartile(checking, 0.75)
    gci = s.bootstrap_ci(generation, seed=8100 + sum(case_id.encode()))
    cci = s.bootstrap_ci(checking, seed=8101 + sum(case_id.encode()))
    gmed, cmed = statistics.median(generation), statistics.median(checking)
    summary = {"case_id": case_id, "claim": base.certificate["claim"], "trust_level": base.certificate["trust_level"], "repetitions": len(raw), "deterministic": all(bool(row["digest_match"]) for row in raw), "generation_ms_median": gmed, "generation_ms_q1": gq1, "generation_ms_q3": gq3, "generation_ms_iqr": gq3 - gq1, "generation_ms_ci95_low": gci[0], "generation_ms_ci95_high": gci[1], "checker_ms_median": cmed, "checker_ms_q1": cq1, "checker_ms_q3": cq3, "checker_ms_iqr": cq3 - cq1, "checker_ms_ci95_low": cci[0], "checker_ms_ci95_high": cci[1], "generation_to_checker_ratio": gmed / cmed if cmed > 0 else float("inf"), **s.certificate_metrics(base.certificate, base.trace)}
    save(f"timing_{case_id}", {"kind": "timing", "raw": raw, "summary": summary, "failures": failures})
    return 0 if not failures else 3


def aggregate() -> int:
    correctness: list[dict[str, Any]] = []
    scaling: list[dict[str, Any]] = []
    timing_raw: list[dict[str, Any]] = []
    timing_summary: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for path in sorted(PARTIAL.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        failures.extend(payload.get("failures", []))
        if payload.get("kind") == "correctness":
            correctness.extend(payload.get("rows", []))
        elif payload.get("kind") == "scaling":
            scaling.extend(payload.get("rows", []))
        elif payload.get("kind") == "timing":
            timing_raw.extend(payload.get("raw", []))
            timing_summary.append(payload["summary"])
    correctness.sort(key=lambda row: row["case_id"])
    scaling.sort(key=lambda row: row["case_id"])
    timing_raw.sort(key=lambda row: (row["case_id"], int(row["repetition"])))
    timing_summary.sort(key=lambda row: row["case_id"])
    expected_correctness = 190
    expected_scaling = 27
    expected_timing = 8
    if len(correctness) != expected_correctness:
        failures.append({"severity": "critical", "component": "aggregate", "case_id": "correctness", "category": "incomplete_partition_set", "message": f"expected {expected_correctness}, found {len(correctness)}"})
    if len(scaling) != expected_scaling:
        failures.append({"severity": "critical", "component": "aggregate", "case_id": "scaling", "category": "incomplete_partition_set", "message": f"expected {expected_scaling}, found {len(scaling)}"})
    if len(timing_summary) != expected_timing:
        failures.append({"severity": "critical", "component": "aggregate", "case_id": "timing", "category": "incomplete_partition_set", "message": f"expected {expected_timing}, found {len(timing_summary)}"})
    s.write_csv(s.RAW / "correctness_cases.csv", correctness)
    s.write_csv(s.RAW / "scaling_cases.csv", scaling)
    s.write_csv(s.RAW / "timing_repetitions.csv", timing_raw)
    s.write_csv(s.PROCESSED / "timing_summary.csv", timing_summary)
    grid, ff = s.build_grid_audit(); failures.extend(ff); s.write_csv(s.RAW / "grid_baseline.csv", grid)
    tightness, ff = s.direct_tightness_audit(); failures.extend(ff); s.write_csv(s.RAW / "tightness.csv", tightness)
    mutations, ff = s.build_mutation_audit(correctness); failures.extend(ff); s.write_csv(s.RAW / "mutations.csv", mutations)
    unit = s.run_unit_tests()
    imports = s.checker_import_audit()
    if not unit["pass"]:
        failures.append({"severity": "critical", "component": "software", "case_id": "unit_tests", "category": "unit_test_failure", "message": str(unit)})
    if not imports["pass"]:
        failures.append({"severity": "critical", "component": "software", "case_id": "checker", "category": "import_boundary_failure", "message": str(imports)})
    s.write_csv(s.RAW / "failures.csv", failures, fieldnames=["severity", "component", "case_id", "category", "message"])
    summary = s.build_summary(correctness, scaling, timing_summary, grid, tightness, mutations, failures, unit, imports)
    s.write_json(s.PROCESSED / "study_summary.json", summary)
    s.write_json(s.VALIDATION / "study_summary.json", summary)
    s.write_json(s.VALIDATION / "study_environment.json", s.environment_record())
    s.write_json(s.VALIDATION / "checker_imports.json", imports)
    s.make_figures(correctness, scaling, timing_summary, grid)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["validation_status"] == "PASS_WITH_DECLARED_P2_BOUNDARY" else 3


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("correctness")
    p.add_argument("--family", required=True, choices=["explicit", "assignment", "shortest_path", "knapsack"])
    p.add_argument("--p", required=True, type=int, choices=[2, 3, 4])
    p.add_argument("--seed", type=int)
    sub.add_parser("controlled")
    sub.add_parser("reference")
    p = sub.add_parser("scaling-assignment"); p.add_argument("--n", required=True, type=int, choices=[20, 40, 60])
    p = sub.add_parser("scaling-shortest"); p.add_argument("--length", required=True, type=int, choices=[20, 100, 400]); p.add_argument("--p", type=int, choices=[2, 3, 4])
    p = sub.add_parser("timing"); p.add_argument("--case-id", required=True)
    sub.add_parser("aggregate")
    args = parser.parse_args()
    s.ensure_dirs()
    if args.command == "correctness": return correctness_family(args.family, args.p, args.seed)
    if args.command == "controlled": return controlled()
    if args.command == "reference": return reference()
    if args.command == "scaling-assignment": return scaling_assignment(args.n)
    if args.command == "scaling-shortest": return scaling_shortest(args.length, args.p)
    if args.command == "timing": return timing_one(args.case_id)
    return aggregate()


if __name__ == "__main__":
    raise SystemExit(main())
