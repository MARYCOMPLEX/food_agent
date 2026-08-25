# Contract Catalog

This catalog is a review-facing projection of the installed Domain Pack
registry. `tests/test_architecture_docs_drift.py` reads the live manifests and
schema bundles and fails when this catalog, the architecture references, or the
compatibility ledger drift apart.

| Pack | Version | Contract API | Schema bundle | Final output schema |
|---|---|---|---|---|
| `food` | `1.0.0` | `domain-contract/v1` | `domain-contract-schema-bundle/v1` | `food-agent-final-output/v1` |
| `travel` | `1.0.0` | `domain-contract/v1` | `domain-contract-schema-bundle/v1` | `travel-agent-final-output/v1` |

The shared contract method set is the seven-method `DomainContract` API. Pack
versions are pinned at task admission and can be unregistered without deleting
shared PostgreSQL facts, Temporal history, Evidence/Bundle versions, or Redis
projections.
