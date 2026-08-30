# Architecture Reference Manifest

These files are versioned historical inputs for `define-modular-architecture`. They are non-normative and do not override capability specs, accepted ADRs, or `design.md`.

| File | SHA-256 | Known superseded content |
|---|---|---|
| [food-agent-unified-architecture.html](./food-agent-unified-architecture.html) | `0E122CF6D7F45344FAAF45AEC084E384463C94EBBAC36328DAE0D866A1E8C198` | OpenAI Agents SDK; Redis/Queue lock and job-state labels |
| [food-agent-runtime-architecture.html](./food-agent-runtime-architecture.html) | `A067EFFA39DE6AE4816D8B3E8A2C9D4AE69E3A8E8E901F79DF2C46C38615CA1E` | Current code-aligned SVG/HTML view: FastAPI, Pydantic AI V2, Temporal queues, PostgreSQL, Redis hot state, S3/MinIO, and release evidence boundary |
| [food-agent-extensible-evidence-architecture.drawio](./food-agent-extensible-evidence-architecture.drawio) | `70BA87D7EA63E55EC0AF22C47E4BC647751CF5DECE7CEBD22B81A63B3091CBC6` | OpenAI Agents SDK; ARQ; Redis locks, retry, and job-state labels |

The accepted replacements are Pydantic AI V2, Temporal, and Redis-only rebuildable hot state as defined in [ADR-0002](../decisions/ADR-0002-infrastructure-baseline.md). Task `14.16` owns updating the visual content and enforcing diagram/contract drift checks.
