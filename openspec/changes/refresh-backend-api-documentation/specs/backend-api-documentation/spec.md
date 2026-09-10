## Purpose

Keep the backend API documentation accurate, complete, and mechanically aligned
with the FastAPI application while distinguishing deployed and planned event
contracts.

## ADDED Requirements

### Requirement: The human guide inventories the complete public API

The canonical backend guide MUST list every route and HTTP method registered by
`api.main:app`, explain identity and envelope conventions, and provide enough
request and response detail to integrate without consulting obsolete files.

#### Scenario: A route is added or removed

- **WHEN** the FastAPI route registry changes
- **THEN** the documentation gate fails until the canonical endpoint inventory
  and generated OpenAPI artifacts are updated

### Requirement: OpenAPI artifacts are generated from one authority

The checked-in YAML contract and JSON test snapshot MUST be deterministic
serializations of `app.openapi()` and MUST be reproducible with one documented
command.

#### Scenario: A generated artifact drifts

- **WHEN** either checked-in OpenAPI artifact differs semantically or textually
  from the generator output
- **THEN** `scripts/export_openapi.py --check` or the documentation test fails

### Requirement: Streaming contracts are not conflated

The guide MUST separately describe legacy SSE, opt-in reliable SSE v1, and the
unpublished Research Experience v1 contracts. It MUST NOT claim that
`ResearchEvent v1` is emitted by the current search endpoint.

#### Scenario: A frontend developer selects a stream

- **WHEN** the developer reads the SSE section
- **THEN** they can determine the query parameter, feature prerequisite, event
  vocabulary, cursor behavior, and terminal events for the selected encoding

### Requirement: Documentation states security and compatibility limitations

The guide MUST identify the current headers as identity resolution rather than
authentication, explain that response errors are not universally enveloped,
and record implementation limitations that materially affect browser clients.

#### Scenario: An API is exposed outside a trusted environment

- **WHEN** an operator reviews the guide
- **THEN** they are warned that an authentication gateway is required and that
  provider credentials or raw account material must never enter public payloads
