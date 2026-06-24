# Computational study

## Design

Random-instance candidates are selected by an epsilon-constraint rule and by SHA-256 ordering before supportability classification. Controlled candidates are fixed algebraically. Finite weight grids are not used as ground truth.

The independent baseline enumerates the complete feasible image for small cases, removes duplicate dominated outcomes and enumerates vertices of the exact rational support polytope. In two objectives it also derives the exact feasible weight interval analytically. The baseline shares neither the exchange algorithm nor certificate extraction code.

## Corpus

The correctness corpus contains 190 cases: 90 explicit-image cases, 30 assignment cases, 30 shortest-path cases, 24 knapsack cases, seven controlled cases and nine reference regressions. Objective dimensions range from two to five.

The scaling corpus contains nine assignment cases and 18 shortest-path cases. The latter encode `2^20`, `2^100` and `2^400` dominated background paths together with controlled supportable or unsupported routes.

## Retained results

The generator agrees with independent exact classification in all 190 correctness cases. The class composition is 100 strictly positively supportable cases, 17 efficient unsupported cases and 73 dominated cases. The corpus contains 178 P1 and 12 P2 correctness cases.

There are 89 negative correctness objects and nine negative scaling objects. No negative object exceeds the objective dimension. Controlled exchange runs attain exactly `p` atoms for `p=2,...,5`. Direct subset checks verify necessity of all `p` constructed rows through `p=8`.

Each declared finite grid has exact false negatives on non-empty support intervals. All 24 independently resealed semantic mutations are rejected. The checker import check finds no non-standard-library dependency.

## Interpretation

The retained evidence supports exact agreement on the fixed corpus, sparse replayable negative objects, sharpness of the `p`-atom bound and incompleteness of fixed finite weight grids. It does not establish prevalence, production-scale superiority or completeness beyond weighted sums.
