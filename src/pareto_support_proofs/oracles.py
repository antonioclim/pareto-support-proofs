"""Exact weighted-sum oracle adapters with explicit trust boundaries.

The adapters receive an exact rational simplex vector and return a globally
optimal feasible decision for the corresponding scalarised problem. P1
adapters also return a compact proof that the standalone checker can replay.
The binary-linear reference adapter is deliberately classified as P2: the
generator obtains an exact answer by exhaustive enumeration for small models
but the independent checker does not repeat that global search.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import heapq
from typing import Any, Sequence

from .canonical import int_string, rational_string, sha256_hex
from .exact import scaled_integer_weights
from .instance import (
    InstanceError,
    decision_key,
    enumerate_decisions,
    evaluate_decision,
    parse_transforms,
    problem_type,
    scalar_value,
)


@dataclass(frozen=True)
class OracleAnswer:
    decision: Any
    outcome: tuple[int, ...]
    scalar_value: Fraction
    trust_level: str
    oracle_name: str
    proof_type: str
    proof: dict[str, Any]

    @property
    def decision_digest(self) -> str:
        return sha256_hex(self.decision)


def _validate_weights(weights: Sequence[Fraction], p: int) -> tuple[Fraction, ...]:
    out = tuple(Fraction(value) for value in weights)
    if len(out) != p or any(value < 0 for value in out) or sum(out, Fraction(0)) != 1:
        raise ValueError("weights must belong to the p-dimensional unit simplex")
    return out


def solve_scalar(instance: dict[str, Any], weights: Sequence[Fraction]) -> OracleAnswer:
    """Solve one exact weighted-sum problem through the registered adapter."""
    transforms = parse_transforms(instance)
    lam = _validate_weights(weights, len(transforms))
    ptype = problem_type(instance)
    if ptype == "explicit_image":
        return _explicit_oracle(instance, lam)
    if ptype == "assignment":
        return _assignment_oracle(instance, lam)
    if ptype == "shortest_path":
        return _shortest_path_oracle(instance, lam)
    if ptype == "binary_linear":
        return _binary_oracle(instance, lam)
    raise InstanceError(f"unsupported oracle problem type: {ptype}")



def _explicit_oracle(instance: dict[str, Any], weights: tuple[Fraction, ...]) -> OracleAnswer:
    candidates: list[tuple[Fraction, bytes, Any, tuple[int, ...]]] = []
    for decision in enumerate_decisions(instance):
        outcome = evaluate_decision(instance, decision)
        candidates.append((scalar_value(outcome, weights), decision_key(decision), decision, outcome))
    value, _, decision, outcome = min(candidates, key=lambda item: (item[0], item[1]))
    return OracleAnswer(
        decision=decision,
        outcome=outcome,
        scalar_value=value,
        trust_level="P1_FULLY_CHECKABLE",
        oracle_name="explicit_enumeration_exact_v1",
        proof_type="explicit_enumeration_v1",
        proof={
            "minimiser_decision": decision,
            "minimiser_outcome": [int_string(item) for item in outcome],
            "minimum_value": rational_string(value),
            "tie_break": "canonical-decision-order",
        },
    )


@dataclass(frozen=True)
class AssignmentSolution:
    permutation: tuple[int, ...]
    value: Fraction
    row_potentials: tuple[Fraction, ...]
    column_potentials: tuple[Fraction, ...]


def _hungarian(costs: Sequence[Sequence[Fraction]]) -> AssignmentSolution:
    """Solve a square assignment exactly and return primal-dual witnesses."""
    n = len(costs)
    if n == 0 or any(len(row) != n for row in costs):
        raise ValueError("the Hungarian oracle requires a non-empty square matrix")
    a = [[Fraction(0)] * (n + 1)] + [
        [Fraction(0)] + [Fraction(value) for value in row] for row in costs
    ]
    u = [Fraction(0)] * (n + 1)
    v = [Fraction(0)] * (n + 1)
    matched_row = [0] * (n + 1)
    predecessor = [0] * (n + 1)

    for row in range(1, n + 1):
        matched_row[0] = row
        current_column = 0
        reduced: list[Fraction | None] = [None] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[current_column] = True
            current_row = matched_row[current_column]
            delta: Fraction | None = None
            next_column = 0
            for column in range(1, n + 1):
                if used[column]:
                    continue
                candidate = a[current_row][column] - u[current_row] - v[column]
                if reduced[column] is None or candidate < reduced[column]:
                    reduced[column] = candidate
                    predecessor[column] = current_column
                assert reduced[column] is not None
                if delta is None or (reduced[column], column) < (delta, next_column):
                    delta = reduced[column]
                    next_column = column
            if delta is None:
                raise AssertionError("Hungarian search failed")
            for column in range(n + 1):
                if used[column]:
                    u[matched_row[column]] += delta
                    v[column] -= delta
                elif column > 0:
                    assert reduced[column] is not None
                    reduced[column] -= delta
            current_column = next_column
            if matched_row[current_column] == 0:
                break
        while True:
            previous_column = predecessor[current_column]
            matched_row[current_column] = matched_row[previous_column]
            current_column = previous_column
            if current_column == 0:
                break

    permutation = [-1] * n
    for column in range(1, n + 1):
        permutation[matched_row[column] - 1] = column - 1
    if sorted(permutation) != list(range(n)):
        raise AssertionError("Hungarian oracle returned a non-permutation")
    value = sum(costs[row][permutation[row]] for row in range(n))
    row_potentials = tuple(u[1:])
    column_potentials = tuple(v[1:])
    dual_value = sum(row_potentials, Fraction(0)) + sum(column_potentials, Fraction(0))
    if dual_value != value:
        raise AssertionError("Hungarian primal and dual values differ")
    if any(
        row_potentials[row] + column_potentials[column] > costs[row][column]
        for row in range(n)
        for column in range(n)
    ):
        raise AssertionError("Hungarian potentials are dual infeasible")
    if any(
        row_potentials[row] + column_potentials[permutation[row]] != costs[row][permutation[row]]
        for row in range(n)
    ):
        raise AssertionError("Hungarian matched edges are not tight")
    return AssignmentSolution(tuple(permutation), value, row_potentials, column_potentials)


def _assignment_weighted_data(
    instance: dict[str, Any], weights: tuple[Fraction, ...]
) -> tuple[tuple[tuple[Fraction, ...], ...], Fraction]:
    problem = instance["problem"]
    transforms = parse_transforms(instance)
    n = problem["n"]
    matrix: list[tuple[Fraction, ...]] = []
    for row in range(n):
        matrix_row: list[Fraction] = []
        for column in range(n):
            value = Fraction(0)
            for objective, transform, weight in zip(problem["objectives"], transforms, weights):
                raw = int(objective["costs"][row][column])
                value += weight * transform.coefficient(raw)
            matrix_row.append(value)
        matrix.append(tuple(matrix_row))
    constant = Fraction(0)
    for objective, transform, weight in zip(problem["objectives"], transforms, weights):
        constant += weight * transform.constant(int(objective["constant"]))
    return tuple(matrix), constant


def _assignment_oracle(instance: dict[str, Any], weights: tuple[Fraction, ...]) -> OracleAnswer:
    matrix, constant = _assignment_weighted_data(instance, weights)
    solution = _hungarian(matrix)
    decision = {"permutation": list(solution.permutation)}
    outcome = evaluate_decision(instance, decision)
    total = solution.value + constant
    if scalar_value(outcome, weights) != total:
        raise AssertionError("assignment objective reconstruction failed")
    return OracleAnswer(
        decision=decision,
        outcome=outcome,
        scalar_value=total,
        trust_level="P1_FULLY_CHECKABLE",
        oracle_name="assignment_exact_hungarian_v1",
        proof_type="assignment_primal_dual_v1",
        proof={
            "minimiser_decision": decision,
            "minimiser_outcome": [int_string(item) for item in outcome],
            "minimum_value": rational_string(total),
            "matrix_value": rational_string(solution.value),
            "constant_value": rational_string(constant),
            "row_potentials": [rational_string(value) for value in solution.row_potentials],
            "column_potentials": [rational_string(value) for value in solution.column_potentials],
        },
    )


def _shortest_path_weighted_data(
    instance: dict[str, Any], weights: tuple[Fraction, ...]
) -> tuple[dict[str, Fraction], Fraction]:
    problem = instance["problem"]
    transforms = parse_transforms(instance)
    edge_costs: dict[str, Fraction] = {}
    for edge in problem["edges"]:
        value = Fraction(0)
        for raw, transform, weight in zip(edge["costs"], transforms, weights):
            value += weight * transform.coefficient(int(raw))
        if value < 0:
            raise InstanceError("canonical weighted shortest-path edge cost became negative")
        edge_costs[edge["id"]] = value
    constant = Fraction(0)
    for raw, transform, weight in zip(problem["objective_constants"], transforms, weights):
        constant += weight * transform.constant(int(raw))
    return edge_costs, constant


def _shortest_path_oracle(instance: dict[str, Any], weights: tuple[Fraction, ...]) -> OracleAnswer:
    problem = instance["problem"]
    edge_costs, constant = _shortest_path_weighted_data(instance, weights)
    outgoing: dict[str, list[dict[str, Any]]] = {node: [] for node in problem["nodes"]}
    for edge in problem["edges"]:
        outgoing[edge["tail"]].append(edge)
    for edges in outgoing.values():
        edges.sort(key=lambda edge: edge["id"])

    source = problem["source"]
    target = problem["target"]
    distances: dict[str, Fraction | None] = {node: None for node in problem["nodes"]}
    distances[source] = Fraction(0)
    predecessor: dict[str, str] = {}
    queue: list[tuple[Fraction, str]] = [(Fraction(0), source)]
    while queue:
        distance, node = heapq.heappop(queue)
        if distances[node] != distance:
            continue
        for edge in outgoing[node]:
            head = edge["head"]
            candidate = distance + edge_costs[edge["id"]]
            incumbent = distances[head]
            incumbent_edge = predecessor.get(head)
            if incumbent is None or candidate < incumbent or (
                candidate == incumbent and (incumbent_edge is None or edge["id"] < incumbent_edge)
            ):
                distances[head] = candidate
                predecessor[head] = edge["id"]
                heapq.heappush(queue, (candidate, head))
    if distances[target] is None:
        raise InstanceError("shortest-path instance has no source-to-target path")

    edges_by_id = {edge["id"]: edge for edge in problem["edges"]}
    path: list[str] = []
    node = target
    while node != source:
        edge_id = predecessor.get(node)
        if edge_id is None:
            raise AssertionError("shortest-path predecessor chain is incomplete")
        path.append(edge_id)
        node = edges_by_id[edge_id]["tail"]
    path.reverse()
    decision = {"edge_ids": path}
    outcome = evaluate_decision(instance, decision)
    assert distances[target] is not None
    total = distances[target] + constant
    if scalar_value(outcome, weights) != total:
        raise AssertionError("shortest-path objective reconstruction failed")
    potential_payload = {
        node_id: rational_string(value)
        for node_id, value in sorted(distances.items())
        if value is not None
    }
    return OracleAnswer(
        decision=decision,
        outcome=outcome,
        scalar_value=total,
        trust_level="P1_FULLY_CHECKABLE",
        oracle_name="shortest_path_exact_dijkstra_v1",
        proof_type="shortest_path_potentials_v1",
        proof={
            "minimiser_decision": decision,
            "minimiser_outcome": [int_string(item) for item in outcome],
            "minimum_value": rational_string(total),
            "path_value": rational_string(distances[target]),
            "constant_value": rational_string(constant),
            "node_potentials": potential_payload,
        },
    )


def _binary_oracle(instance: dict[str, Any], weights: tuple[Fraction, ...]) -> OracleAnswer:
    best: tuple[Fraction, bytes, Any, tuple[int, ...]] | None = None
    for decision in enumerate_decisions(instance, binary_limit=24):
        outcome = evaluate_decision(instance, decision)
        candidate = (scalar_value(outcome, weights), decision_key(decision), decision, outcome)
        if best is None or (candidate[0], candidate[1]) < (best[0], best[1]):
            best = candidate
    if best is None:
        raise InstanceError("binary instance has no feasible decision")
    value, _, decision, outcome = best
    scale, integer_weights = scaled_integer_weights(weights)
    return OracleAnswer(
        decision=decision,
        outcome=outcome,
        scalar_value=value,
        trust_level="P2_TRUSTED_ORACLE",
        oracle_name="binary_linear_exact_enumeration_reference_v1",
        proof_type="trusted_scalar_optimum_assertion_v1",
        proof={
            "minimiser_decision": decision,
            "minimiser_outcome": [int_string(item) for item in outcome],
            "minimum_value": rational_string(value),
            "weight_scale": int_string(scale),
            "integer_weights": [int_string(item) for item in integer_weights],
            "oracle_statement": (
                "global optimality is asserted by the generator and is outside the "
                "standalone checker's trusted-free verification boundary"
            ),
        },
    )
