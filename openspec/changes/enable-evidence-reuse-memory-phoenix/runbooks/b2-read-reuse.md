# B2 Query Family Runbook

1. Keep `MODULAR_QUERY_REUSE_READ_MODE=off` until the B1 gate is approved.
2. Run `shadow` with a positive sample rate and compare public legacy/candidate
   digests. Confirm one refresh identity per Family/scope/policy.
3. Exercise CAS conflict and stale fallback before selecting `canary`.
4. Canary is sampled and contract-compatible; it does not change private or
   session fields in the digest.
5. Roll back with `MODULAR_QUERY_REUSE_READ_MODE=off`; the legacy reader is
   immediately selected and immutable Family/Bundle history remains.
