## Purpose

Define the direct cutover boundary for removed provider and historical search
paths.

## ADDED Requirements

### Requirement: Gaode is absent from executable production code

The repository SHALL contain no executable Gaode service, POI adapter,
compatibility registration, environment setting, or import. Dianping MCP is the
only place enrichment source.

#### Scenario: Production dependency scan runs

- **WHEN** source imports and environment settings are scanned
- **THEN** no Gaode service, adapter, key, or compatibility binding is found

### Requirement: Historical search branches are absent from the active route

The active Agent composition SHALL not instantiate a four-phase search executor,
a recommendation-list follow-up handler, or a local XHS provider fallback.
There is one direct comment-first workflow.

#### Scenario: Composition root is built

- **WHEN** the application composition root resolves the food Agent
- **THEN** it resolves one comment-first workflow with XHS and Dianping source
  ports and no historical search branch
