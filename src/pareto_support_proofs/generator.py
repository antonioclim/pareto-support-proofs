"""Deterministic exact exchange generation of supportability proof objects."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from typing import Any

from . import CANONICALISATION, SCHEMA_VERSION, __version__
from .canonical import (
    canonical_json_bytes,
    decision_sort_key,
    instance_digest,
    int_string,
    rational_string,
    seal_certificate,
    sha256_hex,
)
from .exact import dual_margin_exact, primal_margin_exact, primitive_integer_certificate
from .instance import evaluate_decision, problem_type, scalar_value, validate_instance
from .oracles import solve_scalar


@dataclass(frozen=True)
class GenerationResult:
    certificate: dict[str, Any]
    trace: dict[str, Any]


def _difference(outcome: tuple[int, ...], candidate: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(value - base for value, base in zip(outcome, candidate))


def _digest_label(hex_value: str) -> str:
    return f"sha256:{hex_value}"


def _candidate_payload(decision: Any, outcome: tuple[int, ...]) -> dict[str, Any]:
    return {
        "decision": deepcopy(decision),
        "decision_digest": _digest_label(sha256_hex(decision)),
        "outcome": [int_string(value) for value in outcome],
    }


def _base_certificate(instance: dict[str, Any], candidate_decision: Any, candidate_outcome: tuple[int, ...]) -> dict[str, Any]:
    return {
        "format": "pareto-support-certificate",
        "schema_version": SCHEMA_VERSION,
        "canonicalisation": CANONICALISATION,
        "instance_digest": _digest_label(instance_digest(instance)),
        "problem_type": problem_type(instance),
        "candidate": _candidate_payload(candidate_decision, candidate_outcome),
    }


def generate_certificate(
    instance: dict[str, Any],
    candidate_decision: Any,
    *,
    max_iterations: int = 10_000,
    context: dict[str, Any] | None = None,
) -> GenerationResult:
    """Generate a positive or negative exact certificate.

    The restricted master is solved by rational vertex enumeration. Every cut
    retains the concrete feasible decision and its exact objective vector.
    Negative certificates are locally checkable and use at most ``p`` atoms.
    Positive certificates inherit the P1/P2 trust level of the scalar oracle.
    """
    validate_instance(instance)
    if not isinstance(max_iterations, int) or isinstance(max_iterations, bool) or max_iterations < 1:
        raise ValueError("max_iterations must be a positive integer")
    candidate_outcome = evaluate_decision(instance, candidate_decision)
    p = len(candidate_outcome)
    weights = tuple(Fraction(1, p) for _ in range(p))

    pool: list[dict[str, Any]] = []
    outcome_to_pool: dict[tuple[int, ...], int] = {}
    iterations: list[dict[str, Any]] = []
    last_oracle_name = "none"

    for iteration in range(1, max_iterations + 1):
        oracle = solve_scalar(instance, weights)
        last_oracle_name = oracle.oracle_name
        candidate_scalar = scalar_value(candidate_outcome, weights)
        difference = _difference(oracle.outcome, candidate_outcome)
        oracle_gap = oracle.scalar_value - candidate_scalar
        step: dict[str, Any] = {
            "iteration": iteration,
            "weights": [rational_string(value) for value in weights],
            "oracle_adapter": oracle.oracle_name,
            "oracle_trust_level": oracle.trust_level,
            "oracle_proof_type": oracle.proof_type,
            "oracle_decision": deepcopy(oracle.decision),
            "oracle_outcome": [int_string(value) for value in oracle.outcome],
            "oracle_gap": rational_string(oracle_gap),
            "pool_size_before": len(pool),
        }

        # The candidate itself is feasible, so an exact oracle value cannot
        # exceed the candidate value. Equality is the positive stopping test.
        if oracle.scalar_value == candidate_scalar:
            claim = (
                "positive_weight_supportable"
                if all(value > 0 for value in weights)
                else "nonnegative_weight_supportable"
            )
            step["termination"] = "positive_scalar_optimality"
            iterations.append(step)
            trace = {
                "format": "pareto-support-generation-trace",
                "schema_version": SCHEMA_VERSION,
                "canonicalisation": CANONICALISATION,
                "result": claim,
                "iterations": iterations,
            }
            trace_digest = _digest_label(sha256(canonical_json_bytes(trace)).hexdigest())
            certificate = _base_certificate(instance, candidate_decision, candidate_outcome)
            certificate.update(
                {
                    "claim": claim,
                    "trust_level": oracle.trust_level,
                    "positive_payload": {
                        "weights": [rational_string(value) for value in weights],
                        "weight_floor": rational_string(min(weights)),
                        "candidate_scalar_value": rational_string(candidate_scalar),
                        "scalar_minimum": rational_string(oracle.scalar_value),
                        "oracle": {
                            "adapter": oracle.oracle_name,
                            "proof_type": oracle.proof_type,
                            "proof": deepcopy(oracle.proof),
                        },
                    },
                    "provenance": {
                        "generator": {"name": "pareto-support-proofs", "version": __version__},
                        "algorithm": "exact-exchange-v1",
                        "oracle_adapter": oracle.oracle_name,
                        "trace_digest": trace_digest,
                        "exact_arithmetic": "fractions.Fraction",
                        "deterministic": True,
                    },
                }
            )
            if context:
                certificate["provenance"]["context"] = deepcopy(context)
            return GenerationResult(seal_certificate(certificate), trace)

        if oracle_gap >= 0:
            raise AssertionError("oracle comparison is inconsistent")
        if oracle.outcome == candidate_outcome:
            raise AssertionError("a strict scalar improvement cannot have the candidate outcome")
        if oracle.outcome in outcome_to_pool:
            # Every restricted-master solution has non-negative value on all
            # pooled rows whenever the algorithm has not already terminated
            # negatively. Therefore a newly found negative cut must be new.
            raise AssertionError("oracle returned a previously generated violating outcome")

        pool_index = len(pool)
        outcome_to_pool[oracle.outcome] = pool_index
        pool.append(
            {
                "decision": deepcopy(oracle.decision),
                "outcome": oracle.outcome,
                "difference": difference,
            }
        )
        step["added_pool_index"] = pool_index
        step["added_difference"] = [int_string(value) for value in difference]
        step["pool_size_after"] = len(pool)

        master = primal_margin_exact([item["difference"] for item in pool])
        step["restricted_margin"] = rational_string(master.value)
        step["restricted_weights"] = [rational_string(value) for value in master.weights]

        if master.value < 0:
            dual = dual_margin_exact([item["difference"] for item in pool])
            if dual.value != master.value:
                raise AssertionError("exact primal and dual restricted-master values disagree")
            rows = [item["difference"] for item in pool]
            support, coefficients, coefficient_sum, coordinate_sums, strict_margin = (
                primitive_integer_certificate(rows, dual)
            )
            atoms = [
                {
                    "decision": deepcopy(pool[idx]["decision"]),
                    "decision_digest": _digest_label(sha256_hex(pool[idx]["decision"])),
                    "outcome": [int_string(value) for value in pool[idx]["outcome"]],
                    "coefficient": int_string(coefficient),
                }
                for idx, coefficient in zip(support, coefficients)
            ]
            atoms.sort(key=lambda atom: decision_sort_key(atom["decision"]))
            if len(atoms) > p:
                raise AssertionError("sparse dual extraction exceeded the objective dimension")

            step["termination"] = "negative_sparse_witness"
            step["dual_margin"] = rational_string(dual.value)
            step["certificate_support"] = len(atoms)
            iterations.append(step)
            trace = {
                "format": "pareto-support-generation-trace",
                "schema_version": SCHEMA_VERSION,
                "canonicalisation": CANONICALISATION,
                "result": "nonnegative_weight_unsupported",
                "iterations": iterations,
            }
            trace_digest = _digest_label(sha256(canonical_json_bytes(trace)).hexdigest())
            certificate = _base_certificate(instance, candidate_decision, candidate_outcome)
            certificate.update(
                {
                    "claim": "nonnegative_weight_unsupported",
                    "trust_level": "P1_FULLY_CHECKABLE",
                    "negative_payload": {
                        "atoms": atoms,
                        "coefficient_sum": int_string(coefficient_sum),
                        "coordinate_sums": [int_string(value) for value in coordinate_sums],
                        "strict_margin": rational_string(strict_margin),
                        "normalisation": "primitive-positive-integers-gcd-1",
                    },
                    "provenance": {
                        "generator": {"name": "pareto-support-proofs", "version": __version__},
                        "algorithm": "exact-exchange-v1",
                        "oracle_adapter": last_oracle_name,
                        "trace_digest": trace_digest,
                        "exact_arithmetic": "fractions.Fraction",
                        "deterministic": True,
                    },
                }
            )
            if context:
                certificate["provenance"]["context"] = deepcopy(context)
            return GenerationResult(seal_certificate(certificate), trace)

        iterations.append(step)
        weights = master.weights

    raise RuntimeError(f"exact exchange exceeded max_iterations={max_iterations}")
