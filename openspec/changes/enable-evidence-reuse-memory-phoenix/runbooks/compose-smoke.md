# Compose qualification matrix

The host-side matrix is scripts/qualification_compose_matrix.ps1. It uses
the isolated project food-agent-qualification, the release manifest plus
docker-compose.qualification.yml, and never prints .env values. The
qualification image is built from the current worktree unless -SkipBuild is
used.

## Commands

Run the business dependency matrix without the optional Phoenix pull:

    pwsh -NoProfile -File ./scripts/qualification_compose_matrix.ps1 -SkipPhoenix -KeepStack

Run the complete matrix with the already-built image when Docker Hub access is
the only unknown:

    pwsh -NoProfile -File ./scripts/qualification_compose_matrix.ps1 -SkipBuild -KeepStack

Use -ResetVolumes only for a clean-install migration rehearsal. Omit
-KeepStack when the isolated stack should be removed after the run.

## Matrix contract

The script records or asserts these independent observations:

| Area | Observation |
| --- | --- |
| Configuration | Default and Phoenix Compose configurations parse successfully. |
| Dependency order | PostgreSQL, Redis, Temporal, and MinIO become healthy before migration. |
| Schema | The migration container exits successfully at the current Alembic head. |
| Application | App container health, /health, and /metrics return HTTP 200. |
| Temporal queues | Research, refresh, and media queue smoke workers exit 0. |
| Restart recovery | App, PostgreSQL, Redis, and Temporal restart and become healthy again. |
| Profile isolation | Phoenix services are absent when the profile is disabled. |
| Phoenix profile | Phoenix and its isolated PostgreSQL are started and restarted when the image is available. |

One-shot migration and queue services are run separately from the long-lived
service wait. This prevents a normal Exited (0) smoke container from being
misclassified as a failed compose up --wait.

## Local result

The current worktree image xhs-food-agent:qualification passed the business
matrix on 2026-09-05:

- Compose configuration, image build, dependency health, migration, all three
  queue smoke workers, app health/metrics, and app/PostgreSQL/Redis/Temporal
  restart recovery: **PASS**.
- Phoenix services absent with the profile disabled: **PASS**.
- Phoenix profile startup and observability database restart: **BLOCKED** by
  Docker Hub layer download/network EOF while pulling the pinned image
  arizephoenix/phoenix@sha256:41489a3f4f04310545393d0000cd950f35fad71060bd676d937f0afad379e8f9.

The blocked Phoenix result is not an ingestion qualification. It leaves the
business stack usable and does not grant the Phoenix serving or release gate.
Repeat the second command when registry access is available and attach the
status-only output to the release record.
