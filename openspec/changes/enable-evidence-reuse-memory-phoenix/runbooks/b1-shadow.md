# B1 Evidence Shadow Runbook

1. Apply the additive Alembic revision and run the clean/N-1 schema probes.
2. Start with `MODULAR_EVIDENCE_SHADOW_ENABLED=false` and verify legacy
   response digests.
3. Set a deterministic sample rate and finite write budget, then enable B1.
   Shadow writes return the legacy batch first and never advance a current
   Bundle pointer.
4. Inspect bounded counters for sampled, skipped, privacy-rejected,
   provenance-rejected, persisted, and failed outcomes.
5. Roll back by setting the flag to `false`; retain candidate history and
   verify legacy reads continue.
