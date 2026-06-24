"""Instance validation, decision checking and exact objective evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import product
from typing import Any, Iterable, Iterator

from .canonical import canonical_json_bytes, parse_int_string


class InstanceError(ValueError):
    pass


@dataclass(frozen=True)
class ObjectiveTransform:
    sense: str
    multiplier: int
    offset: int

    @property
    def sign(self) -> int:
        return 1 if self.sense == "min" else -1

    def apply(self, raw_value: int) -> int:
        return self.sign * self.multiplier * raw_value + self.offset

    def coefficient(self, raw_coefficient: int) -> int:
        return self.sign * self.multiplier * raw_coefficient

    def constant(self, raw_constant: int) -> int:
        return self.sign * self.multiplier * raw_constant + self.offset


@dataclass(frozen=True)
class EvaluatedDecision:
    decision: Any
    outcome: tuple[int, ...]


def _exact_keys(obj: dict[str, Any], required: set[str], optional: set[str] = set()) -> None:
    if not isinstance(obj, dict):
        raise InstanceError("object required")
    missing = required - set(obj)
    extra = set(obj) - required - optional
    if missing:
        raise InstanceError(f"missing fields: {sorted(missing)}")
    if extra:
        raise InstanceError(f"unknown fields: {sorted(extra)}")


def parse_transforms(instance: dict[str, Any]) -> tuple[ObjectiveTransform, ...]:
    raw = instance.get("objective_transform")
    if not isinstance(raw, list) or not raw:
        raise InstanceError("objective_transform must be a non-empty array")
    transforms: list[ObjectiveTransform] = []
    for item in raw:
        _exact_keys(item, {"sense", "multiplier", "offset"})
        sense = item["sense"]
        if sense not in {"min", "max"}:
            raise InstanceError("objective sense must be min or max")
        multiplier = parse_int_string(item["multiplier"], positive=True)
        offset = parse_int_string(item["offset"])
        transforms.append(ObjectiveTransform(sense, multiplier, offset))
    return tuple(transforms)


def validate_instance(instance: dict[str, Any]) -> None:
    _exact_keys(instance, {"format", "schema_version", "objective_transform", "problem"}, {"metadata"})
    if instance["format"] != "pareto-support-instance":
        raise InstanceError("unexpected instance format")
    if instance["schema_version"] != "1.0.0":
        raise InstanceError("unsupported instance schema version")
    transforms = parse_transforms(instance)
    p = len(transforms)
    problem = instance["problem"]
    if not isinstance(problem, dict) or "type" not in problem:
        raise InstanceError("problem object with a type is required")
    ptype = problem["type"]
    if ptype == "explicit_image":
        _validate_explicit(problem, p)
    elif ptype == "binary_linear":
        _validate_binary(problem, p)
    elif ptype == "assignment":
        _validate_assignment(problem, p)
    elif ptype == "shortest_path":
        _validate_shortest(problem, transforms)
    else:
        raise InstanceError(f"unsupported problem type: {ptype}")


def _validate_metadata(metadata: Any) -> None:
    if metadata is not None and not isinstance(metadata, dict):
        raise InstanceError("metadata must be an object")


def _validate_explicit(problem: dict[str, Any], p: int) -> None:
    _exact_keys(problem, {"type", "alternatives"})
    alternatives = problem["alternatives"]
    if not isinstance(alternatives, list) or not alternatives:
        raise InstanceError("explicit image must contain alternatives")
    ids: set[str] = set()
    for item in alternatives:
        _exact_keys(item, {"id", "raw_objectives"})
        if not isinstance(item["id"], str) or not item["id"]:
            raise InstanceError("alternative id must be a non-empty string")
        if item["id"] in ids:
            raise InstanceError("alternative ids must be unique")
        ids.add(item["id"])
        values = item["raw_objectives"]
        if not isinstance(values, list) or len(values) != p:
            raise InstanceError("objective vector has the wrong dimension")
        for value in values:
            parse_int_string(value)


def _validate_binary(problem: dict[str, Any], p: int) -> None:
    _exact_keys(problem, {"type", "n", "constraints", "objectives"})
    n = problem["n"]
    if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > 256:
        raise InstanceError("n must be an integer between 1 and 256")
    constraints = problem["constraints"]
    if not isinstance(constraints, list):
        raise InstanceError("constraints must be an array")
    for constraint in constraints:
        _exact_keys(constraint, {"coefficients", "sense", "rhs"})
        coefficients = constraint["coefficients"]
        if not isinstance(coefficients, list) or len(coefficients) != n:
            raise InstanceError("constraint coefficient vector has the wrong length")
        for value in coefficients:
            parse_int_string(value)
        if constraint["sense"] not in {"<=", "=", ">="}:
            raise InstanceError("unsupported constraint sense")
        parse_int_string(constraint["rhs"])
    objectives = problem["objectives"]
    if not isinstance(objectives, list) or len(objectives) != p:
        raise InstanceError("binary objective count does not match objective_transform")
    for objective in objectives:
        _exact_keys(objective, {"coefficients", "constant"})
        coefficients = objective["coefficients"]
        if not isinstance(coefficients, list) or len(coefficients) != n:
            raise InstanceError("objective coefficient vector has the wrong length")
        for value in coefficients:
            parse_int_string(value)
        parse_int_string(objective["constant"])


def _validate_assignment(problem: dict[str, Any], p: int) -> None:
    _exact_keys(problem, {"type", "n", "objectives"})
    n = problem["n"]
    if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > 512:
        raise InstanceError("assignment dimension is invalid")
    objectives = problem["objectives"]
    if not isinstance(objectives, list) or len(objectives) != p:
        raise InstanceError("assignment objective count does not match objective_transform")
    for objective in objectives:
        _exact_keys(objective, {"costs", "constant"})
        matrix = objective["costs"]
        if not isinstance(matrix, list) or len(matrix) != n:
            raise InstanceError("assignment matrix has the wrong number of rows")
        for row in matrix:
            if not isinstance(row, list) or len(row) != n:
                raise InstanceError("assignment matrix is not square")
            for value in row:
                parse_int_string(value)
        parse_int_string(objective["constant"])


def _validate_shortest(problem: dict[str, Any], transforms: tuple[ObjectiveTransform, ...]) -> None:
    _exact_keys(problem, {"type", "nodes", "source", "target", "edges", "objective_constants"})
    nodes = problem["nodes"]
    if not isinstance(nodes, list) or len(nodes) < 2 or any(not isinstance(node, str) or not node for node in nodes):
        raise InstanceError("nodes must be a non-empty string array")
    if len(nodes) != len(set(nodes)):
        raise InstanceError("node ids must be unique")
    source = problem["source"]
    target = problem["target"]
    if source not in nodes or target not in nodes or source == target:
        raise InstanceError("source and target must be distinct listed nodes")
    constants = problem["objective_constants"]
    if not isinstance(constants, list) or len(constants) != len(transforms):
        raise InstanceError("shortest-path constants have the wrong dimension")
    for value in constants:
        parse_int_string(value)
    edges = problem["edges"]
    if not isinstance(edges, list) or not edges:
        raise InstanceError("shortest-path instance requires edges")
    edge_ids: set[str] = set()
    for edge in edges:
        _exact_keys(edge, {"id", "tail", "head", "costs"})
        if not isinstance(edge["id"], str) or not edge["id"] or edge["id"] in edge_ids:
            raise InstanceError("edge ids must be unique non-empty strings")
        edge_ids.add(edge["id"])
        if edge["tail"] not in nodes or edge["head"] not in nodes:
            raise InstanceError("edge endpoint is not a listed node")
        costs = edge["costs"]
        if not isinstance(costs, list) or len(costs) != len(transforms):
            raise InstanceError("edge cost vector has the wrong dimension")
        raw = [parse_int_string(value) for value in costs]
        for transform, value in zip(transforms, raw):
            if transform.coefficient(value) < 0:
                raise InstanceError(
                    "shortest_path requires non-negative canonical edge costs for every objective"
                )


def problem_type(instance: dict[str, Any]) -> str:
    return instance["problem"]["type"]


def evaluate_decision(instance: dict[str, Any], decision: Any) -> tuple[int, ...]:
    transforms = parse_transforms(instance)
    problem = instance["problem"]
    ptype = problem["type"]
    if ptype == "explicit_image":
        raw = _evaluate_explicit(problem, decision)
    elif ptype == "binary_linear":
        raw = _evaluate_binary(problem, decision)
    elif ptype == "assignment":
        raw = _evaluate_assignment(problem, decision)
    elif ptype == "shortest_path":
        raw = _evaluate_shortest(problem, decision)
    else:
        raise InstanceError("unsupported problem type")
    return tuple(transform.apply(value) for transform, value in zip(transforms, raw))


def _evaluate_explicit(problem: dict[str, Any], decision: Any) -> tuple[int, ...]:
    if not isinstance(decision, dict) or set(decision) != {"id"} or not isinstance(decision["id"], str):
        raise InstanceError("explicit-image decision must be an object containing id")
    for alternative in problem["alternatives"]:
        if alternative["id"] == decision["id"]:
            return tuple(parse_int_string(value) for value in alternative["raw_objectives"])
    raise InstanceError("explicit-image decision is not listed")


def _parse_bits(problem: dict[str, Any], decision: Any) -> tuple[int, ...]:
    if not isinstance(decision, dict) or set(decision) != {"bits"} or not isinstance(decision["bits"], str):
        raise InstanceError("binary decision must contain a bit string")
    bits = decision["bits"]
    if len(bits) != problem["n"] or any(char not in "01" for char in bits):
        raise InstanceError("binary decision has the wrong form")
    return tuple(int(char) for char in bits)


def _binary_feasible(problem: dict[str, Any], bits: tuple[int, ...]) -> bool:
    for constraint in problem["constraints"]:
        lhs = sum(parse_int_string(value) * bit for value, bit in zip(constraint["coefficients"], bits))
        rhs = parse_int_string(constraint["rhs"])
        sense = constraint["sense"]
        if sense == "<=" and not lhs <= rhs:
            return False
        if sense == "=" and not lhs == rhs:
            return False
        if sense == ">=" and not lhs >= rhs:
            return False
    return True


def _evaluate_binary(problem: dict[str, Any], decision: Any) -> tuple[int, ...]:
    bits = _parse_bits(problem, decision)
    if not _binary_feasible(problem, bits):
        raise InstanceError("binary decision is infeasible")
    out = []
    for objective in problem["objectives"]:
        value = parse_int_string(objective["constant"])
        value += sum(parse_int_string(coef) * bit for coef, bit in zip(objective["coefficients"], bits))
        out.append(value)
    return tuple(out)


def _parse_permutation(problem: dict[str, Any], decision: Any) -> tuple[int, ...]:
    if not isinstance(decision, dict) or set(decision) != {"permutation"}:
        raise InstanceError("assignment decision must contain a permutation")
    permutation = decision["permutation"]
    n = problem["n"]
    if (
        not isinstance(permutation, list)
        or len(permutation) != n
        or any(not isinstance(value, int) or isinstance(value, bool) for value in permutation)
        or sorted(permutation) != list(range(n))
    ):
        raise InstanceError("assignment decision is not a permutation")
    return tuple(permutation)


def _evaluate_assignment(problem: dict[str, Any], decision: Any) -> tuple[int, ...]:
    permutation = _parse_permutation(problem, decision)
    out = []
    for objective in problem["objectives"]:
        value = parse_int_string(objective["constant"])
        matrix = objective["costs"]
        value += sum(parse_int_string(matrix[row][column]) for row, column in enumerate(permutation))
        out.append(value)
    return tuple(out)


def _edge_map(problem: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {edge["id"]: edge for edge in problem["edges"]}


def _evaluate_shortest(problem: dict[str, Any], decision: Any) -> tuple[int, ...]:
    if not isinstance(decision, dict) or set(decision) != {"edge_ids"}:
        raise InstanceError("shortest-path decision must contain edge_ids")
    edge_ids = decision["edge_ids"]
    if not isinstance(edge_ids, list) or not edge_ids or any(not isinstance(item, str) for item in edge_ids):
        raise InstanceError("edge_ids must be a non-empty string array")
    edges = _edge_map(problem)
    node = problem["source"]
    seen = {node}
    raw = [parse_int_string(value) for value in problem["objective_constants"]]
    for edge_id in edge_ids:
        edge = edges.get(edge_id)
        if edge is None or edge["tail"] != node:
            raise InstanceError("edge sequence is not a source-to-target path")
        node = edge["head"]
        if node in seen:
            raise InstanceError("shortest-path decision must be simple")
        seen.add(node)
        for idx, value in enumerate(edge["costs"]):
            raw[idx] += parse_int_string(value)
    if node != problem["target"]:
        raise InstanceError("path does not end at the target")
    return tuple(raw)


def enumerate_decisions(instance: dict[str, Any], *, binary_limit: int = 24) -> Iterator[Any]:
    problem = instance["problem"]
    ptype = problem["type"]
    if ptype == "explicit_image":
        for alternative in sorted(problem["alternatives"], key=lambda item: item["id"]):
            yield {"id": alternative["id"]}
        return
    if ptype == "binary_linear":
        n = problem["n"]
        if n > binary_limit:
            raise InstanceError(f"binary enumeration is limited to n <= {binary_limit}")
        for bits in product((0, 1), repeat=n):
            if _binary_feasible(problem, bits):
                yield {"bits": "".join(str(value) for value in bits)}
        return
    if ptype == "assignment":
        from itertools import permutations

        for permutation in permutations(range(problem["n"])):
            yield {"permutation": list(permutation)}
        return
    if ptype == "shortest_path":
        yield from _enumerate_simple_paths(problem)
        return
    raise InstanceError("unsupported problem type")


def _enumerate_simple_paths(problem: dict[str, Any]) -> Iterator[Any]:
    outgoing: dict[str, list[dict[str, Any]]] = {node: [] for node in problem["nodes"]}
    for edge in problem["edges"]:
        outgoing[edge["tail"]].append(edge)
    for edges in outgoing.values():
        edges.sort(key=lambda edge: edge["id"])
    source = problem["source"]
    target = problem["target"]

    def visit(node: str, seen: set[str], edge_ids: list[str]) -> Iterator[Any]:
        if node == target:
            yield {"edge_ids": list(edge_ids)}
            return
        for edge in outgoing[node]:
            if edge["head"] in seen:
                continue
            seen.add(edge["head"])
            edge_ids.append(edge["id"])
            yield from visit(edge["head"], seen, edge_ids)
            edge_ids.pop()
            seen.remove(edge["head"])

    yield from visit(source, {source}, [])


def decision_key(decision: Any) -> bytes:
    return canonical_json_bytes(decision)


def scalar_value(outcome: Iterable[int], weights: Iterable[Fraction]) -> Fraction:
    return sum((Fraction(value) * weight for value, weight in zip(outcome, weights)), Fraction(0))
