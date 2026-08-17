# Learning Notes

## Mental Model

The system is a retrieval-and-ranking pipeline, not a single autonomous agent. LLMs structure the user request and classify comment semantics; deterministic Python code controls keyword expansion, deduplication, weighting, filtering, and persistence.

## Learn First

1. FastAPI route and background-task lifecycle.
2. `ConversationContext` and follow-up behavior.
3. `MCPToolRegistry` provider abstraction.
4. Comment preprocessing/scoring contract.
5. SSE event schema and frontend state mapping.
6. PostgreSQL schema/migration lifecycle.

## Glossary

| Term | Meaning |
|---|---|
| XHS | Xiaohongshu data source |
| MCP provider | Local protocol abstraction for search/note tools |
| POI | Map/place information from Amap |
| EventBus | Per-session SSE event log and fan-out backend |
| L1/L2 memory | Redis short-term cache / PostgreSQL durable storage |

## Important Inference

The advertised “wanghong filtering” is currently weaker than the design suggests: scoring initializes `positive_count`/`negative_count` but never increments them, while analyzer filtering depends on their comparison.
