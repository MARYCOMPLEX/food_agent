# ADR-0003: Runtime And Platform Support Matrix

- Status: Accepted
- Date: 2026-08-19
- Owners: Build, Release, QA

## Decision

The release-blocking runtime is CPython 3.12.x. The project metadata constrains Python to `>=3.12,<3.13`, `.python-version` selects the 3.12 line, and CI and release builds install only from the committed `uv.lock` with frozen resolution.

| Dimension | Blocking support | Non-blocking probe |
|---|---|---|
| OS and CPU | Current Ubuntu LTS x86_64 and current supported Windows x86_64 | Current supported macOS arm64 |
| Python | CPython 3.12.x | CPython 3.13 after lock, native dependency, contract, and container checks |
| Browser | Chromium desktop and mobile emulation | Firefox desktop; WebKit desktop and mobile emulation |
| Container | Non-root Linux/amd64 application image and the approved Compose target stack | Restart, rolling worker, and volume-ownership fault probes |
| Node compatibility | Node 20 present for the legacy signer and frontend build | Node absent, signer child failure, and Playwright browser absent |

Probe success records compatibility evidence only. It does not expand the production support matrix. A new blocking runtime, OS, CPU, or browser requires an explicit ADR/OpenSpec update and the same contract, failure, deployment, and rollback gates as the existing baseline.

## Required Gates

- Ubuntu and Windows run `uv lock --check`, `uv sync --frozen --extra dev --python 3.12`, and the same backend suites.
- Frontend installs with `npm ci` from the committed lockfile, then runs lint and build before browser suites.
- Release containers use Python 3.12, run as non-root, and do not create database schema at application startup.
- UTF-8 Chinese, UTC, and Asia/Shanghai are blocking locale/time inputs; other locale and DST combinations are probes.

## Consequences

- Python 3.10/3.11 are no longer accepted project runtimes.
- Python 3.13, macOS arm64, Firefox, and WebKit failures do not silently weaken a blocking gate or become production support claims.
- Task `14.1` owns the complete Ubuntu/Windows gate; task `14.2` owns probe reporting.
