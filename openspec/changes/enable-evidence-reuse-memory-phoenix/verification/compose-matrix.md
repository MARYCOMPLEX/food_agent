# Compose Matrix Evidence

The host-side runner is scripts/qualification_compose_matrix.ps1. It runs
against the isolated food-agent-qualification project and discards captured
Compose output after credential-like values are redacted.

## Commands

Business stack:

    pwsh -NoProfile -File ./scripts/qualification_compose_matrix.ps1 -SkipPhoenix -KeepStack

Phoenix retry using the already-built qualification image:

    pwsh -NoProfile -File ./scripts/qualification_compose_matrix.ps1 -SkipBuild -KeepStack

## Observed results

Run date: 2026-09-05.

| Scenario | Result |
| --- | --- |
| Default and Phoenix Compose config | PASS |
| Qualification image build | PASS |
| PostgreSQL, Redis, Temporal, MinIO health | PASS |
| Alembic migration | PASS |
| Research, refresh, and media queue smoke | PASS |
| App health and metrics | PASS, HTTP 200 |
| App restart | PASS |
| PostgreSQL restart and app recovery | PASS |
| Redis restart | PASS |
| Temporal restart and research queue recovery | PASS |
| Phoenix profile absent when disabled | PASS |
| Phoenix profile startup and isolated database restart | BLOCKED |

The Phoenix retry reached the pinned image pull but Docker Hub returned a
layer-download/network EOF. No Phoenix ingestion or evaluation success is
claimed. The business profile remained healthy and its restart/queue checks
passed. Repeat the Phoenix command when registry access is available.

The qualification overlay resolves the observability network to
food-agent-qualification-phoenix-observability, separate from the release
network food-agent-release-phoenix-observability. The Compose config check
confirmed this override.

## Interpretation

This matrix satisfies local Compose smoke evidence for the business profile.
The optional Phoenix row is an infrastructure availability observation, not a
serving approval. B1, B2, and B3 owner gates remain blocked independently of
this local matrix.
