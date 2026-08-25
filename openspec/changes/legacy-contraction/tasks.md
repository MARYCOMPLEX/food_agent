## 1. Evidence And Inventory

- [ ] 1.1 Export the current compatibility ledger and identify every legacy
  route, DTO, Python export, adapter, and configuration binding.
- [ ] 1.2 Attach consumer evidence for one complete release cycle and approve
  the removal owner and rollback command for each candidate.
- [ ] 1.3 Run clean/N-1 Alembic restore and Temporal history replay before any
  removal is activated.

## 2. Incremental Removal

- [ ] 2.1 Remove the first approved legacy path behind an independently
  reversible binding.
- [ ] 2.2 Run HTTP/SSE, domain, memory, failure, browser, and deployment gates
  and archive exact results.
- [ ] 2.3 Repeat for later paths only after the previous removal is stable; do
  not delete fields or data without an explicit follow-up decision.
