#!/usr/bin/env python3
"""Standalone exact checker for Pareto weighted-sum supportability proofs.

This file intentionally depends only on the Python standard library and does
not import the generator package, any optimisation solver or any schema
library. It is the executable trust boundary for the proof objects defined here.

Exit codes:
  0  fully verified P1 certificate
  1  rejected certificate or invalid input
  2  structurally validated P2 certificate whose global scalar optimum remains
     inside the declared trusted oracle boundary
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
import math
from math import gcd
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = "1.0.0"
CANONICALISATION = "psp-json-c14n-1"
MAX_JSON_BYTES = 10_000_000
INT_RE = re.compile(r"^(?:0|-?[1-9][0-9]*)$")
POS_INT_RE = re.compile(r"^[1-9][0-9]*$")
RAT_RE = re.compile(r"^(0|-?[1-9][0-9]*)/([1-9][0-9]*)$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class Rejection(ValueError):
    """A certificate, instance or proof field failed an exact check."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def reject(code: str, message: str) -> None:
    raise Rejection(code, message)


def _no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            reject("JSON_DUPLICATE_MEMBER", f"duplicate JSON member: {key}")
        out[key] = value
    return out


def _reject_constant(value: str) -> None:
    reject("JSON_NONFINITE_NUMBER", f"non-finite JSON number is forbidden: {value}")


def load_json_strict(path: str) -> Any:
    raw = Path(path).read_bytes()
    if len(raw) > MAX_JSON_BYTES:
        reject("JSON_SIZE_LIMIT", "JSON input exceeds the 10 MB safety limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        reject("JSON_UTF8", f"input is not valid UTF-8: {exc}")
    try:
        return json.loads(
            text,
            object_pairs_hook=_no_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except Rejection:
        raise
    except Exception as exc:
        reject("JSON_PARSE", f"invalid JSON: {exc}")


def _validate_restricted_json(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        reject("CANONICALISATION", f"binary floating-point value is forbidden at {path}")
    if isinstance(value, list):
        for idx, item in enumerate(value):
            _validate_restricted_json(item, f"{path}[{idx}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                reject("CANONICALISATION", f"object key must be a string at {path}")
            _validate_restricted_json(item, f"{path}.{key}")
        return
    reject("CANONICALISATION", f"unsupported JSON value at {path}: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    _validate_restricted_json(value)
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except Exception as exc:
        reject("CANONICALISATION", f"value cannot be canonicalised: {exc}")


def sha256_hex(value: Any) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def digest_label(value: Any) -> str:
    return f"sha256:{sha256_hex(value)}"


def exact_keys(obj: Any, required: set[str], optional: set[str] | None = None, *, where: str) -> None:
    if not isinstance(obj, dict):
        reject("TYPE_OBJECT", f"{where} must be an object")
    optional = optional or set()
    missing = required - set(obj)
    extra = set(obj) - required - optional
    if missing:
        reject("MISSING_FIELD", f"{where} is missing fields: {sorted(missing)}")
    if extra:
        reject("UNKNOWN_FIELD", f"{where} has unknown fields: {sorted(extra)}")


def parse_int_string(value: Any, *, positive: bool = False, where: str) -> int:
    if not isinstance(value, str):
        reject("INTEGER_ENCODING", f"{where} must be a decimal string")
    pattern = POS_INT_RE if positive else INT_RE
    if not pattern.fullmatch(value):
        reject("INTEGER_CANONICAL", f"{where} is not a canonical integer string")
    return int(value)


def parse_rational_string(value: Any, *, where: str) -> Fraction:
    if not isinstance(value, str):
        reject("RATIONAL_ENCODING", f"{where} must be a rational string")
    match = RAT_RE.fullmatch(value)
    if not match:
        reject("RATIONAL_CANONICAL", f"{where} is not a canonical rational string")
    numerator = int(match.group(1))
    denominator = int(match.group(2))
    if gcd(abs(numerator), denominator) != 1:
        reject("RATIONAL_REDUCED", f"{where} is not reduced")
    return Fraction(numerator, denominator)


def require_digest(value: Any, *, where: str) -> str:
    if not isinstance(value, str) or not DIGEST_RE.fullmatch(value):
        reject("DIGEST_FORMAT", f"{where} must be sha256:<64 lowercase hexadecimal digits>")
    return value


def semantic_instance_view(instance: dict[str, Any]) -> dict[str, Any]:
    view = deepcopy(instance)
    view.pop("metadata", None)
    problem = view.get("problem")
    if isinstance(problem, dict):
        ptype = problem.get("type")
        if ptype == "explicit_image" and isinstance(problem.get("alternatives"), list):
            problem["alternatives"] = sorted(problem["alternatives"], key=lambda item: item["id"])
        elif ptype == "shortest_path":
            if isinstance(problem.get("nodes"), list):
                problem["nodes"] = sorted(problem["nodes"])
            if isinstance(problem.get("edges"), list):
                problem["edges"] = sorted(problem["edges"], key=lambda item: item["id"])
        elif ptype == "binary_linear" and isinstance(problem.get("constraints"), list):
            problem["constraints"] = sorted(problem["constraints"], key=canonical_json_bytes)
    return view


def instance_digest(instance: dict[str, Any]) -> str:
    return digest_label(semantic_instance_view(instance))


def certificate_digest(certificate: dict[str, Any]) -> str:
    unsigned = deepcopy(certificate)
    unsigned.pop("integrity", None)
    return digest_label(unsigned)


class Transform:
    def __init__(self, sense: str, multiplier: int, offset: int):
        self.sense = sense
        self.multiplier = multiplier
        self.offset = offset
        self.sign = 1 if sense == "min" else -1

    def apply(self, raw: int) -> int:
        return self.sign * self.multiplier * raw + self.offset

    def coefficient(self, raw: int) -> int:
        return self.sign * self.multiplier * raw

    def constant(self, raw: int) -> int:
        return self.sign * self.multiplier * raw + self.offset


def parse_transforms(instance: dict[str, Any]) -> tuple[Transform, ...]:
    raw = instance.get("objective_transform")
    if not isinstance(raw, list) or not raw:
        reject("INSTANCE_TRANSFORM", "objective_transform must be a non-empty array")
    out: list[Transform] = []
    for idx, item in enumerate(raw):
        exact_keys(item, {"sense", "multiplier", "offset"}, where=f"objective_transform[{idx}]")
        sense = item["sense"]
        if sense not in {"min", "max"}:
            reject("INSTANCE_SENSE", f"objective_transform[{idx}].sense must be min or max")
        multiplier = parse_int_string(item["multiplier"], positive=True, where=f"objective_transform[{idx}].multiplier")
        offset = parse_int_string(item["offset"], where=f"objective_transform[{idx}].offset")
        out.append(Transform(sense, multiplier, offset))
    return tuple(out)


def validate_instance(instance: Any) -> tuple[Transform, ...]:
    exact_keys(
        instance,
        {"format", "schema_version", "objective_transform", "problem"},
        {"metadata"},
        where="instance",
    )
    if instance["format"] != "pareto-support-instance":
        reject("INSTANCE_FORMAT", "unexpected instance format")
    if instance["schema_version"] != SCHEMA_VERSION:
        reject("INSTANCE_VERSION", "unsupported instance schema version")
    if "metadata" in instance and not isinstance(instance["metadata"], dict):
        reject("INSTANCE_METADATA", "metadata must be an object")
    transforms = parse_transforms(instance)
    problem = instance["problem"]
    if not isinstance(problem, dict) or "type" not in problem:
        reject("INSTANCE_PROBLEM", "problem object with a type is required")
    ptype = problem["type"]
    if ptype == "explicit_image":
        validate_explicit(problem, len(transforms))
    elif ptype == "binary_linear":
        validate_binary(problem, len(transforms))
    elif ptype == "assignment":
        validate_assignment(problem, len(transforms))
    elif ptype == "shortest_path":
        validate_shortest(problem, transforms)
    else:
        reject("INSTANCE_PROBLEM_TYPE", f"unsupported problem type: {ptype}")
    return transforms


def validate_explicit(problem: dict[str, Any], p: int) -> None:
    exact_keys(problem, {"type", "alternatives"}, where="problem")
    alternatives = problem["alternatives"]
    if not isinstance(alternatives, list) or not alternatives:
        reject("EXPLICIT_ALTERNATIVES", "explicit image must contain alternatives")
    ids: set[str] = set()
    for idx, item in enumerate(alternatives):
        exact_keys(item, {"id", "raw_objectives"}, where=f"alternative[{idx}]")
        if not isinstance(item["id"], str) or not item["id"]:
            reject("EXPLICIT_ID", f"alternative[{idx}].id must be a non-empty string")
        if item["id"] in ids:
            reject("EXPLICIT_DUPLICATE_ID", "alternative ids must be unique")
        ids.add(item["id"])
        values = item["raw_objectives"]
        if not isinstance(values, list) or len(values) != p:
            reject("OBJECTIVE_DIMENSION", f"alternative[{idx}] has the wrong objective dimension")
        for j, value in enumerate(values):
            parse_int_string(value, where=f"alternative[{idx}].raw_objectives[{j}]")


def validate_binary(problem: dict[str, Any], p: int) -> None:
    exact_keys(problem, {"type", "n", "constraints", "objectives"}, where="problem")
    n = problem["n"]
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 256:
        reject("BINARY_N", "binary n must be an integer between 1 and 256")
    constraints = problem["constraints"]
    if not isinstance(constraints, list):
        reject("BINARY_CONSTRAINTS", "constraints must be an array")
    for idx, constraint in enumerate(constraints):
        exact_keys(constraint, {"coefficients", "sense", "rhs"}, where=f"constraint[{idx}]")
        coefficients = constraint["coefficients"]
        if not isinstance(coefficients, list) or len(coefficients) != n:
            reject("BINARY_CONSTRAINT_DIMENSION", f"constraint[{idx}] has the wrong length")
        for j, value in enumerate(coefficients):
            parse_int_string(value, where=f"constraint[{idx}].coefficients[{j}]")
        if constraint["sense"] not in {"<=", "=", ">="}:
            reject("BINARY_CONSTRAINT_SENSE", f"constraint[{idx}] has an unsupported sense")
        parse_int_string(constraint["rhs"], where=f"constraint[{idx}].rhs")
    objectives = problem["objectives"]
    if not isinstance(objectives, list) or len(objectives) != p:
        reject("OBJECTIVE_DIMENSION", "binary objective count does not match objective_transform")
    for idx, objective in enumerate(objectives):
        exact_keys(objective, {"coefficients", "constant"}, where=f"objective[{idx}]")
        coefficients = objective["coefficients"]
        if not isinstance(coefficients, list) or len(coefficients) != n:
            reject("BINARY_OBJECTIVE_DIMENSION", f"objective[{idx}] has the wrong length")
        for j, value in enumerate(coefficients):
            parse_int_string(value, where=f"objective[{idx}].coefficients[{j}]")
        parse_int_string(objective["constant"], where=f"objective[{idx}].constant")


def validate_assignment(problem: dict[str, Any], p: int) -> None:
    exact_keys(problem, {"type", "n", "objectives"}, where="problem")
    n = problem["n"]
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 512:
        reject("ASSIGNMENT_N", "assignment n must be an integer between 1 and 512")
    objectives = problem["objectives"]
    if not isinstance(objectives, list) or len(objectives) != p:
        reject("OBJECTIVE_DIMENSION", "assignment objective count does not match objective_transform")
    for idx, objective in enumerate(objectives):
        exact_keys(objective, {"costs", "constant"}, where=f"objective[{idx}]")
        matrix = objective["costs"]
        if not isinstance(matrix, list) or len(matrix) != n:
            reject("ASSIGNMENT_MATRIX", f"objective[{idx}] has the wrong number of rows")
        for row_idx, row in enumerate(matrix):
            if not isinstance(row, list) or len(row) != n:
                reject("ASSIGNMENT_MATRIX", f"objective[{idx}] row {row_idx} is not length n")
            for col_idx, value in enumerate(row):
                parse_int_string(value, where=f"objective[{idx}].costs[{row_idx}][{col_idx}]")
        parse_int_string(objective["constant"], where=f"objective[{idx}].constant")


def validate_shortest(problem: dict[str, Any], transforms: tuple[Transform, ...]) -> None:
    exact_keys(
        problem,
        {"type", "nodes", "source", "target", "edges", "objective_constants"},
        where="problem",
    )
    nodes = problem["nodes"]
    if not isinstance(nodes, list) or len(nodes) < 2 or any(not isinstance(node, str) or not node for node in nodes):
        reject("SHORTEST_NODES", "nodes must be an array of at least two non-empty strings")
    if len(nodes) != len(set(nodes)):
        reject("SHORTEST_DUPLICATE_NODE", "node ids must be unique")
    if problem["source"] not in nodes or problem["target"] not in nodes or problem["source"] == problem["target"]:
        reject("SHORTEST_TERMINALS", "source and target must be distinct listed nodes")
    constants = problem["objective_constants"]
    if not isinstance(constants, list) or len(constants) != len(transforms):
        reject("OBJECTIVE_DIMENSION", "shortest-path constants have the wrong dimension")
    for idx, value in enumerate(constants):
        parse_int_string(value, where=f"objective_constants[{idx}]")
    edges = problem["edges"]
    if not isinstance(edges, list) or not edges:
        reject("SHORTEST_EDGES", "shortest-path instance requires edges")
    edge_ids: set[str] = set()
    for idx, edge in enumerate(edges):
        exact_keys(edge, {"id", "tail", "head", "costs"}, where=f"edge[{idx}]")
        if not isinstance(edge["id"], str) or not edge["id"] or edge["id"] in edge_ids:
            reject("SHORTEST_EDGE_ID", "edge ids must be unique non-empty strings")
        edge_ids.add(edge["id"])
        if edge["tail"] not in nodes or edge["head"] not in nodes:
            reject("SHORTEST_ENDPOINT", f"edge[{idx}] endpoint is not listed")
        costs = edge["costs"]
        if not isinstance(costs, list) or len(costs) != len(transforms):
            reject("OBJECTIVE_DIMENSION", f"edge[{idx}] has the wrong cost dimension")
        for j, (value, transform) in enumerate(zip(costs, transforms)):
            raw = parse_int_string(value, where=f"edge[{idx}].costs[{j}]")
            if transform.coefficient(raw) < 0:
                reject("SHORTEST_NEGATIVE_CANONICAL_EDGE", "every canonical objective edge coefficient must be non-negative")


def parse_bits(problem: dict[str, Any], decision: Any) -> tuple[int, ...]:
    if not isinstance(decision, dict) or set(decision) != {"bits"} or not isinstance(decision["bits"], str):
        reject("BINARY_DECISION", "binary decision must contain exactly one bit string")
    bits = decision["bits"]
    if len(bits) != problem["n"] or any(char not in "01" for char in bits):
        reject("BINARY_DECISION", "binary decision has the wrong form")
    return tuple(int(char) for char in bits)


def binary_feasible(problem: dict[str, Any], bits: tuple[int, ...]) -> bool:
    for constraint in problem["constraints"]:
        lhs = sum(int(value) * bit for value, bit in zip(constraint["coefficients"], bits))
        rhs = int(constraint["rhs"])
        sense = constraint["sense"]
        if sense == "<=" and lhs > rhs:
            return False
        if sense == "=" and lhs != rhs:
            return False
        if sense == ">=" and lhs < rhs:
            return False
    return True


def evaluate_decision(instance: dict[str, Any], decision: Any, transforms: tuple[Transform, ...]) -> tuple[int, ...]:
    problem = instance["problem"]
    ptype = problem["type"]
    if ptype == "explicit_image":
        if not isinstance(decision, dict) or set(decision) != {"id"} or not isinstance(decision["id"], str):
            reject("EXPLICIT_DECISION", "explicit-image decision must contain exactly id")
        raw = None
        for alternative in problem["alternatives"]:
            if alternative["id"] == decision["id"]:
                raw = tuple(int(value) for value in alternative["raw_objectives"])
                break
        if raw is None:
            reject("DECISION_INFEASIBLE", "explicit-image decision is not listed")
    elif ptype == "binary_linear":
        bits = parse_bits(problem, decision)
        if not binary_feasible(problem, bits):
            reject("DECISION_INFEASIBLE", "binary decision is infeasible")
        raw_values = []
        for objective in problem["objectives"]:
            value = int(objective["constant"])
            value += sum(int(coef) * bit for coef, bit in zip(objective["coefficients"], bits))
            raw_values.append(value)
        raw = tuple(raw_values)
    elif ptype == "assignment":
        if not isinstance(decision, dict) or set(decision) != {"permutation"}:
            reject("ASSIGNMENT_DECISION", "assignment decision must contain exactly permutation")
        permutation = decision["permutation"]
        n = problem["n"]
        if (
            not isinstance(permutation, list)
            or len(permutation) != n
            or any(not isinstance(value, int) or isinstance(value, bool) for value in permutation)
            or sorted(permutation) != list(range(n))
        ):
            reject("DECISION_INFEASIBLE", "assignment decision is not a permutation")
        raw_values = []
        for objective in problem["objectives"]:
            value = int(objective["constant"])
            value += sum(int(objective["costs"][row][column]) for row, column in enumerate(permutation))
            raw_values.append(value)
        raw = tuple(raw_values)
    elif ptype == "shortest_path":
        if not isinstance(decision, dict) or set(decision) != {"edge_ids"}:
            reject("SHORTEST_DECISION", "shortest-path decision must contain exactly edge_ids")
        edge_ids = decision["edge_ids"]
        if not isinstance(edge_ids, list) or not edge_ids or any(not isinstance(item, str) for item in edge_ids):
            reject("SHORTEST_DECISION", "edge_ids must be a non-empty string array")
        edges = {edge["id"]: edge for edge in problem["edges"]}
        node = problem["source"]
        seen = {node}
        raw_values = [int(value) for value in problem["objective_constants"]]
        for edge_id in edge_ids:
            edge = edges.get(edge_id)
            if edge is None or edge["tail"] != node:
                reject("DECISION_INFEASIBLE", "edge sequence is not a source-to-target path")
            node = edge["head"]
            if node in seen:
                reject("DECISION_INFEASIBLE", "shortest-path decision is not simple")
            seen.add(node)
            for idx, value in enumerate(edge["costs"]):
                raw_values[idx] += int(value)
        if node != problem["target"]:
            reject("DECISION_INFEASIBLE", "path does not end at the target")
        raw = tuple(raw_values)
    else:
        reject("INSTANCE_PROBLEM_TYPE", "unsupported problem type")
    return tuple(transform.apply(value) for transform, value in zip(transforms, raw))


def scalar_value(outcome: Iterable[int], weights: Iterable[Fraction]) -> Fraction:
    return sum((Fraction(value) * weight for value, weight in zip(outcome, weights)), Fraction(0))


def parse_outcome(value: Any, p: int, *, where: str) -> tuple[int, ...]:
    if not isinstance(value, list) or len(value) != p:
        reject("OBJECTIVE_DIMENSION", f"{where} must contain exactly {p} components")
    return tuple(parse_int_string(item, where=f"{where}[{idx}]") for idx, item in enumerate(value))


def validate_candidate(candidate: Any, instance: dict[str, Any], transforms: tuple[Transform, ...]) -> tuple[Any, tuple[int, ...]]:
    exact_keys(candidate, {"decision", "decision_digest", "outcome"}, where="candidate")
    decision = candidate["decision"]
    require_digest(candidate["decision_digest"], where="candidate.decision_digest")
    if candidate["decision_digest"] != digest_label(decision):
        reject("DECISION_DIGEST_MISMATCH", "candidate decision digest does not match its decision")
    p = len(transforms)
    recorded = parse_outcome(candidate["outcome"], p, where="candidate.outcome")
    evaluated = evaluate_decision(instance, decision, transforms)
    if recorded != evaluated:
        reject("OUTCOME_MISMATCH", "candidate outcome does not match exact reevaluation")
    return decision, evaluated


def validate_provenance(provenance: Any, expected_adapter: str | None = None) -> None:
    exact_keys(
        provenance,
        {"generator", "algorithm", "oracle_adapter", "trace_digest", "exact_arithmetic", "deterministic"},
        {"context"},
        where="provenance",
    )
    exact_keys(provenance["generator"], {"name", "version"}, where="provenance.generator")
    if not isinstance(provenance["generator"]["name"], str) or not provenance["generator"]["name"]:
        reject("PROVENANCE", "generator name must be non-empty")
    if not isinstance(provenance["generator"]["version"], str) or not provenance["generator"]["version"]:
        reject("PROVENANCE", "generator version must be non-empty")
    if provenance["algorithm"] != "exact-exchange-v1":
        reject("PROVENANCE", "unsupported generation algorithm")
    if not isinstance(provenance["oracle_adapter"], str) or not provenance["oracle_adapter"]:
        reject("PROVENANCE", "oracle_adapter must be non-empty")
    if expected_adapter is not None and provenance["oracle_adapter"] != expected_adapter:
        reject("PROVENANCE", "provenance oracle adapter differs from the proof adapter")
    require_digest(provenance["trace_digest"], where="provenance.trace_digest")
    if provenance["exact_arithmetic"] != "fractions.Fraction":
        reject("PROVENANCE", "exact_arithmetic must declare fractions.Fraction")
    if provenance["deterministic"] is not True:
        reject("PROVENANCE", "deterministic must be true")
    if "context" in provenance and not isinstance(provenance["context"], dict):
        reject("PROVENANCE", "provenance.context must be an object")


def verify_integrity(certificate: dict[str, Any]) -> None:
    integrity = certificate.get("integrity")
    exact_keys(integrity, {"algorithm", "canonicalisation", "certificate_digest"}, where="integrity")
    if integrity["algorithm"] != "sha256":
        reject("INTEGRITY_ALGORITHM", "unsupported integrity algorithm")
    if integrity["canonicalisation"] != CANONICALISATION:
        reject("INTEGRITY_CANONICALISATION", "integrity canonicalisation does not match the schema")
    require_digest(integrity["certificate_digest"], where="integrity.certificate_digest")
    expected = certificate_digest(certificate)
    if integrity["certificate_digest"] != expected:
        reject("CERTIFICATE_DIGEST_MISMATCH", "certificate digest does not match the unsigned proof object")


def verify_negative(
    certificate: dict[str, Any],
    instance: dict[str, Any],
    transforms: tuple[Transform, ...],
    candidate_outcome: tuple[int, ...],
) -> dict[str, Any]:
    if certificate["trust_level"] != "P1_FULLY_CHECKABLE":
        reject("TRUST_LEVEL", "negative certificates must be P1 fully checkable")
    payload = certificate["negative_payload"]
    exact_keys(
        payload,
        {"atoms", "coefficient_sum", "coordinate_sums", "strict_margin", "normalisation"},
        where="negative_payload",
    )
    if payload["normalisation"] != "primitive-positive-integers-gcd-1":
        reject("NEGATIVE_NORMALISATION", "unsupported negative-certificate normalisation")
    atoms = payload["atoms"]
    p = len(transforms)
    if not isinstance(atoms, list) or not 1 <= len(atoms) <= p:
        reject("NEGATIVE_SUPPORT_SIZE", f"negative certificate must have between 1 and p={p} atoms")

    previous_key: bytes | None = None
    seen_outcomes: set[tuple[int, ...]] = set()
    coefficients: list[int] = []
    differences: list[tuple[int, ...]] = []
    for idx, atom in enumerate(atoms):
        exact_keys(atom, {"decision", "decision_digest", "outcome", "coefficient"}, where=f"atom[{idx}]")
        key = canonical_json_bytes(atom["decision"])
        if previous_key is not None and key <= previous_key:
            reject("NEGATIVE_ATOM_ORDER", "atoms must be strictly ordered by canonical decision encoding")
        previous_key = key
        require_digest(atom["decision_digest"], where=f"atom[{idx}].decision_digest")
        if atom["decision_digest"] != digest_label(atom["decision"]):
            reject("DECISION_DIGEST_MISMATCH", f"atom[{idx}] decision digest does not match")
        recorded = parse_outcome(atom["outcome"], p, where=f"atom[{idx}].outcome")
        evaluated = evaluate_decision(instance, atom["decision"], transforms)
        if recorded != evaluated:
            reject("OUTCOME_MISMATCH", f"atom[{idx}] outcome does not match exact reevaluation")
        if recorded == candidate_outcome:
            reject("NEGATIVE_ZERO_DIFFERENCE", f"atom[{idx}] duplicates the candidate outcome")
        if recorded in seen_outcomes:
            reject("NEGATIVE_DUPLICATE_OUTCOME", "negative atoms must have distinct outcomes")
        seen_outcomes.add(recorded)
        coefficient = parse_int_string(atom["coefficient"], positive=True, where=f"atom[{idx}].coefficient")
        coefficients.append(coefficient)
        differences.append(tuple(value - base for value, base in zip(recorded, candidate_outcome)))

    coefficient_sum = parse_int_string(payload["coefficient_sum"], positive=True, where="negative_payload.coefficient_sum")
    if coefficient_sum != sum(coefficients):
        reject("NEGATIVE_COEFFICIENT_SUM", "coefficient_sum is inconsistent with the atoms")
    divisor = 0
    for coefficient in coefficients:
        divisor = gcd(divisor, coefficient)
    if divisor != 1:
        reject("NEGATIVE_NOT_PRIMITIVE", "negative coefficients are not primitive")

    computed_sums = tuple(
        sum(coefficients[h] * differences[h][coordinate] for h in range(len(atoms)))
        for coordinate in range(p)
    )
    recorded_sums = parse_outcome(payload["coordinate_sums"], p, where="negative_payload.coordinate_sums")
    if recorded_sums != computed_sums:
        reject("NEGATIVE_COORDINATE_SUM", "coordinate_sums do not match exact recomputation")
    if any(value >= 0 for value in computed_sums):
        reject("NEGATIVE_NOT_STRICT", "the weighted challenger mixture is not strictly negative in every coordinate")

    strict_margin = parse_rational_string(payload["strict_margin"], where="negative_payload.strict_margin")
    expected_margin = Fraction(min(-value for value in computed_sums), coefficient_sum)
    if strict_margin != expected_margin or strict_margin <= 0:
        reject("NEGATIVE_MARGIN", "strict_margin does not match the exact uniform margin")

    bit_payload = sum(value.bit_length() for value in coefficients) + coefficient_sum.bit_length()
    return {
        "status": "VERIFIED",
        "verification_level": "P1_FULLY_CHECKABLE",
        "claim": certificate["claim"],
        "support_size": len(atoms),
        "objective_dimension": p,
        "strict_margin": f"{strict_margin.numerator}/{strict_margin.denominator}",
        "coefficient_bit_payload": bit_payload,
        "trusted_global_optimisation_calls": 0,
    }


def parse_weights(payload: dict[str, Any], p: int, claim: str) -> tuple[Fraction, ...]:
    raw = payload["weights"]
    if not isinstance(raw, list) or len(raw) != p:
        reject("POSITIVE_WEIGHT_DIMENSION", f"positive weights must contain exactly p={p} entries")
    weights = tuple(parse_rational_string(value, where=f"positive_payload.weights[{idx}]") for idx, value in enumerate(raw))
    if any(value < 0 for value in weights) or sum(weights, Fraction(0)) != 1:
        reject("POSITIVE_WEIGHT_SIMPLEX", "positive weights must form a non-negative simplex vector")
    if claim == "positive_weight_supportable" and not all(value > 0 for value in weights):
        reject("POSITIVE_WEIGHT_CLAIM", "positive_weight_supportable requires every weight to be strictly positive")
    floor = parse_rational_string(payload["weight_floor"], where="positive_payload.weight_floor")
    if floor != min(weights):
        reject("POSITIVE_WEIGHT_FLOOR", "weight_floor does not equal the smallest weight")
    return weights


def weighted_assignment_data(instance: dict[str, Any], transforms: tuple[Transform, ...], weights: tuple[Fraction, ...]) -> tuple[list[list[Fraction]], Fraction]:
    problem = instance["problem"]
    n = problem["n"]
    matrix: list[list[Fraction]] = []
    for row in range(n):
        matrix_row: list[Fraction] = []
        for column in range(n):
            value = Fraction(0)
            for objective, transform, weight in zip(problem["objectives"], transforms, weights):
                value += weight * transform.coefficient(int(objective["costs"][row][column]))
            matrix_row.append(value)
        matrix.append(matrix_row)
    constant = sum(
        (weight * transform.constant(int(objective["constant"])) for objective, transform, weight in zip(problem["objectives"], transforms, weights)),
        Fraction(0),
    )
    return matrix, constant


def weighted_shortest_data(instance: dict[str, Any], transforms: tuple[Transform, ...], weights: tuple[Fraction, ...]) -> tuple[dict[str, Fraction], Fraction]:
    problem = instance["problem"]
    edge_costs: dict[str, Fraction] = {}
    for edge in problem["edges"]:
        value = sum(
            (weight * transform.coefficient(int(raw)) for raw, transform, weight in zip(edge["costs"], transforms, weights)),
            Fraction(0),
        )
        if value < 0:
            reject("SHORTEST_NEGATIVE_WEIGHTED_EDGE", "weighted shortest-path proof contains a negative edge cost")
        edge_costs[edge["id"]] = value
    constant = sum(
        (weight * transform.constant(int(raw)) for raw, transform, weight in zip(problem["objective_constants"], transforms, weights)),
        Fraction(0),
    )
    return edge_costs, constant


def verify_explicit_proof(instance: dict[str, Any], transforms: tuple[Transform, ...], weights: tuple[Fraction, ...], proof: Any) -> Fraction:
    exact_keys(
        proof,
        {"minimiser_decision", "minimiser_outcome", "minimum_value", "tie_break"},
        where="positive_payload.oracle.proof",
    )
    if proof["tie_break"] != "canonical-decision-order":
        reject("EXPLICIT_TIE_BREAK", "unsupported explicit enumeration tie-break")
    best: tuple[Fraction, bytes, dict[str, Any], tuple[int, ...]] | None = None
    for alternative in instance["problem"]["alternatives"]:
        decision = {"id": alternative["id"]}
        outcome = evaluate_decision(instance, decision, transforms)
        item = (scalar_value(outcome, weights), canonical_json_bytes(decision), decision, outcome)
        if best is None or (item[0], item[1]) < (best[0], best[1]):
            best = item
    assert best is not None
    value, _, decision, outcome = best
    if proof["minimiser_decision"] != decision:
        reject("EXPLICIT_MINIMISER", "proof minimiser is not the canonical exact minimiser")
    recorded_outcome = parse_outcome(proof["minimiser_outcome"], len(transforms), where="proof.minimiser_outcome")
    if recorded_outcome != outcome:
        reject("OUTCOME_MISMATCH", "proof minimiser outcome is incorrect")
    reported = parse_rational_string(proof["minimum_value"], where="proof.minimum_value")
    if reported != value:
        reject("EXPLICIT_MINIMUM", "reported explicit minimum is incorrect")
    return value


def verify_assignment_proof(instance: dict[str, Any], transforms: tuple[Transform, ...], weights: tuple[Fraction, ...], proof: Any) -> Fraction:
    exact_keys(
        proof,
        {"minimiser_decision", "minimiser_outcome", "minimum_value", "matrix_value", "constant_value", "row_potentials", "column_potentials"},
        where="positive_payload.oracle.proof",
    )
    problem = instance["problem"]
    n = problem["n"]
    outcome = evaluate_decision(instance, proof["minimiser_decision"], transforms)
    recorded_outcome = parse_outcome(proof["minimiser_outcome"], len(transforms), where="proof.minimiser_outcome")
    if recorded_outcome != outcome:
        reject("OUTCOME_MISMATCH", "assignment proof minimiser outcome is incorrect")
    permutation = proof["minimiser_decision"]["permutation"]
    matrix, constant = weighted_assignment_data(instance, transforms, weights)
    primal = sum(matrix[row][permutation[row]] for row in range(n))
    total = primal + constant
    row_raw = proof["row_potentials"]
    col_raw = proof["column_potentials"]
    if not isinstance(row_raw, list) or len(row_raw) != n or not isinstance(col_raw, list) or len(col_raw) != n:
        reject("ASSIGNMENT_POTENTIAL_DIMENSION", "assignment potentials must each have length n")
    row_potentials = tuple(parse_rational_string(value, where=f"proof.row_potentials[{idx}]") for idx, value in enumerate(row_raw))
    col_potentials = tuple(parse_rational_string(value, where=f"proof.column_potentials[{idx}]") for idx, value in enumerate(col_raw))
    for row in range(n):
        for column in range(n):
            if row_potentials[row] + col_potentials[column] > matrix[row][column]:
                reject("ASSIGNMENT_DUAL_INFEASIBLE", f"assignment dual inequality fails at ({row},{column})")
        if row_potentials[row] + col_potentials[permutation[row]] != matrix[row][permutation[row]]:
            reject("ASSIGNMENT_COMPLEMENTARY_SLACKNESS", f"matched edge {row} is not tight")
    dual = sum(row_potentials, Fraction(0)) + sum(col_potentials, Fraction(0))
    if dual != primal:
        reject("ASSIGNMENT_PRIMAL_DUAL_GAP", "assignment primal and dual values differ")
    if parse_rational_string(proof["matrix_value"], where="proof.matrix_value") != primal:
        reject("ASSIGNMENT_MATRIX_VALUE", "reported assignment matrix value is incorrect")
    if parse_rational_string(proof["constant_value"], where="proof.constant_value") != constant:
        reject("ASSIGNMENT_CONSTANT_VALUE", "reported assignment constant is incorrect")
    if parse_rational_string(proof["minimum_value"], where="proof.minimum_value") != total:
        reject("ASSIGNMENT_MINIMUM", "reported assignment minimum is incorrect")
    if scalar_value(outcome, weights) != total:
        reject("ASSIGNMENT_RECONSTRUCTION", "assignment outcome does not reconstruct the scalar minimum")
    return total


def reachable_nodes(problem: dict[str, Any]) -> set[str]:
    outgoing: dict[str, list[str]] = {node: [] for node in problem["nodes"]}
    for edge in problem["edges"]:
        outgoing[edge["tail"]].append(edge["head"])
    seen = {problem["source"]}
    stack = [problem["source"]]
    while stack:
        node = stack.pop()
        for head in outgoing[node]:
            if head not in seen:
                seen.add(head)
                stack.append(head)
    return seen


def verify_shortest_proof(instance: dict[str, Any], transforms: tuple[Transform, ...], weights: tuple[Fraction, ...], proof: Any) -> Fraction:
    exact_keys(
        proof,
        {"minimiser_decision", "minimiser_outcome", "minimum_value", "path_value", "constant_value", "node_potentials"},
        where="positive_payload.oracle.proof",
    )
    problem = instance["problem"]
    outcome = evaluate_decision(instance, proof["minimiser_decision"], transforms)
    recorded_outcome = parse_outcome(proof["minimiser_outcome"], len(transforms), where="proof.minimiser_outcome")
    if recorded_outcome != outcome:
        reject("OUTCOME_MISMATCH", "shortest-path proof minimiser outcome is incorrect")
    edge_costs, constant = weighted_shortest_data(instance, transforms, weights)
    potentials_raw = proof["node_potentials"]
    if not isinstance(potentials_raw, dict):
        reject("SHORTEST_POTENTIALS", "node_potentials must be an object")
    reachable = reachable_nodes(problem)
    if set(potentials_raw) != reachable:
        reject("SHORTEST_POTENTIAL_DOMAIN", "node_potentials must contain exactly the structurally reachable nodes")
    potentials = {
        node: parse_rational_string(value, where=f"proof.node_potentials[{node!r}]")
        for node, value in potentials_raw.items()
    }
    source = problem["source"]
    target = problem["target"]
    if potentials[source] != 0:
        reject("SHORTEST_SOURCE_POTENTIAL", "source potential must be zero")
    for edge in problem["edges"]:
        if edge["tail"] in reachable:
            if edge["head"] not in reachable:
                reject("SHORTEST_REACHABILITY", "an edge from a reachable tail has an unreachable head")
            if potentials[edge["head"]] > potentials[edge["tail"]] + edge_costs[edge["id"]]:
                reject("SHORTEST_DUAL_INFEASIBLE", f"shortest-path potential inequality fails on edge {edge['id']}")
    edge_map = {edge["id"]: edge for edge in problem["edges"]}
    path_cost = sum((edge_costs[edge_id] for edge_id in proof["minimiser_decision"]["edge_ids"]), Fraction(0))
    if path_cost != potentials[target]:
        reject("SHORTEST_PRIMAL_DUAL_GAP", "proof path cost does not equal the target potential")
    total = path_cost + constant
    if parse_rational_string(proof["path_value"], where="proof.path_value") != path_cost:
        reject("SHORTEST_PATH_VALUE", "reported path value is incorrect")
    if parse_rational_string(proof["constant_value"], where="proof.constant_value") != constant:
        reject("SHORTEST_CONSTANT_VALUE", "reported shortest-path constant is incorrect")
    if parse_rational_string(proof["minimum_value"], where="proof.minimum_value") != total:
        reject("SHORTEST_MINIMUM", "reported shortest-path minimum is incorrect")
    if scalar_value(outcome, weights) != total:
        reject("SHORTEST_RECONSTRUCTION", "shortest-path outcome does not reconstruct the scalar minimum")
    return total


def common_denominator(values: Sequence[Fraction]) -> int:
    out = 1
    for value in values:
        out = abs(out // gcd(out, value.denominator) * value.denominator)
    return out


def verify_binary_trusted_proof(instance: dict[str, Any], transforms: tuple[Transform, ...], weights: tuple[Fraction, ...], proof: Any) -> Fraction:
    exact_keys(
        proof,
        {"minimiser_decision", "minimiser_outcome", "minimum_value", "weight_scale", "integer_weights", "oracle_statement"},
        where="positive_payload.oracle.proof",
    )
    outcome = evaluate_decision(instance, proof["minimiser_decision"], transforms)
    recorded_outcome = parse_outcome(proof["minimiser_outcome"], len(transforms), where="proof.minimiser_outcome")
    if recorded_outcome != outcome:
        reject("OUTCOME_MISMATCH", "trusted proof minimiser outcome is incorrect")
    value = scalar_value(outcome, weights)
    if parse_rational_string(proof["minimum_value"], where="proof.minimum_value") != value:
        reject("TRUSTED_MINIMUM_VALUE", "trusted proof minimum does not match its stated minimiser")
    scale = parse_int_string(proof["weight_scale"], positive=True, where="proof.weight_scale")
    raw_weights = proof["integer_weights"]
    if not isinstance(raw_weights, list) or len(raw_weights) != len(weights):
        reject("TRUSTED_INTEGER_WEIGHTS", "integer_weights has the wrong dimension")
    integer_weights = tuple(parse_int_string(item, where=f"proof.integer_weights[{idx}]") for idx, item in enumerate(raw_weights))
    if any(item < 0 for item in integer_weights) or sum(integer_weights) != scale:
        reject("TRUSTED_INTEGER_WEIGHTS", "integer_weights must be non-negative and sum to weight_scale")
    if any(Fraction(item, scale) != weight for item, weight in zip(integer_weights, weights)):
        reject("TRUSTED_INTEGER_WEIGHTS", "integer_weights do not encode the certificate weights")
    divisor = 0
    for item in integer_weights:
        divisor = gcd(divisor, abs(item))
    if divisor > 1:
        reject("TRUSTED_INTEGER_WEIGHTS", "integer weight representation is not primitive")
    if not isinstance(proof["oracle_statement"], str) or "trusted" not in proof["oracle_statement"].lower():
        reject("TRUSTED_ORACLE_STATEMENT", "P2 proof must contain an explicit trusted-oracle statement")
    return value


def verify_positive(
    certificate: dict[str, Any],
    instance: dict[str, Any],
    transforms: tuple[Transform, ...],
    candidate_outcome: tuple[int, ...],
) -> dict[str, Any]:
    payload = certificate["positive_payload"]
    exact_keys(
        payload,
        {"weights", "weight_floor", "candidate_scalar_value", "scalar_minimum", "oracle"},
        where="positive_payload",
    )
    p = len(transforms)
    weights = parse_weights(payload, p, certificate["claim"])
    candidate_scalar = scalar_value(candidate_outcome, weights)
    if parse_rational_string(payload["candidate_scalar_value"], where="positive_payload.candidate_scalar_value") != candidate_scalar:
        reject("POSITIVE_CANDIDATE_VALUE", "candidate_scalar_value is incorrect")
    scalar_minimum = parse_rational_string(payload["scalar_minimum"], where="positive_payload.scalar_minimum")
    oracle = payload["oracle"]
    exact_keys(oracle, {"adapter", "proof_type", "proof"}, where="positive_payload.oracle")
    if not isinstance(oracle["adapter"], str) or not isinstance(oracle["proof_type"], str):
        reject("POSITIVE_ORACLE", "oracle adapter and proof_type must be strings")

    ptype = instance["problem"]["type"]
    expected: dict[str, tuple[str, str, str]] = {
        "explicit_image": ("explicit_enumeration_exact_v1", "explicit_enumeration_v1", "P1_FULLY_CHECKABLE"),
        "assignment": ("assignment_exact_hungarian_v1", "assignment_primal_dual_v1", "P1_FULLY_CHECKABLE"),
        "shortest_path": ("shortest_path_exact_dijkstra_v1", "shortest_path_potentials_v1", "P1_FULLY_CHECKABLE"),
        "binary_linear": ("binary_linear_exact_enumeration_reference_v1", "trusted_scalar_optimum_assertion_v1", "P2_TRUSTED_ORACLE"),
    }
    adapter, proof_type, trust = expected[ptype]
    if oracle["adapter"] != adapter or oracle["proof_type"] != proof_type:
        reject("POSITIVE_ORACLE_ADAPTER", "oracle adapter or proof type does not match the instance class")
    if certificate["trust_level"] != trust:
        reject("TRUST_LEVEL", "certificate trust level does not match the oracle adapter")
    validate_provenance(certificate["provenance"], expected_adapter=adapter)

    if ptype == "explicit_image":
        proved_minimum = verify_explicit_proof(instance, transforms, weights, oracle["proof"])
    elif ptype == "assignment":
        proved_minimum = verify_assignment_proof(instance, transforms, weights, oracle["proof"])
    elif ptype == "shortest_path":
        proved_minimum = verify_shortest_proof(instance, transforms, weights, oracle["proof"])
    elif ptype == "binary_linear":
        proved_minimum = verify_binary_trusted_proof(instance, transforms, weights, oracle["proof"])
    else:
        reject("INSTANCE_PROBLEM_TYPE", "unsupported positive proof class")

    if scalar_minimum != proved_minimum:
        reject("POSITIVE_SCALAR_MINIMUM", "scalar_minimum differs from the oracle proof")
    if candidate_scalar != scalar_minimum:
        reject("POSITIVE_NOT_OPTIMAL", "candidate scalar value differs from the certified scalar minimum")

    if trust == "P2_TRUSTED_ORACLE":
        return {
            "status": "VALIDATED_NOT_FULLY_VERIFIED",
            "verification_level": trust,
            "claim": certificate["claim"],
            "objective_dimension": p,
            "weight_floor": f"{min(weights).numerator}/{min(weights).denominator}",
            "trusted_global_optimisation_calls": 1,
            "unverified_assertion": "global scalar optimality",
        }
    return {
        "status": "VERIFIED",
        "verification_level": trust,
        "claim": certificate["claim"],
        "objective_dimension": p,
        "weight_floor": f"{min(weights).numerator}/{min(weights).denominator}",
        "trusted_global_optimisation_calls": 0,
    }


def verify(instance: Any, certificate: Any) -> dict[str, Any]:
    transforms = validate_instance(instance)
    if not isinstance(certificate, dict):
        reject("CERTIFICATE_TYPE", "certificate must be an object")
    claim = certificate.get("claim")
    if claim == "nonnegative_weight_unsupported":
        required = {
            "format", "schema_version", "canonicalisation", "instance_digest", "problem_type",
            "candidate", "claim", "trust_level", "negative_payload", "provenance", "integrity",
        }
    elif claim in {"nonnegative_weight_supportable", "positive_weight_supportable"}:
        required = {
            "format", "schema_version", "canonicalisation", "instance_digest", "problem_type",
            "candidate", "claim", "trust_level", "positive_payload", "provenance", "integrity",
        }
    else:
        reject("CLAIM", "unsupported or missing certificate claim")
    exact_keys(certificate, required, where="certificate")
    if certificate["format"] != "pareto-support-certificate":
        reject("CERTIFICATE_FORMAT", "unexpected certificate format")
    if certificate["schema_version"] != SCHEMA_VERSION:
        reject("CERTIFICATE_VERSION", "unsupported certificate schema version")
    if certificate["canonicalisation"] != CANONICALISATION:
        reject("CERTIFICATE_CANONICALISATION", "unsupported certificate canonicalisation")
    if certificate["problem_type"] != instance["problem"]["type"]:
        reject("PROBLEM_TYPE_MISMATCH", "certificate problem_type differs from the instance")
    require_digest(certificate["instance_digest"], where="certificate.instance_digest")
    if certificate["instance_digest"] != instance_digest(instance):
        reject("INSTANCE_DIGEST_MISMATCH", "certificate is not bound to this mathematical instance")
    verify_integrity(certificate)
    _, candidate_outcome = validate_candidate(certificate["candidate"], instance, transforms)

    if claim == "nonnegative_weight_unsupported":
        validate_provenance(certificate["provenance"])
        result = verify_negative(certificate, instance, transforms, candidate_outcome)
    else:
        result = verify_positive(certificate, instance, transforms, candidate_outcome)
    result["instance_digest"] = certificate["instance_digest"]
    result["certificate_digest"] = certificate["integrity"]["certificate_digest"]
    result["checker"] = {
        "name": "pareto-support-checker",
        "version": "0.6.1",
        "dependencies": "python-standard-library-only",
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Independently verify an exact supportability proof object.")
    parser.add_argument("--instance", required=True, help="Instance JSON file")
    parser.add_argument("--certificate", required=True, help="Certificate JSON file")
    parser.add_argument("--require-p1", action="store_true", help="Reject P2 trusted-oracle outputs")
    parser.add_argument("--report", help="Optional path for the canonical JSON verification report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        instance = load_json_strict(args.instance)
        certificate = load_json_strict(args.certificate)
        report = verify(instance, certificate)
        if args.require_p1 and report["status"] != "VERIFIED":
            reject("P1_REQUIRED", "certificate is not fully verifiable at P1")
        text = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if args.report:
            Path(args.report).write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0 if report["status"] == "VERIFIED" else 2
    except Rejection as exc:
        report = {"status": "REJECTED", "error_code": exc.code, "message": exc.message}
        text = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if args.report:
            Path(args.report).write_text(text + "\n", encoding="utf-8")
        print(text)
        return 1
    except Exception as exc:  # hard boundary: no traceback leaks into machine output
        report = {"status": "REJECTED", "error_code": "INTERNAL_ERROR", "message": f"{type(exc).__name__}: {exc}"}
        text = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if args.report:
            Path(args.report).write_text(text + "\n", encoding="utf-8")
        print(text)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
