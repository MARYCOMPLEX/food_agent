## OpenSpec

- [x] Create the comment-first cutover proposal, design, and executable specs.
- [x] Validate this change with `openspec validate comment-first-agent-cutover --strict --no-interactive`.

## Agent and source boundaries

- [x] Add typed research contracts and source/profile ports.
- [x] Implement the XHS comment-first collector and Dianping structured enricher.
- [x] Replace the old orchestrator route with the injected research Agent.
- [x] Remove follow-up branching, four-phase executor, and Gaode dependency graph.

## Persistence and evidence

- [x] Add durable structured profile fields and idempotent repository mapping.
- [x] Preserve raw payloads, completeness, and explicit enrichment gaps.
- [x] Keep comment evidence on the existing evidence lifecycle.

## Verification

- [x] Add focused unit tests for contracts, source mapping, partial failures,
      conversation turns, and profile persistence.
- [x] Run static checks and the non-live test suite.
- [x] Configure and smoke-test the supplied OpenAI-compatible endpoint without
      committing credentials.
- [x] Commit the completed cutover.
