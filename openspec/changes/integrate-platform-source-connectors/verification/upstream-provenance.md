# Platform Connector Intake: Upstream Provenance And License Gate

Status: **intake recorded; production activation blocked pending owner/legal
approval**

Recorded: 2026-08-31 (Asia/Shanghai)

This record identifies the exact upstream snapshots used for local adapter
qualification.  It is not a grant of rights to redistribute or operate either
project.  No upstream server, worker, database, credential, QR payload, or raw
response is copied into the application repository.

## Snapshot provenance

| Provider | Source URL | Commit | Commit time | Reproducible archive SHA-256 |
|---|---|---|---|---|
| Dianping protocol engine | <https://github.com/MARYCOMPLEX/dazhongdianping.git> | `ffbc1d413ed1c83602212bc1fec12b57cd2b423d` | 2026-08-19T12:30:40+08:00 | `b535f193e1b82d87541f8604613e92956b85a2b2911d89e3c7efe475806e4f88` |
| Spider_XHS | <https://github.com/cv-cat/Spider_XHS.git> | `e1888d712519040f5fcc294baeac4b9505b25c98` | 2026-08-18T23:00:50+08:00 | `472df6713016dfd4c4999ae58a84c625abb7ffc4dba51b71ddd6604344d52ebe` |

The archive digest is calculated with `git archive --format=tar HEAD` at the
recorded commit and SHA-256 hashing the resulting bytes.  Re-fetching a
different commit, changing archive format, or changing the dependency files
requires a new intake record and connector version.

## Dependency manifest digests

| Provider | Manifest | SHA-256 |
|---|---|---|
| Dianping | `pyproject.toml` | `c9e09a0c05189d0f312dac084820f9663c49e749a796506d7e10404a38d9f046` |
| Spider_XHS | `requirements.txt` | `7e0b00e1e38ab5a1599d1d00f097b3bec46ff834a8111fb5c298081c90c4b773` |
| Spider_XHS | `package.json` | `d453db039b224e88b0b9250642bdca30479a582c9dfbadfdf176e58a906d640b` |
| Spider_XHS | `package-lock.json` | `99016bc2c76f1b0d5197581626711ffcb327860b21b2a1b85511579aadab1cc6` |

The core lockfile remains the authority for this repository.  Upstream
manifests are evidence only; dependencies are admitted only after a separate
security and compatibility review.

## Reusable surface and exclusions

The adapter may consume only the protocol/auth modules listed in
`references/provider-import-allowlist.yaml`.  The following are explicitly
excluded from the application runtime:

- Dianping's FastAPI application, SQLite account/task tables, risk manager,
  CLI, and standalone worker.
- Spider_XHS's CLI/data writer (`Data_Spider`), Excel/media writers, global
  `.env` session, and Creator publishing/upload APIs.
- Any upstream retry queue, scheduler, broker, or process-global mutable
  client/profile.

## License and activation gate

Neither checkout contains a tracked `LICENSE` file at the recorded commit.
Spider_XHS README carries an MIT badge that links to the absent file and also
states that the project is for learning/communication and forbids commercial
use.  A badge is not treated as a legal grant.  Dianping has no machine-
readable license declaration in its checkout either.

Accordingly, `license_status` is `unknown` for both providers.  The
Composition Root MUST keep both bindings disabled for production or
commercial traffic until an owner/legal approval record identifies the
permitted use, attribution/notice obligations, and a reviewed dependency
digest.  Local synthetic fixtures and non-production contract tests are
allowed while this gate is open.  The approval record must be referenced by a
new provenance revision; editing this status in place is not sufficient.

Spider_XHS additionally fetches/executes platform signing material and uses a
Node runtime.  Any activation requires a hash-pinned, sandboxed signer asset
and bounded process policy; dynamic unreviewed downloads are not accepted.
