# Validation artefacts

The `validation/` directory contains concise machine-readable outputs generated from the public tree.

- `exact_falsification_summary.json` records deterministic theorem-level falsification counts.
- `study_summary.json` records the fixed computational study outcome.
- `corpus_replay.json` records schema validation and checker replay of retained objects.
- `test_summary.json` records the unit and integration test count.
- `metadata_summary.json` records cross-file version and licence consistency.
- `release_hygiene.json` records the public-tree scan.
- `checker_imports.json` records the standalone checker import boundary.
- `release_summary.json` combines the principal checks.
- `FILE_MANIFEST.sha256` binds every retained file except the manifest itself.

No raw package-manager transcript, absolute path, user name, host name or network endpoint is retained.
