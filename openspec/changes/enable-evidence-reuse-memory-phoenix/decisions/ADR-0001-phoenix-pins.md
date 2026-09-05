# ADR-0001: Phoenix OSS and OTLP Pins

Status: accepted for this change's qualification deployment

## Decision

Use Phoenix OSS as an optional consumer behind the project-owned observation
and evaluation ports. The first image is pinned by a multi-architecture OCI
manifest digest rather than a mutable tag:

```text
arizephoenix/phoenix@sha256:41489a3f4f04310545393d0000cd950f35fad71060bd676d937f0afad379e8f9
```

The digest corresponds to the `version-20.8.0` tag observed from the Docker
Hub registry on 2026-09-05. The registry response reported
`media_type=application/vnd.oci.image.index.v1+json`, with the amd64 image at
`sha256:378e8150b44fdf7d401b156092dc46a8e1f199c906fe2182dbca798d36077400`
and the arm64 image at
`sha256:b899655ed60ba69fcbbe470963b673b2635ee5e7ede6ea7085eeef2645348647`.
The release job must re-check the manifest digest with the registry before
deployment and fail if it differs from this record.

## Transport and API

* Traces use OTLP over HTTP/JSON at `POST /v1/traces` on the Phoenix OTLP
  endpoint. The application owns no Phoenix database connection.
* Evaluation projection uses the versioned Phoenix HTTP gateway contract at
  `/v1/datasets` and `/v1/experiments`. The adapter sends the configured
  `phoenix_api_version` header and maps unsupported versions to `blocked`/
  unhealthy without entering a business request.
* Health probing uses `GET /healthz` with a bounded timeout. Health is exposed
  through the existing Prometheus surface and is never a prerequisite for
  business health.
* Local Compose uses HTTP on the private network. Non-local deployments must
  terminate TLS at the gateway and use a bearer `TOKEN` reference; raw tokens
  and database credentials are never stored in application settings.

## Storage isolation and retention

Phoenix uses a separate PostgreSQL service/database, role, credentials, named
volume, and network identity (`phoenix-observability`) from the business
PostgreSQL instance. The initial retention fixture is 30 days and is an
operational setting, not a business-data retention rule. Backups and deletion
must be scoped to the observability database.

## Replacement and rollback

An OTel Collector may be inserted later without changing domain contracts.
Disabling `MODULAR_OTEL_ENABLED` or the optional Compose profile selects the
no-op/in-memory adapter. Rollback does not delete Evidence, Bundles, Memory,
Temporal history, or repository-owned evaluation fixtures.

## Evidence commands

```powershell
Invoke-RestMethod 'https://hub.docker.com/v2/repositories/arizephoenix/phoenix/tags?page_size=100'
docker buildx imagetools inspect arizephoenix/phoenix@sha256:41489a3f4f04310545393d0000cd950f35fad71060bd676d937f0afad379e8f9
```
