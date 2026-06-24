# Threat model and limitations

## Adversaries considered

The checker is designed to detect malformed JSON, duplicate members, stale or altered digests, infeasible decisions, altered objective vectors, invalid rational encodings, inconsistent redundant fields, non-strict negative mixtures, non-primitive coefficients, invalid assignment potentials, invalid shortest-path potentials and dishonest P1/P2 relabelling.

Controlled mutations are resealed where appropriate. Rejection must therefore follow from semantic checks rather than a stale self-hash alone.

## Trusted computing base

For a negative object, the trusted computing base is the Python interpreter, standalone checker and instance parser. The generator, master programme and weighted-sum oracle are not trusted after emission.

For a P1 positive object, the trusted computing base additionally includes the checker implementation of the relevant elementary optimality proof. No generator code or solver library is imported.

For a P2 positive object, global scalar optimality is trusted. The checker reports this limitation explicitly and a strict consumer may reject the object.

## Safety properties

The parser limits each JSON input to 10 MB. It rejects duplicate members and non-finite constants. The checker performs no network access, executes no data from the object and uses only Python standard-library modules.

## Non-goals

The software does not provide digital signatures, remote attestation, general solver proof-log adapters, interval arithmetic for measured data, proof compression for very large decisions or a hardened sandbox. It does not claim efficiency for large objective dimension.

## Epistemic limitation

Successful checking establishes the encoded claim under the encoded model. It cannot establish that the model faithfully represents a physical or institutional decision problem. It cannot convert supportability into Pareto efficiency without an additional dominance argument.
