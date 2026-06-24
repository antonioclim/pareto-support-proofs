#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src"

python scripts/regenerate_examples.py
python scripts/run_exact_falsification.py
bash scripts/run_study_all.sh
python scripts/make_figure.py --output-dir figures
python scripts/run_release_validation.py
