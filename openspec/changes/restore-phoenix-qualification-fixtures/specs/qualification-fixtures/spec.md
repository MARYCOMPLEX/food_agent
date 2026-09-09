## Purpose

Provides reproducible, repository-owned qualification inputs for schema-state
probing and deterministic evaluation without exposing private or provider data.

## ADDED Requirements

### Requirement: Qualification artifacts are complete and versioned

The repository MUST contain one versioned schema-state fixture for each of
`clean`, `n-minus-1`, `current`, and `divergent`, four versioned milestone
evaluation datasets for `b1`, `b2`, `b3`, and `observability`, one manifest per
milestone, and an aggregate manifest referencing all of them.

#### Scenario: All referenced artifacts are available

- **WHEN** the qualification fixture tests resolve the declared paths
- **THEN** every path exists and parses as a JSON object with its declared
  version

### Requirement: Evaluation datasets are deterministic and redaction-safe

Each milestone dataset MUST validate as `evaluation/v1`, contain at least four
unique cases including a privacy or redaction case, and carry the digest
computed from its immutable cases. Inputs, expected values, and tags MUST NOT
contain credentials, private identity data, raw URLs, cookies, authorization
headers, or raw provider payloads.

#### Scenario: Dataset replay produces the same digest

- **WHEN** the same dataset is loaded and evaluated twice with the same actuals
  and configuration
- **THEN** the dataset digest and evaluation result digest are identical and
  every expected case passes

### Requirement: Schema fixtures fail closed on divergence

The schema-state fixtures MUST classify as clean, N-1, current, or divergent
according to the default schema authority signatures. A divergent fixture MUST
not be considered compatible and MUST raise the existing divergence error when
compatibility is required.

#### Scenario: Divergent state is rejected

- **WHEN** the schema probe reads the divergent fixture and compatibility is
  required
- **THEN** the probe reports `divergent` and raises `SchemaDivergentError`

### Requirement: Fixture JSON remains trackable without broadening data exposure

The repository MUST exempt only the qualification fixture subtree from the
global JSON ignore rule. Other generated JSON files MUST remain ignored by
default.

#### Scenario: Intended fixtures appear in version control

- **WHEN** a new JSON file is placed under the qualification fixture subtree
- **THEN** Git reports it as trackable while an unrelated generated JSON file
  remains ignored
