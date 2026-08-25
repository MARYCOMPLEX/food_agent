## ADDED Requirements

### Requirement: Contraction is evidence gated

The system SHALL reject a legacy removal plan when the release-cycle consumer
inventory, restore rehearsal, or replacement contract evidence is incomplete.

#### Scenario: Missing consumer evidence

- **WHEN** a legacy path has an unresolved supported consumer
- **THEN** the path remains available and the contraction milestone stays open

#### Scenario: Restore rehearsal fails

- **WHEN** a clean/N-1 restore or Temporal replay fails
- **THEN** no legacy path is removed and the rollback plan remains unchanged

### Requirement: Each removal is independently reversible

Every contraction milestone SHALL have a single binding, focused tests, an
exact rollback command, and no destructive data migration.

#### Scenario: Removal regression

- **WHEN** a contract, failure, browser, or restore gate regresses
- **THEN** the milestone is reverted without deleting PostgreSQL facts,
  Temporal history, or immutable Evidence/Bundle versions
