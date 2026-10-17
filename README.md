# Pareto Support Proofs — generator 0.6.2

Exact proof objects for non-negative weighted-sum supportability and unsupportedness in finite multi-objective optimisation. The current generator corrects shortest-path reconstruction on zero-cost cycles by retaining the predecessor when an equal-distance relaxation occurs. Costs and weight coordinates equal to zero remain allowed.

The standalone checker is unchanged and continues to report **0.6.1**; the schema remains **1.0.0**. Source code uses the Python standard library. The source tests and metadata checks additionally use the small dependency stack in `requirements-ci.txt`.

## Check an existing exact object

From the repository root, with Python3.11 or later:

```bash
python -I -S checker/verify_certificate.py --instance examples/instances/explicit_tight_negative_p3.json --certificate examples/certificates/explicit_tight_negative_p3_certificate.json --require-p1
```

This is a read-only check of a retained historical object. A P1 object contains locally checkable evidence for the complete encoded claim. A positive P2 object retains an explicit trusted-oracle assumption; `--require-p1` rejects it. Replaying or enumerating a case does not promote the retained object to P1.

## Generate a new object

Install the local package, choose a new output-directory name and run:

```bash
python -m pip install -e .
python -m pareto_support_proofs.cli_generate --instance examples/instances/explicit_tight_negative_p3.json --candidate examples/candidates/explicit_tight_negative_p3_candidate.json --certificate local-output-01/certificate.json --trace local-output-01/trace.json
python -I -S checker/verify_certificate.py --instance examples/instances/explicit_tight_negative_p3.json --certificate local-output-01/certificate.json --require-p1
```

The generator writes the named output files. Use a fresh directory for each experiment; retained `examples/`, `results/` and `validation/` are historical evidence.

## Run the lightweight current-source checks

```bash
python -m pip install -r requirements-ci.txt
python -B scripts/check_current_release.py
python -B -m unittest discover -s tests -v
```

The validator checks synchronised version/licence metadata, pinned source bytes, Python syntax, the 37-test inventory and retained-object provenance counts. The separate unittest command runs the **37 functional tests**, including the nine zero-cycle regressions. These commands do not regenerate the computational study or rerun its timing campaign. `scripts/validate_metadata.py` is a compatibility entry point for the same current validator and has no default report-file write.

The GitHub workflow is manual-only and runs one Ubuntu/Python3.12 job. A source preparation or local test result is distinct from a completed GitHub Actions run. Consult the Actions history for the actual run outcome.

## Scientific bundle and retained evidence

The complete journal companion is the **OPTL-R1-20261017** distribution. Its [R1 release page](https://github.com/antonioclim/pareto-support-proofs/releases/tag/optl-r1-20261017) is the intended publication location for four assets: `ESM_1_Pareto_Support_Proofs_R1.zip`, `Fig1_Editable_Sources_R1.zip`, `PUBLIC_RELEASE_CONTEXT.md` and `SHA256SUMS.txt`. The platform record determines whether publication has occurred. The ESM contains both complete engine trees, the create-only AC3 reproduction wrapper, repaired-run evidence, scientific protocols and historical documentation. Follow its current `README_R1.txt` and `GUIDE_R1.md` for full reproduction.

| Identity | Meaning |
|---|---|
| Current root generator/package | 0.6.2 |
| Unchanged standalone checker | 0.6.1 |
| Root `examples/`, `results/`, `protocol/`, `validation/` | Retained 0.6.1 evidence; not newly generated 0.6.2 results |
| Complete companion distribution | OPTL-R1-20261017; reproduction layer AC3-candidate.1 |
| Repaired scientific run within the ESM | AC3_REPAIRED_20261017_01 |
| Historical run within the ESM | R1_01 |

The retained root corpus contains **225 objects: 213 P1 and 12 conditional P2**. New AC3 evidence is stored separately in the ESM, and the historical timing batch remains separate from the three repaired shortest-path timing cases. The old computational scripts, Makefile study/reproduction targets and `REPRODUCE.md` remain historical workflow records; the default current-source checks are the commands above. Full scientific reproduction uses the ESM wrapper and a new run identifier, rather than replacing the retained root corpus.

`CURRENT_SOURCE_MANIFEST.json` pins canonical current source and retained evidence. It also identifies the small operational documentation/CI-validator overlays. Its hashes provide transfer/concordance checks, not a signature or an independent mathematical proof. The canonical engine source and original historical scripts remain byte-preserved inside the ESM and in Git history.

## Citation, publication state and licences

The copied engine metadata records its frozen prepublication preparation state and therefore contains no invented new DOI or release date. Actual GitHub and Zenodo records identify later publication events. The DOI [10.5281/zenodo.20832039](https://doi.org/10.5281/zenodo.20832039) identifies the **historical 0.6.1** release; it is not a new 0.6.2 or OPTL-R1-20261017 version DOI. The concept DOI is [10.5281/zenodo.20832038](https://doi.org/10.5281/zenodo.20832038).

Source code is licensed under BSD-3-Clause. Data, proof objects, figures and documentation are licensed under CC BY4.0; see `LICENSE`, `LICENSE-DATA.md` and `NOTICE`. New source and documentation work received ChatGPT and Codex assistance. Scientific responsibility and final author approval remain with Antonio Clim. These checks do not imply independent human verification or editorial acceptance.
