from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def load_checker():
    path = ROOT / "checker" / "verify_certificate.py"
    spec = importlib.util.spec_from_file_location("standalone_pareto_checker", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load standalone checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = load_checker()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def example(stem: str, kind: str):
    folders = {
        "instance": "instances",
        "candidate": "candidates",
        "certificate": "certificates",
        "trace": "traces",
    }
    suffix = {
        "instance": ".json",
        "candidate": "_candidate.json",
        "certificate": "_certificate.json",
        "trace": "_trace.json",
    }
    return load_json(ROOT / "examples" / folders[kind] / f"{stem}{suffix[kind]}")


def reseal(certificate: dict) -> dict:
    out = deepcopy(certificate)
    out.pop("integrity", None)
    out["integrity"] = {
        "algorithm": "sha256",
        "canonicalisation": "psp-json-c14n-1",
        "certificate_digest": CHECKER.certificate_digest(out),
    }
    return out


def recompute_negative_payload(instance: dict, certificate: dict) -> dict:
    out = deepcopy(certificate)
    transforms = CHECKER.validate_instance(instance)
    candidate = CHECKER.evaluate_decision(instance, out["candidate"]["decision"], transforms)
    coeffs = []
    diffs = []
    for atom in out["negative_payload"]["atoms"]:
        coeff = int(atom["coefficient"])
        outcome = CHECKER.evaluate_decision(instance, atom["decision"], transforms)
        atom["outcome"] = [str(v) for v in outcome]
        atom["decision_digest"] = CHECKER.digest_label(atom["decision"])
        coeffs.append(coeff)
        diffs.append(tuple(v - b for v, b in zip(outcome, candidate)))
    q = sum(coeffs)
    sums = [sum(coeffs[h] * diffs[h][i] for h in range(len(coeffs))) for i in range(len(candidate))]
    out["negative_payload"]["coefficient_sum"] = str(q)
    out["negative_payload"]["coordinate_sums"] = [str(v) for v in sums]
    if q > 0 and all(v < 0 for v in sums):
        eta = Fraction(min(-v for v in sums), q)
        out["negative_payload"]["strict_margin"] = f"{eta.numerator}/{eta.denominator}"
    else:
        out["negative_payload"]["strict_margin"] = "1/1"
    return reseal(out)
