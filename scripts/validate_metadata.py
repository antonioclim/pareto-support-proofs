#!/usr/bin/env python3
"""Validate synchronised public metadata without adding machine-specific data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import tomllib
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.6.1"
EXPECTED_TITLE = "Pareto Support Proofs: exact certificates and standalone verification"
EXPECTED_ORCID = "0000-0003-4745-0431"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate() -> dict[str, Any]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    citation = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    archive = load_json(ROOT / ".zenodo.json")
    codemeta = load_json(ROOT / "codemeta.json")
    version_file = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

    checks: dict[str, bool] = {}
    versions = {
        project["project"]["version"],
        str(citation["version"]),
        str(archive["version"]),
        str(codemeta["version"]),
        version_file,
    }
    checks["version_consistency"] = versions == {EXPECTED_VERSION}
    checks["title_consistency"] = citation["title"] == archive["title"] == EXPECTED_TITLE
    checks["package_name"] = project["project"]["name"] == "pareto-support-proofs"
    checks["resource_type"] = archive["upload_type"] == "software" and citation["type"] == "software"
    checks["source_licence"] = (
        project["project"]["license"] == "BSD-3-Clause"
        and citation["license"] == "BSD-3-Clause"
        and archive["license"] == "bsd-3-clause"
    )
    checks["orcid_consistency"] = (
        citation["authors"][0]["orcid"].endswith(EXPECTED_ORCID)
        and archive["creators"][0]["orcid"] == EXPECTED_ORCID
        and codemeta["author"][0]["identifier"].endswith(EXPECTED_ORCID)
    )
    checks["affiliation_consistency"] = (
        citation["authors"][0]["affiliation"]
        == archive["creators"][0]["affiliation"]
        == codemeta["author"][0]["affiliation"]["name"]
    )
    checks["release_identifier_not_embedded"] = "doi" not in citation and "doi" not in archive

    contact_pattern = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    metadata_paths = [
        ROOT / "pyproject.toml",
        ROOT / "CITATION.cff",
        ROOT / ".zenodo.json",
        ROOT / "codemeta.json",
        ROOT / "AUTHORS.md",
        ROOT / "NOTICE",
    ]
    checks["no_contact_address"] = all(
        contact_pattern.search(path.read_text(encoding="utf-8")) is None for path in metadata_paths
    )
    checks["dual_licence_notice"] = "CC BY 4.0" in (ROOT / "NOTICE").read_text(encoding="utf-8")
    checks["python_support"] = project["project"]["requires-python"] == ">=3.11"
    checks["pep639_licence_files"] = project["project"].get("license-files") == [
        "LICENSE", "LICENSE-DATA.md", "NOTICE", "AUTHORS.md"
    ]

    failures = sorted(name for name, passed in checks.items() if not passed)
    return {
        "schema": "pareto-support-metadata-validation-1.0",
        "version": EXPECTED_VERSION,
        "checks": checks,
        "failure_count": len(failures),
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "validation" / "metadata_summary.json")
    args = parser.parse_args()
    result = validate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
