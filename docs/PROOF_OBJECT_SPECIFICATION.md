# Pareto Support Proof Object Specification 1.0.0

This document is normative together with the JSON Schemas and the standalone checker.

## Exact encodings

- Integers are decimal strings matching `0|-?[1-9][0-9]*`.
- Positive integers exclude zero.
- Rationals are reduced strings `n/d` with `d>0`.
- Digests are `sha256:` followed by 64 lower-case hexadecimal digits.
- Mathematical floating-point values are forbidden.

## Canonicalisation

`psp-json-c14n-1` serialises the restricted JSON data model as UTF-8 with object names sorted by Unicode code point and no insignificant whitespace. It performs no Unicode normalisation. The generator and checker implement the profile independently.

The instance digest excludes the top-level `metadata` member. Explicit alternatives, shortest-path nodes and edges and binary constraints are ordered canonically. Objective order, variable order, matrix order and path direction remain semantic.

## Top-level certificate

Required fields are:

- `format`
- `schema_version`
- `canonicalisation`
- `instance_digest`
- `problem_type`
- `candidate`
- `claim`
- `trust_level`
- `provenance`
- `integrity`

Exactly one of `positive_payload` and `negative_payload` is present.

## Negative payload

`atoms` contains between one and `p` entries in strictly increasing canonical decision order. Every entry carries a feasible decision, its digest, its exact transformed outcome and a positive integer coefficient. Outcomes are distinct and differ from the candidate outcome.

The checker verifies decision digests, feasibility, objective re-evaluation, coefficient positivity, primitive normalisation, stored sums, strict componentwise negativity and the exact uniform margin.

A negative object is always `P1_FULLY_CHECKABLE`.

## Positive payload

The payload records exact simplex weights, their minimum component, the candidate scalar value, the reported scalar minimum and an adapter envelope.

Supported proof types are:

- `explicit_enumeration_v1`
- `assignment_primal_dual_v1`
- `shortest_path_potentials_v1`
- `trusted_scalar_optimum_assertion_v1`

The first three are P1 adapters. The fourth is a P2 adapter.

## Verification results

- `VERIFIED` means the complete claim was checked at P1.
- `VALIDATED_NOT_FULLY_VERIFIED` means a P2 object is internally consistent but global scalar optimality was not independently checked.
- `REJECTED` means that a structural, integrity, feasibility or mathematical check failed.

The command-line process returns `0`, `2` and `1` respectively.

## Versioning

A change to field meaning, canonicalisation, digest scope or acceptance conditions requires a schema-version or adapter-version increment. New optional adapters may be added only when older checkers reject rather than misinterpret them.
