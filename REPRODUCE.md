# Reproduction guide

## 1. Supported environment

- Python 3.11, 3.12 or 3.13
- no network access during execution after dependencies are installed
- standard-library-only generator and standalone checker
- pinned direct validation dependencies in `requirements-validation.txt`

## 2. Installation

### POSIX shells

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[validation]"
```

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[validation]"
```

## 3. Fast integrity validation

```bash
make validate
```

This command runs the unit suite, validates metadata, scans the release tree, validates every JSON object, checks the standalone import boundary and replays all retained certificates.

## 4. Exact mathematical falsification

```bash
make falsify
```

The retained deterministic summary is written to `validation/exact_falsification_summary.json`.

## 5. Reference objects

```bash
make examples
```

Each reference certificate and trace is generated twice. Canonical bytes must agree before the object is retained. Every object is then replayed by the standalone checker.

## 6. Complete computational study

```bash
make study
```

The command recreates the correctness corpus, scaling constructions, timing records, finite-grid counterexamples, atom-bound checks and semantic mutation tests. Existing `results/` and generated study figures are replaced.

## 7. Certificate-geometry figure

```bash
make figure
```

This recreates `figures/certificate_geometry.png` and `figures/certificate_geometry.eps`.

## 8. Complete rebuild

```bash
make reproduce
```

The complete rebuild regenerates examples, theorem falsification evidence, the computational study, figures and validation summaries in that order.

## 9. Interpretation

A successful replay establishes the encoded claim under the encoded mathematical model. P2 positive objects remain conditional. Timing measurements are descriptive for the recorded environment and are not portable performance guarantees.
