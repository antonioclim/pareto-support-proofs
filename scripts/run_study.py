#!/usr/bin/env python3
"""Run the fixed computational study and retain case-level evidence.

Instances, classifications and proof objects are deterministic. Timing
measurements are environment dependent and are retained with a concise
environment record. Complete-image classification uses an exact support-
polytope vertex enumerator implemented independently of the certificate
generator. The standalone checker is loaded from its file and is also
exercised across a fresh process boundary.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import csv
from fractions import Fraction
from hashlib import sha256
import importlib.util
from importlib import metadata as importlib_metadata
import itertools
import json
import math
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import time
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pareto_support_proofs import __version__
from pareto_support_proofs.canonical import canonical_json_bytes
from pareto_support_proofs.generator import generate_certificate
from pareto_support_proofs.instance import evaluate_decision
from pareto_support_proofs.study_instances import (
    Evaluated,
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
    tight_rows,
)

try:
    import jsonschema
except Exception as exc:  # pragma: no cover - explicit audit dependency
    raise SystemExit(f"jsonschema is required for the computational study: {exc}")

PROTOCOL = ROOT / "protocol" / "computational_study_protocol.json"
PROTOCOL_DIGEST = sha256(PROTOCOL.read_bytes()).hexdigest()
CHECKER_PATH = ROOT / "checker" / "verify_certificate.py"
RESULTS = ROOT / "results"
RAW = RESULTS / "raw"
PROCESSED = RESULTS / "processed"
INSTANCES = RESULTS / "instances"
CANDIDATES = RESULTS / "candidates"
CERTIFICATES = RESULTS / "certificates"
TRACES = RESULTS / "traces"
FIGURES = ROOT / "figures"
VALIDATION = ROOT / "validation"


def ensure_dirs() -> None:
    for path in [RAW, PROCESSED, INSTANCES, CANDIDATES, CERTIFICATES, TRACES, FIGURES, VALIDATION]:
        path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any, *, canonical: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if canonical:
        path.write_bytes(canonical_json_bytes(payload) + b"\n")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[dict[str, Any]], fieldnames: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        order: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    order.append(key)
        fieldnames = order
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def load_checker():
    spec = importlib.util.spec_from_file_location("study_standalone_checker", CHECKER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load standalone checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = load_checker()
INSTANCE_SCHEMA = json.loads((ROOT / "schemas" / "instance-v1.schema.json").read_text(encoding="utf-8"))
CERTIFICATE_SCHEMA = json.loads((ROOT / "schemas" / "certificate-v1.schema.json").read_text(encoding="utf-8"))
TRACE_SCHEMA = json.loads((ROOT / "schemas" / "trace-v1.schema.json").read_text(encoding="utf-8"))


def dot(a: Sequence[Fraction | int], b: Sequence[Fraction | int]) -> Fraction:
    return sum((Fraction(x) * Fraction(y) for x, y in zip(a, b)), Fraction(0))


def solve_square_independent(a: Sequence[Sequence[Fraction]], b: Sequence[Fraction]) -> tuple[Fraction, ...] | None:
    """Independent exact Gaussian elimination used only by the full-image baseline."""
    n = len(a)
    if n == 0 or any(len(row) != n for row in a) or len(b) != n:
        raise ValueError("square system required")
    m = [list(map(Fraction, row)) + [Fraction(rhs)] for row, rhs in zip(a, b)]
    pivot_row = 0
    for column in range(n):
        pivot = next((r for r in range(pivot_row, n) if m[r][column] != 0), None)
        if pivot is None:
            return None
        if pivot != pivot_row:
            m[pivot_row], m[pivot] = m[pivot], m[pivot_row]
        scale = m[pivot_row][column]
        m[pivot_row] = [value / scale for value in m[pivot_row]]
        for r in range(n):
            if r == pivot_row:
                continue
            factor = m[r][column]
            if factor != 0:
                m[r] = [m[r][c] - factor * m[pivot_row][c] for c in range(n + 1)]
        pivot_row += 1
    return tuple(m[i][-1] for i in range(n))


def unique_nondominated_outcomes(evaluated: Sequence[Evaluated]) -> list[tuple[int, ...]]:
    unique = sorted(set(item.outcome for item in evaluated))
    out: list[tuple[int, ...]] = []
    for i, y in enumerate(unique):
        dominated = False
        for j, z in enumerate(unique):
            if i == j:
                continue
            if all(z[k] <= y[k] for k in range(len(y))) and any(z[k] < y[k] for k in range(len(y))):
                dominated = True
                break
        if not dominated:
            out.append(y)
    return out


def pareto_efficient(candidate: tuple[int, ...], evaluated: Sequence[Evaluated]) -> bool:
    for item in evaluated:
        y = item.outcome
        if all(y[i] <= candidate[i] for i in range(len(candidate))) and any(y[i] < candidate[i] for i in range(len(candidate))):
            return False
    return True


def exact_support_vertices(candidate: tuple[int, ...], efficient_outcomes: Sequence[tuple[int, ...]]) -> list[tuple[Fraction, ...]]:
    """Enumerate support-polytope vertices without calling the generator master."""
    p = len(candidate)
    differences = [tuple(y[i] - candidate[i] for i in range(p)) for y in efficient_outcomes]
    differences = sorted(set(row for row in differences if any(v != 0 for v in row)))
    if p == 1:
        return [(Fraction(1),)] if all(row[0] >= 0 for row in differences) else []
    inequalities: list[tuple[Fraction, ...]] = []
    for i in range(p):
        row = [Fraction(0)] * p
        row[i] = Fraction(1)
        inequalities.append(tuple(row))
    inequalities.extend(tuple(Fraction(v) for v in row) for row in differences)
    vertices: set[tuple[Fraction, ...]] = set()
    for active in itertools.combinations(range(len(inequalities)), p - 1):
        matrix = [[Fraction(1)] * p]
        rhs = [Fraction(1)]
        for idx in active:
            matrix.append(list(inequalities[idx]))
            rhs.append(Fraction(0))
        solution = solve_square_independent(matrix, rhs)
        if solution is None or any(v < 0 for v in solution):
            continue
        if all(dot(row, solution) >= 0 for row in differences):
            vertices.add(solution)
    return sorted(vertices)


def exact_ground_truth(candidate: tuple[int, ...], evaluated: Sequence[Evaluated]) -> dict[str, Any]:
    efficient = pareto_efficient(candidate, evaluated)
    frontier = unique_nondominated_outcomes(evaluated)
    start = time.perf_counter_ns()
    vertices = exact_support_vertices(candidate, frontier)
    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
    supportable = bool(vertices)
    positive = supportable and all(any(vertex[i] > 0 for vertex in vertices) for i in range(len(candidate)))
    if not efficient:
        semantic_class = "DOM"
    elif not supportable:
        semantic_class = "UNS"
    elif positive:
        semantic_class = "S+"
    else:
        semantic_class = "S0"
    return {
        "supportable": supportable,
        "positive_supportable": positive,
        "pareto_efficient": efficient,
        "semantic_class": semantic_class,
        "support_vertices": vertices,
        "frontier_outcomes": len(frontier),
        "ground_truth_ms": elapsed_ms,
    }


def analytic_interval_2d(candidate: tuple[int, int], evaluated: Sequence[Evaluated]) -> tuple[Fraction, Fraction] | None:
    lower, upper = Fraction(0), Fraction(1)
    for item in evaluated:
        d1 = item.outcome[0] - candidate[0]
        d2 = item.outcome[1] - candidate[1]
        # d2 + lambda (d1-d2) >= 0
        slope = d1 - d2
        if slope == 0:
            if d2 < 0:
                return None
            continue
        threshold = Fraction(-d2, slope)
        if slope > 0:
            lower = max(lower, threshold)
        else:
            upper = min(upper, threshold)
    lower = max(lower, Fraction(0))
    upper = min(upper, Fraction(1))
    return (lower, upper) if lower <= upper else None


def rational_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def checker_file(instance_path: Path, certificate_path: Path) -> tuple[int, dict[str, Any], float]:
    start = time.perf_counter_ns()
    try:
        instance = CHECKER.load_json_strict(str(instance_path))
        certificate = CHECKER.load_json_strict(str(certificate_path))
        report = CHECKER.verify(instance, certificate)
        code = 0 if report["status"] == "VERIFIED" else 2
    except CHECKER.Rejection as exc:
        report = {"status": "REJECTED", "error_code": exc.code, "message": exc.message}
        code = 1
    return code, report, (time.perf_counter_ns() - start) / 1_000_000


def checker_process(instance_path: Path, certificate_path: Path, *, require_p1: bool = False) -> tuple[int, dict[str, Any], float]:
    command = [sys.executable, "-I", "-S", str(CHECKER_PATH), "--instance", str(instance_path), "--certificate", str(certificate_path)]
    if require_p1:
        command.append("--require-p1")
    start = time.perf_counter_ns()
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=60)
    elapsed = (time.perf_counter_ns() - start) / 1_000_000
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
    try:
        report = json.loads(line)
    except json.JSONDecodeError:
        report = {"status": "MALFORMED_OUTPUT", "stdout": result.stdout, "stderr": result.stderr}
    return result.returncode, report, elapsed


def claim_polarity(claim: str) -> str:
    return "unsupported" if claim == "nonnegative_weight_unsupported" else "supportable"


def certificate_metrics(certificate: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
    payload = certificate.get("negative_payload")
    atoms = payload.get("atoms", []) if payload else []
    coefficients = [int(atom["coefficient"]) for atom in atoms]
    coefficient_sum = int(payload["coefficient_sum"]) if payload else 0
    return {
        "certificate_bytes": len(canonical_json_bytes(certificate)),
        "atom_count": len(atoms),
        "max_coefficient_bits": max((value.bit_length() for value in coefficients), default=0),
        "coefficient_sum_bits": coefficient_sum.bit_length() if coefficient_sum else 0,
        "strict_margin": payload.get("strict_margin", "") if payload else "",
        "oracle_calls": len(trace.get("iterations", [])),
    }


def case_paths(case_id: str) -> tuple[Path, Path, Path, Path]:
    return (
        INSTANCES / f"{case_id}.json",
        CANDIDATES / f"{case_id}.json",
        CERTIFICATES / f"{case_id}.json",
        TRACES / f"{case_id}.json",
    )


def process_correctness_case(
    *, case_id: str, family: str, source: str, instance: dict[str, Any], candidate: Any,
    evaluated: Sequence[Evaluated], candidate_origin: str, failures: list[dict[str, Any]],
) -> dict[str, Any]:
    instance_path, candidate_path, certificate_path, trace_path = case_paths(case_id)
    write_json(instance_path, instance)
    write_json(candidate_path, candidate)
    candidate_outcome = evaluate_decision(instance, candidate)
    ground = exact_ground_truth(candidate_outcome, evaluated)
    interval = analytic_interval_2d(candidate_outcome, evaluated) if len(candidate_outcome) == 2 else None
    start = time.perf_counter_ns()
    result = generate_certificate(instance, candidate, context={"case_id": case_id, "protocol_sha256": PROTOCOL_DIGEST})
    generation_ms = (time.perf_counter_ns() - start) / 1_000_000
    write_json(certificate_path, result.certificate, canonical=True)
    write_json(trace_path, result.trace, canonical=True)
    rerun = generate_certificate(instance, candidate, context={"case_id": case_id, "protocol_sha256": PROTOCOL_DIGEST})
    deterministic_certificate = canonical_json_bytes(result.certificate) == canonical_json_bytes(rerun.certificate)
    deterministic_trace = canonical_json_bytes(result.trace) == canonical_json_bytes(rerun.trace)
    kernel_code, kernel_report, kernel_ms = checker_file(instance_path, certificate_path)
    process_code, process_report, process_ms = checker_process(instance_path, certificate_path)
    p1_code, p1_report, p1_ms = checker_process(instance_path, certificate_path, require_p1=True)
    generated_polarity = claim_polarity(result.certificate["claim"])
    expected_polarity = "supportable" if ground["supportable"] else "unsupported"
    agreement = generated_polarity == expected_polarity
    p1_expected = result.certificate["trust_level"] == "P1_FULLY_CHECKABLE"
    p1_boundary_correct = (p1_expected and p1_code == 0) or ((not p1_expected) and p1_code != 0)
    try:
        jsonschema.Draft202012Validator(INSTANCE_SCHEMA).validate(instance)
        jsonschema.Draft202012Validator(CERTIFICATE_SCHEMA).validate(result.certificate)
        jsonschema.Draft202012Validator(TRACE_SCHEMA).validate(result.trace)
        schema_valid = True
    except Exception as exc:
        schema_valid = False
        failures.append({"severity": "critical", "component": "correctness", "case_id": case_id, "category": "schema_failure", "message": str(exc)})
    if not agreement:
        failures.append({"severity": "critical", "component": "correctness", "case_id": case_id, "category": "classification_disagreement", "message": f"ground={expected_polarity} generated={generated_polarity}"})
    if kernel_code not in ({0} if p1_expected else {2}):
        failures.append({"severity": "critical", "component": "correctness", "case_id": case_id, "category": "checker_kernel_failure", "message": json.dumps(kernel_report, sort_keys=True)})
    if process_code not in ({0} if p1_expected else {2}):
        failures.append({"severity": "critical", "component": "correctness", "case_id": case_id, "category": "checker_process_failure", "message": json.dumps(process_report, sort_keys=True)})
    if not p1_boundary_correct:
        failures.append({"severity": "critical", "component": "correctness", "case_id": case_id, "category": "p1_boundary_failure", "message": json.dumps(p1_report, sort_keys=True)})
    if not deterministic_certificate or not deterministic_trace:
        failures.append({"severity": "critical", "component": "correctness", "case_id": case_id, "category": "nondeterminism", "message": "certificate or trace changed on immediate regeneration"})
    metrics = certificate_metrics(result.certificate, result.trace)
    row = {
        "case_id": case_id,
        "family": family,
        "source": source,
        "p": len(candidate_outcome),
        "candidate_origin": candidate_origin,
        "feasible_decisions": len(evaluated),
        "distinct_outcomes": len(set(item.outcome for item in evaluated)),
        "frontier_outcomes": ground["frontier_outcomes"],
        "ground_supportable": ground["supportable"],
        "ground_positive_supportable": ground["positive_supportable"],
        "ground_pareto_efficient": ground["pareto_efficient"],
        "ground_class": ground["semantic_class"],
        "ground_truth_ms": ground["ground_truth_ms"],
        "generated_claim": result.certificate["claim"],
        "generated_polarity": generated_polarity,
        "trust_level": result.certificate["trust_level"],
        "agreement": agreement,
        "generation_ms": generation_ms,
        "checker_kernel_ms": kernel_ms,
        "checker_process_ms": process_ms,
        "checker_kernel_status": kernel_report.get("status", ""),
        "checker_process_status": process_report.get("status", ""),
        "p1_boundary_correct": p1_boundary_correct,
        "p1_process_ms": p1_ms,
        "deterministic_certificate": deterministic_certificate,
        "deterministic_trace": deterministic_trace,
        "schema_valid": schema_valid,
        "analytic_2d_supportable": interval is not None if len(candidate_outcome) == 2 else "",
        "analytic_2d_lower": rational_text(interval[0]) if interval else "",
        "analytic_2d_upper": rational_text(interval[1]) if interval else "",
        **metrics,
    }
    return row


def build_correctness_corpus() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for p in (2, 3, 4):
        for seed in range(1001, 1016):
            instance = make_random_explicit(p=p, alternatives=24, seed=seed + 10000 * p)
            evaluated = enumerate_evaluated(instance)
            for origin, item in select_candidates_independently(evaluated, seed=seed + 11 * p):
                case_id = f"explicit_p{p}_s{seed}_{origin}"
                rows.append(process_correctness_case(case_id=case_id, family="explicit_image", source="random", instance=instance, candidate=item.decision, evaluated=evaluated, candidate_origin=origin, failures=failures))
    for p in (2, 3, 4):
        for seed in range(2001, 2006):
            instance = make_random_assignment(n=5, p=p, seed=seed + 10000 * p)
            evaluated = enumerate_evaluated(instance)
            for origin, item in select_candidates_independently(evaluated, seed=seed + 13 * p):
                case_id = f"assignment_p{p}_s{seed}_{origin}"
                rows.append(process_correctness_case(case_id=case_id, family="assignment", source="random", instance=instance, candidate=item.decision, evaluated=evaluated, candidate_origin=origin, failures=failures))
    for p in (2, 3, 4):
        for seed in range(3001, 3006):
            instance = make_random_shortest_path(n=8, p=p, seed=seed + 10000 * p)
            evaluated = enumerate_evaluated(instance)
            for origin, item in select_candidates_independently(evaluated, seed=seed + 17 * p):
                case_id = f"shortest_path_p{p}_s{seed}_{origin}"
                rows.append(process_correctness_case(case_id=case_id, family="shortest_path", source="random", instance=instance, candidate=item.decision, evaluated=evaluated, candidate_origin=origin, failures=failures))
    for p in (2, 3, 4):
        for seed in range(4001, 4005):
            instance = make_random_knapsack(n=10, p=p, seed=seed + 10000 * p)
            evaluated = enumerate_evaluated(instance)
            for origin, item in select_candidates_independently(evaluated, seed=seed + 19 * p):
                case_id = f"knapsack_p{p}_s{seed}_{origin}"
                rows.append(process_correctness_case(case_id=case_id, family="binary_knapsack", source="random", instance=instance, candidate=item.decision, evaluated=evaluated, candidate_origin=origin, failures=failures))
    for p in (2, 3, 4, 5):
        instance, candidate = make_tight_explicit(p=p)
        evaluated = enumerate_evaluated(instance)
        rows.append(process_correctness_case(case_id=f"tight_explicit_p{p}", family="explicit_image", source="controlled_tight", instance=instance, candidate=candidate, evaluated=evaluated, candidate_origin="fixed_algebraically", failures=failures))
    for q in (100000, 1000000, 10000000):
        instance, candidate, _ = make_grid_interval_explicit(q=q)
        evaluated = enumerate_evaluated(instance)
        rows.append(process_correctness_case(case_id=f"narrow_interval_q{q}", family="explicit_image", source="controlled_grid", instance=instance, candidate=candidate, evaluated=evaluated, candidate_origin="fixed_algebraically", failures=failures))
    reference_manifest = json.loads((ROOT / "examples" / "reference_manifest.json").read_text(encoding="utf-8"))
    for entry in reference_manifest["cases"]:
        stem = entry["case"]
        instance = json.loads((ROOT / "examples" / "instances" / f"{stem}.json").read_text(encoding="utf-8"))
        candidate = json.loads((ROOT / "examples" / "candidates" / f"{stem}_candidate.json").read_text(encoding="utf-8"))
        evaluated = enumerate_evaluated(instance)
        rows.append(process_correctness_case(case_id=f"reference_{stem}", family=instance["problem"]["type"], source="reference_regression", instance=instance, candidate=candidate, evaluated=evaluated, candidate_origin="reference_fixed", failures=failures))
    rows.sort(key=lambda row: row["case_id"])
    return rows, failures


def factorial_log10(n: int) -> float:
    return math.lgamma(n + 1) / math.log(10)


def process_scaling_case(case_id: str, family: str, instance: dict[str, Any], candidate: Any, expected: str, catalogue_log10: float, failures: list[dict[str, Any]]) -> dict[str, Any]:
    instance_path, candidate_path, certificate_path, trace_path = case_paths(case_id)
    write_json(instance_path, instance)
    write_json(candidate_path, candidate)
    start = time.perf_counter_ns()
    result = generate_certificate(instance, candidate, context={"case_id": case_id, "protocol_sha256": PROTOCOL_DIGEST})
    generation_ms = (time.perf_counter_ns() - start) / 1_000_000
    write_json(certificate_path, result.certificate, canonical=True)
    write_json(trace_path, result.trace, canonical=True)
    kernel_code, kernel_report, kernel_ms = checker_file(instance_path, certificate_path)
    process_code, process_report, process_ms = checker_process(instance_path, certificate_path, require_p1=True)
    actual = claim_polarity(result.certificate["claim"])
    if actual != expected:
        failures.append({"severity": "critical", "component": "scaling", "case_id": case_id, "category": "construction_disagreement", "message": f"expected={expected} actual={actual}"})
    if kernel_code != 0 or process_code != 0:
        failures.append({"severity": "critical", "component": "scaling", "case_id": case_id, "category": "checker_failure", "message": json.dumps({"kernel": kernel_report, "process": process_report}, sort_keys=True)})
    metrics = certificate_metrics(result.certificate, result.trace)
    if actual == "unsupported" and metrics["atom_count"] > len(evaluate_decision(instance, candidate)):
        failures.append({"severity": "critical", "component": "scaling", "case_id": case_id, "category": "sparsity_failure", "message": str(metrics)})
    return {
        "case_id": case_id,
        "family": family,
        "p": len(evaluate_decision(instance, candidate)),
        "expected_polarity": expected,
        "generated_polarity": actual,
        "trust_level": result.certificate["trust_level"],
        "catalogue_log10": catalogue_log10,
        "generation_ms": generation_ms,
        "checker_kernel_ms": kernel_ms,
        "checker_process_ms": process_ms,
        "checker_kernel_faster": kernel_ms < generation_ms,
        **metrics,
    }


def build_scaling_corpus() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for n in (20, 40, 60):
        for p in (2, 3, 4):
            instance, candidate = make_large_assignment_positive(n=n, p=p, seed=5100 + n * 10 + p)
            rows.append(process_scaling_case(f"assignment_n{n}_p{p}_supportable", "assignment", instance, candidate, "supportable", factorial_log10(n), failures))
    for length in (20, 100, 400):
        for p in (2, 3, 4):
            for claim in ("supportable", "unsupported"):
                instance, candidate, log10_catalogue = make_large_shortest_path(p=p, path_length=length, claim=claim, seed=6200 + length * 10 + p)
                rows.append(process_scaling_case(f"shortest_path_L{length}_p{p}_{claim}", "shortest_path", instance, candidate, claim, log10_catalogue, failures))
    rows.sort(key=lambda row: row["case_id"])
    return rows, failures


def bootstrap_ci(values: Sequence[float], *, seed: int, resamples: int = 3000) -> tuple[float, float]:
    rng = random.Random(seed)
    medians = []
    n = len(values)
    for _ in range(resamples):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        medians.append(statistics.median(sample))
    medians.sort()
    return medians[int(0.025 * (resamples - 1))], medians[int(0.975 * (resamples - 1))]


def quartile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def timing_case_definitions() -> list[tuple[str, dict[str, Any], Any]]:
    cases: list[tuple[str, dict[str, Any], Any]] = []
    for n, p in ((40, 3), (60, 4)):
        instance, candidate = make_large_assignment_positive(n=n, p=p, seed=7300 + n + p)
        cases.append((f"timing_assignment_n{n}_p{p}_supportable", instance, candidate))
    for length, p, claim in ((400, 3, "supportable"), (400, 3, "unsupported"), (400, 4, "unsupported")):
        instance, candidate, _ = make_large_shortest_path(p=p, path_length=length, claim=claim, seed=7400 + length + p)
        cases.append((f"timing_shortest_L{length}_p{p}_{claim}", instance, candidate))
    instance, candidate = make_tight_explicit(p=4)
    cases.append(("timing_tight_explicit_p4", instance, candidate))
    instance, candidate, _ = make_grid_interval_explicit(q=1000000)
    cases.append(("timing_narrow_interval_q1000000", instance, candidate))
    instance = json.loads((ROOT / "examples" / "instances" / "binary_negative_p2.json").read_text(encoding="utf-8"))
    candidate = json.loads((ROOT / "examples" / "candidates" / "binary_negative_p2_candidate.json").read_text(encoding="utf-8"))
    cases.append(("timing_binary_negative_p2", instance, candidate))
    return cases


def build_timing_study() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    raw: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for case_id, instance, candidate in timing_case_definitions():
        instance_path, candidate_path, certificate_path, trace_path = case_paths(case_id)
        write_json(instance_path, instance)
        write_json(candidate_path, candidate)
        base = generate_certificate(instance, candidate, context={"case_id": case_id, "protocol_sha256": PROTOCOL_DIGEST})
        write_json(certificate_path, base.certificate, canonical=True)
        write_json(trace_path, base.trace, canonical=True)
        digest = sha256(canonical_json_bytes(base.certificate)).hexdigest()
        for _ in range(3):
            generate_certificate(instance, candidate, context={"case_id": case_id, "protocol_sha256": PROTOCOL_DIGEST})
            checker_file(instance_path, certificate_path)
        for repetition in range(1, 31):
            start = time.perf_counter_ns()
            generated = generate_certificate(instance, candidate, context={"case_id": case_id, "protocol_sha256": PROTOCOL_DIGEST})
            generation_ms = (time.perf_counter_ns() - start) / 1_000_000
            current_digest = sha256(canonical_json_bytes(generated.certificate)).hexdigest()
            code, report, checker_ms = checker_file(instance_path, certificate_path)
            if code not in (0, 2):
                failures.append({"severity": "critical", "component": "timing", "case_id": case_id, "category": "checker_failure", "message": json.dumps(report, sort_keys=True)})
            raw.append({
                "case_id": case_id,
                "repetition": repetition,
                "generation_ms": generation_ms,
                "checker_kernel_ms": checker_ms,
                "digest_match": current_digest == digest,
                "claim": base.certificate["claim"],
                "trust_level": base.certificate["trust_level"],
                **certificate_metrics(generated.certificate, generated.trace),
            })
        case_rows = [row for row in raw if row["case_id"] == case_id]
        generation = [float(row["generation_ms"]) for row in case_rows]
        checking = [float(row["checker_kernel_ms"]) for row in case_rows]
        gq1, gq3 = quartile(generation, 0.25), quartile(generation, 0.75)
        cq1, cq3 = quartile(checking, 0.25), quartile(checking, 0.75)
        gci = bootstrap_ci(generation, seed=8100 + len(summaries) * 2)
        cci = bootstrap_ci(checking, seed=8101 + len(summaries) * 2)
        gmed, cmed = statistics.median(generation), statistics.median(checking)
        summary = {
            "case_id": case_id,
            "claim": base.certificate["claim"],
            "trust_level": base.certificate["trust_level"],
            "repetitions": len(case_rows),
            "deterministic": all(bool(row["digest_match"]) for row in case_rows),
            "generation_ms_median": gmed,
            "generation_ms_q1": gq1,
            "generation_ms_q3": gq3,
            "generation_ms_iqr": gq3 - gq1,
            "generation_ms_ci95_low": gci[0],
            "generation_ms_ci95_high": gci[1],
            "checker_ms_median": cmed,
            "checker_ms_q1": cq1,
            "checker_ms_q3": cq3,
            "checker_ms_iqr": cq3 - cq1,
            "checker_ms_ci95_low": cci[0],
            "checker_ms_ci95_high": cci[1],
            "generation_to_checker_ratio": gmed / cmed if cmed > 0 else float("inf"),
            **certificate_metrics(base.certificate, base.trace),
        }
        summaries.append(summary)
    return raw, summaries, failures


def build_grid_audit() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for q in (100000, 1000000, 10000000):
        _, _, values = make_grid_interval_explicit(q=q)
        lower = Fraction(values[0], values[1])
        upper = Fraction(values[2], values[3])
        for denominator in (100, 1000, 10000):
            hit = any(lower <= Fraction(k, denominator) <= upper for k in range(denominator + 1))
            rows.append({
                "q": q,
                "grid_denominator": denominator,
                "lower": rational_text(lower),
                "upper": rational_text(upper),
                "width": rational_text(upper - lower),
                "grid_hit": hit,
                "false_negative": not hit,
            })
            if hit:
                failures.append({"severity": "critical", "component": "grid", "case_id": f"q{q}_d{denominator}", "category": "unexpected_grid_hit", "message": f"interval=[{lower},{upper}]"})
    return rows, failures


def direct_tightness_audit() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for p in range(2, 9):
        vectors = tight_rows(p)
        total = tuple(sum(row[i] for row in vectors) for i in range(p))
        all_strict = all(value < 0 for value in total)
        proper_subsets_blocked = True
        checked = 0
        for size in range(1, p):
            for subset in itertools.combinations(range(p), size):
                checked += 1
                missing = next((coordinate for coordinate in range(p) if coordinate not in subset), None)
                if missing is None or not all(vectors[row][missing] == 1 for row in subset):
                    proper_subsets_blocked = False
        passed = all_strict and proper_subsets_blocked
        rows.append({"p": p, "uniform_coordinate_sum": total[0], "proper_subsets_checked": checked, "requires_p_atoms": passed})
        if not passed:
            failures.append({"severity": "critical", "component": "tightness", "case_id": f"p{p}", "category": "tightness_failure", "message": str(rows[-1])})
    return rows, failures


def reseal(certificate: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(certificate)
    out.pop("integrity", None)
    out["integrity"] = {
        "algorithm": "sha256",
        "canonicalisation": "psp-json-c14n-1",
        "certificate_digest": CHECKER.certificate_digest(out),
    }
    return out


def mutate_certificate(certificate: dict[str, Any], mutation_index: int) -> tuple[str, dict[str, Any]]:
    out = deepcopy(certificate)
    negative = out.get("negative_payload") is not None
    if negative:
        mutations = [
            "atom_outcome", "coordinate_sum", "coefficient_sum", "decision_digest",
            "instance_digest", "strict_margin", "candidate_outcome", "problem_type",
        ]
        kind = mutations[mutation_index % len(mutations)]
        if kind == "atom_outcome":
            out["negative_payload"]["atoms"][0]["outcome"][0] = str(int(out["negative_payload"]["atoms"][0]["outcome"][0]) + 1)
        elif kind == "coordinate_sum":
            out["negative_payload"]["coordinate_sums"][0] = str(int(out["negative_payload"]["coordinate_sums"][0]) + 1)
        elif kind == "coefficient_sum":
            out["negative_payload"]["coefficient_sum"] = str(int(out["negative_payload"]["coefficient_sum"]) + 1)
        elif kind == "decision_digest":
            out["negative_payload"]["atoms"][0]["decision_digest"] = "sha256:" + "0" * 64
        elif kind == "instance_digest":
            out["instance_digest"] = "sha256:" + "1" * 64
        elif kind == "strict_margin":
            out["negative_payload"]["strict_margin"] = "999/1"
        elif kind == "candidate_outcome":
            out["candidate"]["outcome"][0] = str(int(out["candidate"]["outcome"][0]) + 1)
        elif kind == "problem_type":
            out["problem_type"] = "explicit_image" if out["problem_type"] != "explicit_image" else "assignment"
    else:
        mutations = [
            "weight_floor", "candidate_scalar", "scalar_minimum", "instance_digest",
            "candidate_digest", "candidate_outcome", "problem_type", "oracle_minimum",
        ]
        kind = mutations[mutation_index % len(mutations)]
        payload = out["positive_payload"]
        if kind == "weight_floor":
            payload["weight_floor"] = "999/1"
        elif kind == "candidate_scalar":
            payload["candidate_scalar_value"] = "999/1"
        elif kind == "scalar_minimum":
            payload["scalar_minimum"] = "998/1"
        elif kind == "instance_digest":
            out["instance_digest"] = "sha256:" + "2" * 64
        elif kind == "candidate_digest":
            out["candidate"]["decision_digest"] = "sha256:" + "3" * 64
        elif kind == "candidate_outcome":
            out["candidate"]["outcome"][0] = str(int(out["candidate"]["outcome"][0]) + 1)
        elif kind == "problem_type":
            out["problem_type"] = "assignment" if out["problem_type"] != "assignment" else "explicit_image"
        elif kind == "oracle_minimum":
            proof = payload["oracle"]["proof"]
            if "minimum_value" in proof:
                proof["minimum_value"] = "997/1"
            else:
                payload["scalar_minimum"] = "997/1"
    return kind, reseal(out)


def build_mutation_audit(correctness_rows: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    positive = [row for row in correctness_rows if row["generated_polarity"] == "supportable"]
    negative = [row for row in correctness_rows if row["generated_polarity"] == "unsupported"]
    selected = negative[:12] + positive[:12]
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, source in enumerate(selected):
        case_id = source["case_id"]
        instance_path, _, certificate_path, _ = case_paths(case_id)
        instance = json.loads(instance_path.read_text(encoding="utf-8"))
        certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
        kind, mutant = mutate_certificate(certificate, index)
        try:
            CHECKER.verify(instance, mutant)
            rejected = False
            error_code = "ACCEPTED"
        except CHECKER.Rejection as exc:
            rejected = True
            error_code = exc.code
        rows.append({"source_case": case_id, "mutation": kind, "resealed": True, "rejected": rejected, "error_code": error_code})
        if not rejected:
            failures.append({"severity": "critical", "component": "mutation", "case_id": case_id, "category": "false_acceptance", "message": kind})
    return rows, failures


def checker_import_audit() -> dict[str, Any]:
    tree = ast.parse(CHECKER_PATH.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    stdlib = set(sys.stdlib_module_names)
    nonstdlib = sorted(name for name in imports if name not in stdlib and name != "__future__")
    return {"imports": sorted(imports), "non_standard_library_imports": nonstdlib, "pass": not nonstdlib and "pareto_support_proofs" not in imports}


def run_unit_tests() -> dict[str, Any]:
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT, capture_output=True, text=True, check=False, timeout=180)
    ran = 0
    for line in (result.stdout + result.stderr).splitlines():
        if line.startswith("Ran ") and " tests" in line:
            try:
                ran = int(line.split()[1])
            except Exception:
                pass
    return {"exit_code": result.returncode, "tests_reported": ran, "pass": result.returncode == 0}


def environment_record() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for package in ("jsonschema", "matplotlib", "numpy", "Pillow", "PyYAML"):
        try:
            packages[package] = importlib_metadata.version(package)
        except importlib_metadata.PackageNotFoundError:
            packages[package] = "not-installed"
    return {
        "schema": "pareto-support-study-environment-1.0",
        "protocol_sha256": PROTOCOL_DIGEST,
        "software_version": __version__,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "operating_system": platform.system(),
        "architecture": platform.machine(),
        "packages": packages,
        "checker_sha256": sha256(CHECKER_PATH.read_bytes()).hexdigest(),
        "runner_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def make_figures(correctness: Sequence[dict[str, Any]], scaling: Sequence[dict[str, Any]], timing: Sequence[dict[str, Any]], grid: Sequence[dict[str, Any]]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image

    def save_png(fig, path: Path) -> None:
        fig.savefig(path, dpi=220, metadata={})
        with Image.open(path) as image:
            image.save(path, format="PNG", optimize=False)

    negative = [row for row in correctness if row["generated_polarity"] == "unsupported"]
    ps = sorted(set(int(row["p"]) for row in negative))
    maxima = [max(int(row["atom_count"]) for row in negative if int(row["p"]) == p) for p in ps]
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    ax.plot(ps, maxima, marker="o", label="Observed maximum")
    ax.plot(range(2, 9), range(2, 9), linestyle="--", label="p-atom ceiling")
    ax.set_xlabel("Objective dimension p")
    ax.set_ylabel("Negative-certificate atoms")
    ax.legend()
    fig.tight_layout()
    save_png(fig, FIGURES / "study_atom_count.png")
    plt.close(fig)

    neg_scaling = [row for row in scaling if row["generated_polarity"] == "unsupported"]
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    ax.scatter([float(row["catalogue_log10"]) for row in neg_scaling], [int(row["certificate_bytes"]) for row in neg_scaling])
    ax.set_xlabel("log10 catalogue-size proxy")
    ax.set_ylabel("Canonical certificate bytes")
    fig.tight_layout()
    save_png(fig, FIGURES / "study_scaling_size.png")
    plt.close(fig)

    labels = [row["case_id"].replace("timing_", "") for row in timing]
    x = list(range(len(labels)))
    width = 0.38
    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    ax.bar([v - width / 2 for v in x], [float(row["generation_ms_median"]) for row in timing], width=width, label="Generation")
    ax.bar([v + width / 2 for v in x], [float(row["checker_ms_median"]) for row in timing], width=width, label="Checking")
    ax.set_yscale("log")
    ax.set_ylabel("Median time (ms, log scale)")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=7)
    ax.legend()
    fig.tight_layout()
    save_png(fig, FIGURES / "study_timing.png")
    plt.close(fig)

    q_values = sorted(set(int(row["q"]) for row in grid))
    widths = [1 / q for q in q_values]
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    ax.loglog(q_values, widths, marker="o", label="Exact support-interval width")
    for denominator in (100, 1000, 10000):
        ax.axhline(1 / denominator, linestyle="--", label=f"Grid spacing 1/{denominator}")
    ax.set_xlabel("Construction parameter q")
    ax.set_ylabel("Width or grid spacing")
    ax.legend(fontsize=8)
    fig.tight_layout()
    save_png(fig, FIGURES / "study_grid_resolution.png")
    plt.close(fig)


def build_summary(correctness: Sequence[dict[str, Any]], scaling: Sequence[dict[str, Any]], timing: Sequence[dict[str, Any]], grid: Sequence[dict[str, Any]], tightness: Sequence[dict[str, Any]], mutations: Sequence[dict[str, Any]], failures: Sequence[dict[str, Any]], unit: dict[str, Any], imports: dict[str, Any]) -> dict[str, Any]:
    negative_correctness = [row for row in correctness if row["generated_polarity"] == "unsupported"]
    negative_scaling = [row for row in scaling if row["generated_polarity"] == "unsupported"]
    p2 = [row for row in correctness if row["trust_level"] == "P2_TRUSTED_ORACLE"]
    timed_large_negative = [row for row in timing if row["claim"] == "nonnegative_weight_unsupported" and ("shortest_L400" in row["case_id"])]
    critical = [item for item in failures if item.get("severity") == "critical"]
    checks = {
        "complete_image_agreement": all(bool(row["agreement"]) for row in correctness),
        "negative_certificates_sparse_and_verified": all(int(row["atom_count"]) <= int(row["p"]) and row["checker_kernel_status"] == "VERIFIED" for row in negative_correctness) and all(int(row["atom_count"]) <= int(row["p"]) for row in negative_scaling),
        "atom_bound_sharpness": all(bool(row["requires_p_atoms"]) for row in tightness) and all(int(row["atom_count"]) == int(row["p"]) for row in correctness if row["source"] == "controlled_tight"),
        "finite_grid_false_negatives": all(bool(row["false_negative"]) for row in grid),
        "large_negative_checking_cheaper": bool(timed_large_negative) and all(float(row["checker_ms_median"]) < float(row["generation_ms_median"]) for row in timed_large_negative),
        "trust_boundary_and_mutation_rejection": all(bool(row["p1_boundary_correct"]) for row in correctness) and all(bool(row["rejected"]) for row in mutations),
        "unit_tests": bool(unit["pass"]),
        "checker_import_boundary": bool(imports["pass"]),
        "no_critical_failures": not critical,
    }
    return {
        "protocol_sha256": PROTOCOL_DIGEST,
        "software_version": __version__,
        "correctness_cases": len(correctness),
        "correctness_agreements": sum(bool(row["agreement"]) for row in correctness),
        "correctness_rate": sum(bool(row["agreement"]) for row in correctness) / len(correctness),
        "family_counts": {family: sum(row["family"] == family for row in correctness) for family in sorted(set(row["family"] for row in correctness))},
        "class_counts": {cls: sum(row["ground_class"] == cls for row in correctness) for cls in ("S+", "S0", "UNS", "DOM")},
        "p1_correctness_cases": sum(row["trust_level"] == "P1_FULLY_CHECKABLE" for row in correctness),
        "p2_correctness_cases": len(p2),
        "negative_correctness_cases": len(negative_correctness),
        "negative_scaling_cases": len(negative_scaling),
        "maximum_negative_atoms": max([int(row["atom_count"]) for row in negative_correctness + negative_scaling] or [0]),
        "maximum_atoms_minus_p": max([int(row["atom_count"]) - int(row["p"]) for row in negative_correctness + negative_scaling] or [0]),
        "scaling_cases": len(scaling),
        "timing_cases": len(timing),
        "grid_tests": len(grid),
        "grid_false_negatives": sum(bool(row["false_negative"]) for row in grid),
        "tightness_dimensions": len(tightness),
        "mutations": len(mutations),
        "mutations_rejected": sum(bool(row["rejected"]) for row in mutations),
        "unit_tests": unit,
        "checker_import_audit": imports,
        "reported_failures": len(failures),
        "critical_failures": len(critical),
        "validation_checks": checks,
        "validation_status": "PASS_WITH_DECLARED_P2_BOUNDARY" if all(checks.values()) else "FAIL",
        "interpretive_limits": json.loads(PROTOCOL.read_text(encoding="utf-8"))["interpretive_limits"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true", help="remove previous study outputs before execution")
    args = parser.parse_args()
    if args.clean and RESULTS.exists():
        import shutil
        shutil.rmtree(RESULTS)
    if args.clean and FIGURES.exists():
        import shutil
        shutil.rmtree(FIGURES)
    ensure_dirs()
    failures: list[dict[str, Any]] = []
    print("[1/8] correctness corpus", flush=True)
    correctness, ff = build_correctness_corpus()
    failures.extend(ff)
    write_csv(RAW / "correctness_cases.csv", correctness)
    print("[2/8] scaling corpus", flush=True)
    scaling, ff = build_scaling_corpus()
    failures.extend(ff)
    write_csv(RAW / "scaling_cases.csv", scaling)
    print("[3/8] timing study", flush=True)
    timing_raw, timing_summary, ff = build_timing_study()
    failures.extend(ff)
    write_csv(RAW / "timing_repetitions.csv", timing_raw)
    write_csv(PROCESSED / "timing_summary.csv", timing_summary)
    print("[4/8] grid audit", flush=True)
    grid, ff = build_grid_audit()
    failures.extend(ff)
    write_csv(RAW / "grid_baseline.csv", grid)
    print("[5/8] tightness audit", flush=True)
    tightness, ff = direct_tightness_audit()
    failures.extend(ff)
    write_csv(RAW / "tightness.csv", tightness)
    print("[6/8] mutation audit", flush=True)
    mutations, ff = build_mutation_audit(correctness)
    failures.extend(ff)
    write_csv(RAW / "mutations.csv", mutations)
    print("[7/8] software audits", flush=True)
    unit = run_unit_tests()
    imports = checker_import_audit()
    if not unit["pass"]:
        failures.append({"severity": "critical", "component": "software", "case_id": "unit_tests", "category": "unit_test_failure", "message": str(unit)})
    if not imports["pass"]:
        failures.append({"severity": "critical", "component": "software", "case_id": "checker", "category": "import_boundary_failure", "message": str(imports)})
    write_csv(RAW / "failures.csv", failures, fieldnames=["severity", "component", "case_id", "category", "message"])
    summary = build_summary(correctness, scaling, timing_summary, grid, tightness, mutations, failures, unit, imports)
    write_json(PROCESSED / "study_summary.json", summary)
    write_json(VALIDATION / "study_summary.json", summary)
    write_json(VALIDATION / "study_environment.json", environment_record())
    write_json(VALIDATION / "checker_imports.json", imports)
    print("[8/8] figures", flush=True)
    make_figures(correctness, scaling, timing_summary, grid)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if summary["validation_status"] == "PASS_WITH_DECLARED_P2_BOUNDARY" else 3


if __name__ == "__main__":
    raise SystemExit(main())
