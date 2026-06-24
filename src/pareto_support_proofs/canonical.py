"""Canonical JSON handling and exact scalar encodings.

The project deliberately uses a restricted JSON data model. Mathematical
integers are decimal strings and rationals are reduced ``numerator/denominator``
strings with a positive denominator. Canonical serialisation uses UTF-8,
lexicographically sorted ASCII property names and no insignificant whitespace.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
import math
import re
from typing import Any

INT_RE = re.compile(r"^(?:0|-?[1-9][0-9]*)$")
POS_INT_RE = re.compile(r"^[1-9][0-9]*$")
RAT_RE = re.compile(r"^(0|-?[1-9][0-9]*)/([1-9][0-9]*)$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class DuplicateKeyError(ValueError):
    """Raised when a JSON object contains duplicate member names."""


def _no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise DuplicateKeyError(f"duplicate JSON member: {key}")
        out[key] = value
    return out


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def load_json_strict(path: str) -> Any:
    with open(path, "rb") as handle:
        raw = handle.read()
    if len(raw) > 10_000_000:
        raise ValueError("JSON input exceeds the 10 MB safety limit")
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_no_duplicate_pairs,
        parse_constant=_reject_constant,
    )


def loads_json_strict(text: str) -> Any:
    return json.loads(
        text,
        object_pairs_hook=_no_duplicate_pairs,
        parse_constant=_reject_constant,
    )


def _validate_restricted_json(value: Any, path: str = "$") -> None:
    """Reject values whose cross-language canonical form is ambiguous.

    The profile permits null, booleans, integers, strings, arrays and objects.
    Binary floating-point values are forbidden. Mathematical numbers are
    already represented by canonical decimal or rational strings.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        raise ValueError(f"binary floating-point value is forbidden at {path}")
    if isinstance(value, list):
        for idx, item in enumerate(value):
            _validate_restricted_json(item, f"{path}[{idx}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"object key must be a string at {path}")
            _validate_restricted_json(item, f"{path}.{key}")
        return
    raise TypeError(f"unsupported JSON value at {path}: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialise the restricted data model deterministically.

    Object member names are ordered by Unicode code point. UTF-8 is used
    without insignificant whitespace. No Unicode normalisation is performed:
    identifiers are bound exactly as supplied.
    """
    _validate_restricted_json(value)
    text = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return text.encode("utf-8")


def dump_json_canonical(value: Any, path: str) -> None:
    with open(path, "wb") as handle:
        handle.write(canonical_json_bytes(value))
        handle.write(b"\n")


def sha256_hex(value: Any) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def parse_int_string(value: Any, *, positive: bool = False) -> int:
    if not isinstance(value, str):
        raise ValueError("integer must be encoded as a decimal string")
    pattern = POS_INT_RE if positive else INT_RE
    if not pattern.fullmatch(value):
        raise ValueError(f"non-canonical integer string: {value!r}")
    return int(value)


def int_string(value: int) -> str:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("integer required")
    return str(value)


def parse_rational_string(value: Any) -> Fraction:
    if not isinstance(value, str):
        raise ValueError("rational must be encoded as a string")
    match = RAT_RE.fullmatch(value)
    if not match:
        raise ValueError(f"non-canonical rational string: {value!r}")
    numerator = int(match.group(1))
    denominator = int(match.group(2))
    if math.gcd(abs(numerator), denominator) != 1:
        raise ValueError(f"rational is not reduced: {value!r}")
    return Fraction(numerator, denominator)


def rational_string(value: Fraction | int) -> str:
    q = value if isinstance(value, Fraction) else Fraction(value)
    return f"{q.numerator}/{q.denominator}"


def semantic_instance_view(instance: dict[str, Any]) -> dict[str, Any]:
    """Return the mathematical instance view covered by ``instance_digest``.

    Descriptive metadata is intentionally excluded. Arrays with semantically
    irrelevant order are sorted. Objective order, matrix order and variable
    order remain unchanged because they are part of the mathematical model.
    """
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
            problem["constraints"] = sorted(
                problem["constraints"], key=lambda item: canonical_json_bytes(item)
            )
    return view


def instance_digest(instance: dict[str, Any]) -> str:
    return sha256_hex(semantic_instance_view(instance))


def certificate_unsigned_view(certificate: dict[str, Any]) -> dict[str, Any]:
    view = deepcopy(certificate)
    view.pop("integrity", None)
    return view


def certificate_digest(certificate: dict[str, Any]) -> str:
    return sha256_hex(certificate_unsigned_view(certificate))


def seal_certificate(certificate: dict[str, Any]) -> dict[str, Any]:
    sealed = deepcopy(certificate)
    sealed.pop("integrity", None)
    sealed["integrity"] = {
        "algorithm": "sha256",
        "canonicalisation": "psp-json-c14n-1",
        "certificate_digest": f"sha256:{certificate_digest(sealed)}",
    }
    return sealed


def decision_sort_key(decision: Any) -> bytes:
    return canonical_json_bytes(decision)
