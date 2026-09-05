# B3 Memory and Personalization Runbook

1. Keep `MODULAR_PERSONALIZATION_CANARY_MODE=off` until B2 rollback rehearsal
   and the B3 isolation/authority gate pass.
2. In `shadow`, sample context and ranking comparisons while serving public
   ranking. Verify explicit hard constraints, session requirements, explicit
   preferences, and inferred preferences in that order.
3. Verify PostgreSQL commit before outbox projection, Redis rebuild from
   authority, and no cross-scope cache key access.
4. Canary serves only sampled personalized ranking. Public candidate facts and
   scores remain unchanged.
5. Roll back to `off`; stop warm-up, keep authority records, and use public
   ranking for new requests.
