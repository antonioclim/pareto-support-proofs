# Pareto Support Proofs

Pareto Support Proofs provides exact proof objects for deciding whether a selected feasible outcome is supportable by a non-negative weighted sum in a finite multi-objective optimisation problem. The repository contains a deterministic generator, a standalone generator-independent checker, machine-readable schemas, reference objects and a retained computational study.

## Mathematical scope

For a candidate outcome `y0` and challenger differences `d(y)=y-y0`, supportability asks whether a simplex weight `lambda` satisfies

```text
lambda^T d(y) >= 0 for every feasible challenger y.
```

The generator returns exactly one of the following objects.

- A positive object containing an exact weight and adapter-specific scalar-optimality evidence. P1 adapters provide a locally checkable proof while P2 objects retain a declared trusted-oracle assumption.
- A negative object containing at most `p` feasible challengers and primitive positive integer coefficients whose weighted coordinate sum is strictly negative.

Unsupportedness is not a domination statement. Support by a non-negative weight is not, by itself, a Pareto-efficiency proof when some weight is zero.

## Trust levels

`P1_FULLY_CHECKABLE` means the complete claim is replayed by the standalone checker using exact arithmetic and adapter-specific elementary conditions.

`P2_TRUSTED_ORACLE` means feasibility and internal consistency are checked but global scalar optimality remains an explicit external assumption. A strict consumer may reject P2 objects.

## Quick start

```bash
python -m venv .venv
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[validation]"
make validate
```

The generator and standalone checker use only the Python standard library. The optional validation dependencies are required for JSON Schema checks, retained figures and metadata parsing.

Generate a certificate:

```bash
pareto-support-generate \
  --instance examples/instances/explicit_tight_negative_p3.json \
  --candidate examples/candidates/explicit_tight_negative_p3_candidate.json \
  --certificate certificate.json \
  --trace trace.json
```

Verify it independently:

```bash
python checker/verify_certificate.py \
  --instance examples/instances/explicit_tight_negative_p3.json \
  --certificate certificate.json
```

## Reproduction commands

```bash
make examples   # regenerate the nine canonical reference objects
make test       # run unit and integration tests
make falsify    # run the exact theorem falsification suite
make study      # recreate the complete retained computational study
make figure     # regenerate the certificate-geometry figure
make validate   # replay the retained corpus and check release integrity
```

The complete study contains timing measurements and can take substantially longer than the remaining commands. Detailed instructions are in `REPRODUCE.md`.

## Repository structure

- `src/pareto_support_proofs/` — exact generator, master programmes and oracle adapters
- `checker/verify_certificate.py` — standalone standard-library checker
- `schemas/` — instance, certificate and trace schemas
- `examples/` — compact canonical examples and checker reports
- `protocol/` — fixed computational study specification
- `results/` — retained case-level evidence
- `validation/` — concise machine-readable validation summaries and file manifest
- `scripts/` — deterministic reproduction and validation commands
- `tests/` — exact, adversarial and integrity tests
- `figures/` — generated scientific figures

## Citation

Citation metadata are supplied in `CITATION.cff`, `.zenodo.json` and `codemeta.json`. The release DOI should be taken from the archival record rather than inserted retrospectively into the source archive.

## Licences

Source code is licensed under BSD-3-Clause. Retained instances, proof objects, generated results, figures and prose documentation are licensed under CC BY 4.0. See `LICENSE` and `LICENSE-DATA.md`.
