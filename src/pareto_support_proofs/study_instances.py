"""Deterministic instance construction for the computational study.

The constructors deliberately separate candidate selection from weighted-sum
supportability testing.  Small candidates are selected by epsilon constraints
or by a hash ordering.  Large structured instances are fixed theorem-targeted
constructions and are never presented as prevalence samples.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from itertools import permutations
import math
import random
from typing import Any, Iterable, Sequence

from .canonical import canonical_json_bytes
from .instance import enumerate_decisions, evaluate_decision


@dataclass(frozen=True)
class Evaluated:
    decision: Any
    outcome: tuple[int, ...]


def transforms(p: int, *, sense: str = "min") -> list[dict[str, str]]:
    return [{"sense": sense, "multiplier": "1", "offset": "0"} for _ in range(p)]


def enumerate_evaluated(instance: dict[str, Any], *, binary_limit: int = 24) -> list[Evaluated]:
    return [
        Evaluated(decision, evaluate_decision(instance, decision))
        for decision in enumerate_decisions(instance, binary_limit=binary_limit)
    ]


def _decision_hash(decision: Any, seed: int) -> bytes:
    return sha256(str(seed).encode("ascii") + b"|" + canonical_json_bytes(decision)).digest()


def select_candidates_independently(
    evaluated: Sequence[Evaluated], *, seed: int
) -> list[tuple[str, Evaluated]]:
    """Return one epsilon-constraint candidate and one hash-selected control.

    The epsilon thresholds are empirical quantiles of the enumerated image.
    No supportability LP, weight search or certificate output is consulted.
    """
    if not evaluated:
        raise ValueError("candidate selection requires at least one feasible decision")
    p = len(evaluated[0].outcome)
    primary = seed % p
    quantiles = (0.42, 0.58)
    selected: list[tuple[str, Evaluated]] = []
    for candidate_no, quantile in enumerate(quantiles[:1]):
        thresholds: dict[int, int] = {}
        for j in range(p):
            if j == primary:
                continue
            values = sorted(item.outcome[j] for item in evaluated)
            idx = min(len(values) - 1, max(0, int(round(quantile * (len(values) - 1)))))
            thresholds[j] = values[idx]
        feasible = [
            item for item in evaluated
            if all(item.outcome[j] <= bound for j, bound in thresholds.items())
        ]
        if not feasible:
            feasible = list(evaluated)
        best = min(
            feasible,
            key=lambda item: (
                item.outcome[primary],
                sum(item.outcome),
                item.outcome,
                canonical_json_bytes(item.decision),
            ),
        )
        selected.append((f"epsilon_q{int(quantile * 100):02d}", best))
    hash_choice = min(evaluated, key=lambda item: _decision_hash(item.decision, seed + 99173))
    if hash_choice.decision != selected[0][1].decision:
        selected.append(("hash_control", hash_choice))
    else:
        second = sorted(evaluated, key=lambda item: _decision_hash(item.decision, seed + 99173))[1]
        selected.append(("hash_control", second))
    return selected


def make_random_explicit(*, p: int, alternatives: int, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    points: list[dict[str, Any]] = []
    seen: set[tuple[int, ...]] = set()
    while len(points) < alternatives:
        point = tuple(rng.randint(0, 120) for _ in range(p))
        if point in seen:
            continue
        seen.add(point)
        points.append({"id": f"a{len(points):03d}", "raw_objectives": [str(v) for v in point]})
    return {
        "format": "pareto-support-instance",
        "schema_version": "1.0.0",
        "objective_transform": transforms(p),
        "problem": {"type": "explicit_image", "alternatives": points},
        "metadata": {"family": "random_explicit", "seed": seed},
    }


def make_random_assignment(*, n: int, p: int, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    objectives = []
    for objective in range(p):
        costs = [[str(rng.randint(0, 90)) for _ in range(n)] for _ in range(n)]
        objectives.append({"costs": costs, "constant": str(rng.randint(-5, 5))})
    return {
        "format": "pareto-support-instance",
        "schema_version": "1.0.0",
        "objective_transform": transforms(p),
        "problem": {"type": "assignment", "n": n, "objectives": objectives},
        "metadata": {"family": "random_assignment", "seed": seed},
    }


def make_random_shortest_path(*, n: int, p: int, seed: int, edge_probability: float = 0.30) -> dict[str, Any]:
    rng = random.Random(seed)
    nodes = [f"v{i}" for i in range(n)]
    edges: list[dict[str, Any]] = []
    edge_no = 0
    for i in range(n - 1):
        edge_no += 1
        edges.append({
            "id": f"e{edge_no:04d}",
            "tail": nodes[i],
            "head": nodes[i + 1],
            "costs": [str(rng.randint(1, 30)) for _ in range(p)],
        })
    for i in range(n - 2):
        for j in range(i + 2, n):
            if rng.random() < edge_probability:
                edge_no += 1
                edges.append({
                    "id": f"e{edge_no:04d}",
                    "tail": nodes[i],
                    "head": nodes[j],
                    "costs": [str(rng.randint(1, 35)) for _ in range(p)],
                })
    return {
        "format": "pareto-support-instance",
        "schema_version": "1.0.0",
        "objective_transform": transforms(p),
        "problem": {
            "type": "shortest_path",
            "nodes": nodes,
            "source": nodes[0],
            "target": nodes[-1],
            "edges": edges,
            "objective_constants": ["0"] * p,
        },
        "metadata": {"family": "random_shortest_path", "seed": seed},
    }


def make_random_knapsack(*, n: int, p: int, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    weights = [rng.randint(2, 20) for _ in range(n)]
    capacity = max(1, int(round(0.42 * sum(weights))))
    objectives = []
    for _ in range(p):
        profits = [rng.randint(5, 70) for _ in range(n)]
        objectives.append({"coefficients": [str(v) for v in profits], "constant": "0"})
    return {
        "format": "pareto-support-instance",
        "schema_version": "1.0.0",
        "objective_transform": transforms(p, sense="max"),
        "problem": {
            "type": "binary_linear",
            "n": n,
            "constraints": [{
                "coefficients": [str(v) for v in weights],
                "sense": "<=",
                "rhs": str(capacity),
            }],
            "objectives": objectives,
        },
        "metadata": {
            "family": "random_knapsack",
            "seed": seed,
            "weights": weights,
            "capacity": capacity,
        },
    }


def tight_rows(p: int) -> list[tuple[int, ...]]:
    if p < 2:
        raise ValueError("p must be at least two")
    return [tuple(-p if i == j else 1 for i in range(p)) for j in range(p)]


def make_tight_explicit(*, p: int, offset: int | None = None) -> tuple[dict[str, Any], dict[str, str]]:
    base = offset if offset is not None else p + 3
    y0 = tuple(base for _ in range(p))
    alternatives = [{"id": "candidate", "raw_objectives": [str(v) for v in y0]}]
    for j, row in enumerate(tight_rows(p)):
        alternatives.append({
            "id": f"challenger_{j + 1}",
            "raw_objectives": [str(y0[i] + row[i]) for i in range(p)],
        })
    instance = {
        "format": "pareto-support-instance",
        "schema_version": "1.0.0",
        "objective_transform": transforms(p),
        "problem": {"type": "explicit_image", "alternatives": alternatives},
        "metadata": {"family": "tight_explicit", "p": p},
    }
    return instance, {"id": "candidate"}


def make_grid_interval_explicit(*, q: int) -> tuple[dict[str, Any], dict[str, str], tuple[int, int, int, int]]:
    """Build a two-objective candidate supported on a very narrow interval.

    The exact support interval is [(q+1)/(2q), (q+3)/(2q)] and has width 1/q.
    """
    if q < 20:
        raise ValueError("q must be at least 20")
    base = q + 10
    lower_num, lower_den = q + 1, 2 * q
    upper_num, upper_den = q + 3, 2 * q
    d_low = (lower_den - lower_num, -lower_num)
    d_high = (-(upper_den - upper_num), upper_num)
    y0 = (base, base)
    alternatives = [
        {"id": "candidate", "raw_objectives": [str(v) for v in y0]},
        {"id": "lower_cut", "raw_objectives": [str(y0[i] + d_low[i]) for i in range(2)]},
        {"id": "upper_cut", "raw_objectives": [str(y0[i] + d_high[i]) for i in range(2)]},
    ]
    instance = {
        "format": "pareto-support-instance",
        "schema_version": "1.0.0",
        "objective_transform": transforms(2),
        "problem": {"type": "explicit_image", "alternatives": alternatives},
        "metadata": {"family": "narrow_support_interval", "q": q},
    }
    return instance, {"id": "candidate"}, (lower_num, lower_den, upper_num, upper_den)


def make_large_assignment_positive(*, n: int, p: int, seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(seed)
    objectives = []
    for k in range(p):
        matrix: list[list[str]] = []
        for i in range(n):
            row = []
            for j in range(n):
                if i == j:
                    row.append("0")
                else:
                    row.append(str(50 + ((i + 3) * (j + 5) * (k + 7) + rng.randint(0, 19)) % 151))
            matrix.append(row)
        objectives.append({"costs": matrix, "constant": "0"})
    instance = {
        "format": "pareto-support-instance",
        "schema_version": "1.0.0",
        "objective_transform": transforms(p),
        "problem": {"type": "assignment", "n": n, "objectives": objectives},
        "metadata": {"family": "large_assignment_positive", "seed": seed},
    }
    return instance, {"permutation": list(range(n))}


def make_large_shortest_path(
    *, p: int, path_length: int, claim: str, seed: int
) -> tuple[dict[str, Any], dict[str, Any], float]:
    if claim not in {"supportable", "unsupported"}:
        raise ValueError("claim must be supportable or unsupported")
    if path_length < 2:
        raise ValueError("path_length must be at least two")
    rng = random.Random(seed)
    source, target = "s", "t"
    nodes = [source, target]
    edges: list[dict[str, Any]] = []
    route_decisions: list[list[str]] = []
    base = 3 * p + 20
    if claim == "supportable":
        totals = [tuple(base for _ in range(p))]
        totals.extend(tuple(base + 7 + j for _ in range(p)) for j in range(p))
    else:
        totals = [tuple(base for _ in range(p))]
        totals.extend(tuple(base + row[i] for i in range(p)) for row in tight_rows(p))
    for route_no, total in enumerate(totals):
        previous = source
        route_edges: list[str] = []
        for layer in range(path_length):
            head = target if layer == path_length - 1 else f"r{route_no}_{layer + 1}"
            if head not in {source, target}:
                nodes.append(head)
            edge_id = f"r{route_no}_e{layer + 1:04d}"
            costs = total if layer == 0 else tuple(0 for _ in range(p))
            edges.append({
                "id": edge_id,
                "tail": previous,
                "head": head,
                "costs": [str(v) for v in costs],
            })
            route_edges.append(edge_id)
            previous = head
        route_decisions.append(route_edges)
    # A binary layered branch contributes 2^L additional dominated paths.
    background_nodes = [source] + [f"b{i}" for i in range(1, path_length)] + [target]
    for node in background_nodes[1:-1]:
        nodes.append(node)
    high = base * (p + 5) + 100
    for layer in range(path_length):
        tail = background_nodes[layer]
        head = background_nodes[layer + 1]
        for choice in range(2):
            edge_id = f"b{layer + 1:04d}_{choice}"
            perturb = rng.randint(0, 3)
            edges.append({
                "id": edge_id,
                "tail": tail,
                "head": head,
                "costs": [str(high + perturb + choice) for _ in range(p)],
            })
    instance = {
        "format": "pareto-support-instance",
        "schema_version": "1.0.0",
        "objective_transform": transforms(p),
        "problem": {
            "type": "shortest_path",
            "nodes": sorted(set(nodes)),
            "source": source,
            "target": target,
            "edges": edges,
            "objective_constants": ["0"] * p,
        },
        "metadata": {
            "family": "large_shortest_path",
            "claim": claim,
            "path_length": path_length,
            "catalogue_description": f"{len(totals)} controlled paths plus 2^{path_length} background paths",
        },
    }
    log10_catalogue = path_length * math.log10(2.0)
    return instance, {"edge_ids": route_decisions[0]}, log10_catalogue
