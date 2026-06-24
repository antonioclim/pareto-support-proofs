#!/usr/bin/env python3
"""Check a source tree for private contact data and packaging debris."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import struct
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
}
FORBIDDEN_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".tmp",
    ".bak",
    ".swp",
    ".swo",
    ".orig",
    ".rej",
}
FORBIDDEN_NAMES = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}
FORBIDDEN_DIRECTORY_SUFFIXES = {".egg-info"}
NESTED_ARCHIVE_SUFFIXES = {".zip", ".whl", ".tar", ".tgz", ".gz", ".bz2", ".xz", ".7z"}

CONTACT_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
TOKEN_PATTERNS = [
    re.compile(r"gh[psoru]_[A-Za-z0-9_]{30,}"),
    re.compile(r"AKIA[A-Z0-9]{16}"),
]


def iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRECTORIES for part in path.parts):
            continue
        if path.is_file():
            yield path


def png_text_chunks(data: bytes) -> list[str]:
    """Return the names of textual PNG chunks without decoding image data."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return []
    found: list[str] = []
    offset = 8
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            return ["truncated"]
        if chunk_type in {b"tEXt", b"zTXt", b"iTXt", b"tIME", b"eXIf"}:
            found.append(chunk_type.decode("ascii"))
        offset = end
        if chunk_type == b"IEND":
            break
    return found


def scan(root: Path = ROOT) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    files_scanned = 0
    bytes_scanned = 0

    for directory in sorted(path for path in root.rglob("*") if path.is_dir()):
        name = directory.name
        if name in SKIP_DIRECTORIES or any(name.endswith(suffix) for suffix in FORBIDDEN_DIRECTORY_SUFFIXES):
            findings.append(
                {
                    "path": directory.relative_to(root).as_posix(),
                    "category": "packaging_debris",
                    "detail": name,
                }
            )

    for path in iter_files(root):
        relative = path.relative_to(root).as_posix()
        files_scanned += 1
        data = path.read_bytes()
        bytes_scanned += len(data)

        suffix = path.suffix.lower()
        if path.name in FORBIDDEN_NAMES or suffix in FORBIDDEN_SUFFIXES:
            findings.append({"path": relative, "category": "packaging_debris", "detail": path.name})
        if suffix in NESTED_ARCHIVE_SUFFIXES:
            findings.append({"path": relative, "category": "nested_archive", "detail": suffix})

        if suffix == ".png":
            for chunk in png_text_chunks(data):
                findings.append({"path": relative, "category": "image_metadata", "detail": chunk})
        elif suffix == ".eps":
            header = data[:8192].decode("latin-1", errors="ignore")
            for marker in ("%%Creator:", "%%CreationDate:", "%%For:"):
                if marker in header:
                    findings.append({"path": relative, "category": "image_metadata", "detail": marker})

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue

        if CONTACT_PATTERN.search(text):
            findings.append({"path": relative, "category": "contact_address", "detail": "address-like string"})
        if PRIVATE_KEY_PATTERN.search(text):
            findings.append({"path": relative, "category": "private_key", "detail": "private-key header"})
        for pattern in TOKEN_PATTERNS:
            if pattern.search(text):
                findings.append({"path": relative, "category": "access_token", "detail": "token-like string"})

    unique = sorted(
        {json.dumps(item, sort_keys=True): item for item in findings}.values(),
        key=lambda item: (item["path"], item["category"], item["detail"]),
    )
    return {
        "schema": "pareto-support-release-hygiene-1.1",
        "files_scanned": files_scanned,
        "bytes_scanned": bytes_scanned,
        "finding_count": len(unique),
        "findings": unique,
        "status": "PASS" if not unique else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "validation" / "release_hygiene.json")
    args = parser.parse_args()
    result = scan(args.root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
