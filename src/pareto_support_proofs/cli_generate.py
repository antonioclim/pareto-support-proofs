"""Command-line interface for deterministic certificate generation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .canonical import dump_json_canonical, load_json_strict
from .generator import generate_certificate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate an exact weighted-sum supportability proof object."
    )
    parser.add_argument("--instance", required=True, help="Instance JSON file")
    parser.add_argument("--candidate", required=True, help="Candidate decision JSON file")
    parser.add_argument("--certificate", required=True, help="Output certificate JSON file")
    parser.add_argument("--trace", help="Optional output generation trace JSON file")
    parser.add_argument("--max-iterations", type=int, default=10_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        instance = load_json_strict(args.instance)
        candidate = load_json_strict(args.candidate)
        result = generate_certificate(
            instance,
            candidate,
            max_iterations=args.max_iterations,
        )
        Path(args.certificate).parent.mkdir(parents=True, exist_ok=True)
        dump_json_canonical(result.certificate, args.certificate)
        if args.trace:
            Path(args.trace).parent.mkdir(parents=True, exist_ok=True)
            dump_json_canonical(result.trace, args.trace)
        summary = {
            "claim": result.certificate["claim"],
            "trust_level": result.certificate["trust_level"],
            "certificate_written": True,
            "trace_written": bool(args.trace),
        }
        print(json.dumps(summary, sort_keys=True))
        return 0
    except Exception as exc:  # CLI boundary
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
