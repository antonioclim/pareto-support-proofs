#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src"

rm -rf results figures
mkdir -p results/partial figures validation

for p in 2 3 4; do
  python scripts/run_study_partition.py correctness --family explicit --p "$p"
done
for p in 2 3; do
  python scripts/run_study_partition.py correctness --family assignment --p "$p"
done
for seed in 2001 2002 2003 2004 2005; do
  python scripts/run_study_partition.py correctness --family assignment --p 4 --seed "$seed"
done
for family in shortest_path knapsack; do
  for p in 2 3 4; do
    python scripts/run_study_partition.py correctness --family "$family" --p "$p"
  done
done
python scripts/run_study_partition.py controlled
python scripts/run_study_partition.py reference

for n in 20 40 60; do
  python scripts/run_study_partition.py scaling-assignment --n "$n"
done
for length in 20 100; do
  python scripts/run_study_partition.py scaling-shortest --length "$length"
done
for p in 2 3 4; do
  python scripts/run_study_partition.py scaling-shortest --length 400 --p "$p"
done

for case_id in \
  timing_assignment_n40_p3_supportable \
  timing_assignment_n60_p4_supportable \
  timing_shortest_L400_p3_supportable \
  timing_shortest_L400_p3_unsupported \
  timing_shortest_L400_p4_unsupported \
  timing_tight_explicit_p4 \
  timing_narrow_interval_q1000000 \
  timing_binary_negative_p2; do
  python scripts/run_study_partition.py timing --case-id "$case_id"
done

python scripts/run_study_partition.py aggregate
rm -rf results/partial
