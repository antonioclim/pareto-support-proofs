# Exact certifying exchange algorithm

## Scope

The algorithm classifies one feasible candidate with respect to scalarisation by a non-negative weighted sum. It does not, by itself, certify Pareto efficiency. All objectives are transformed to a common minimisation convention before computation.

Let `x0` be the candidate, `y0=F(x0)` and `p` the objective dimension. For every challenger outcome `y`, write `d=y-y0`. A positive object is a rational vector `lambda` in the unit simplex satisfying `lambda^T d>=0` for every feasible challenger. A negative object is a positive combination of challenger differences whose coordinate sum is strictly negative.

## Algorithm

1. Start from the simplex barycentre.
2. Call an exact weighted-sum oracle at the current rational weight.
3. If the oracle optimum equals the candidate scalar value, emit a positive object containing the weight and adapter proof.
4. Otherwise retain the returned feasible decision, exact outcome and candidate difference.
5. Solve the restricted max-min master problem on all retained differences.
6. If the restricted margin is negative, solve its exact dual, select a margin-optimal basic solution with at most `p` positive atoms and convert the coefficients into primitive positive integers.
7. If the restricted margin is non-negative, use an exact master maximiser as the next weight and return to Step 2.

Decisions and outcomes are stored rather than anonymous cuts. A third party can therefore re-evaluate every atom against the original instance.

## Finite termination and correctness

Assume that the feasible image is finite and every oracle call returns a globally optimal feasible decision for the supplied exact rational weight.

The exchange algorithm terminates after at most `|F(X) \ {y0}|+1` oracle calls. Positive termination returns a valid support weight. Negative termination returns an integer witness excluding every non-negative support weight.

A newly returned strict oracle violation cannot duplicate a pooled outcome because the current restricted-master solution is non-negative on every pooled row. A negative master value yields the alternative-system witness. A non-negative master value yields a new exact weight. Finiteness completes the termination argument.

## Complexity qualifications

The oracle-call bound can be proportional to the number of distinct outcomes and is not strongly polynomial. The reference master uses exact vertex enumeration. It is intended for proof production and falsification rather than large-dimensional numerical performance.
