# Phoenix OSS Runbook

Phoenix is optional. Start the application with OTel disabled to validate the
business path, then enable the isolated observability profile and the pinned
image from ADR-0001. Export is asynchronous and bounded; a Phoenix outage is
visible in health/drop metrics but does not fail requests or business commits.

To roll back, disable `MODULAR_OTEL_ENABLED` (and the optional Compose
profile), flush once within the configured deadline, and retain the
repository-owned evaluation fixtures/results. Never point the application at
the Phoenix database or copy raw account/session/prompt data into it.
