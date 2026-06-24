# Mathematical contract

## Canonical image and candidate

All objectives are transformed to exact integer minimisation form. Let the finite feasible image be `Y subset Z^p` and let `y0 in Y` be the selected candidate outcome. For each challenger `y`, define `d(y)=y-y0`.

A non-negative weighted-sum support exists when a vector `lambda` in the unit simplex `Delta_p` satisfies

```text
lambda^T d(y) >= 0 for every y in Y.
```

Strictly positive support additionally requires `lambda_i>0` for every objective.

## Alternative certificate

Exactly one of the following systems is feasible.

1. `lambda in Delta_p` and `lambda^T d(y)>=0` for every challenger.
2. A finite family of challengers `y^1,...,y^k`, positive coefficients `a_1,...,a_k` and `k<=p` such that

   ```text
   sum_h a_h (y^h-y0) < 0
   ```

   componentwise.

The second object proves unsupportedness. For every `lambda in Delta_p`, the coefficient-weighted average of the stored scalar gaps is strictly negative. Therefore at least one stored challenger has a negative scalar gap.

The schema uses primitive positive integer coefficients. If `A=sum_h a_h` and `s_i=sum_h a_h(y^h_i-y0_i)`, the reported uniform margin is

```text
eta=min_i(-s_i)/A > 0.
```

The checker recomputes every quantity exactly.

## Restricted master and exchange loop

For a current cut pool `D={d^1,...,d^m}`, the generator solves

```text
max t
subject to lambda in Delta_p
           lambda^T d^j >= t for every pooled row.
```

It then calls an exact scalar oracle for `min_x lambda^T F(x)`.

- Equality with the candidate scalar value yields a positive object.
- A strict improvement contributes the concrete feasible decision and exact outcome to the pool.
- A negative restricted-master value yields a dual mixture, compressed to at most `p` positive atoms and converted to primitive integers.

Each strict oracle violation has an outcome not already present in the pool. The loop therefore terminates after at most the number of distinct feasible challenger outcomes plus one oracle call.

## Positive adapter obligations

### Explicit image

The checker enumerates all listed alternatives and recomputes the exact minimum with a deterministic canonical tie-break.

### Assignment

The proof supplies a feasible permutation and rational row and column potentials. The checker verifies every dual inequality, tightness on matched edges, equality of primal and dual values and exact reconstruction of the transformed scalar objective.

### Shortest path

The proof supplies a feasible simple source-to-target path and rational node potentials. The checker verifies source normalisation, every edge inequality, equality between target potential and path cost and exact reconstruction of the transformed scalar objective.

### Trusted oracle

A P2 proof supplies a feasible minimiser assertion and an exact representation of the scalar weights. The checker verifies internal consistency but does not solve the global scalar problem.

## Semantic exclusions

Unsupportedness is not a domination certificate. Non-negative weighted-sum support is not a Pareto-efficiency certificate when some weight is zero. Duplicate outcomes do not strengthen either side. The object concerns the transformed objective image bound by the instance digest.
