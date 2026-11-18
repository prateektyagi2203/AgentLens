# ADR-006: Web Bot Auth verification (C4 Tier 1)
Date: 2026-11-18
Status: Accepted
## Context
PRD 11 needs a Verified identity tier that cannot be forged by copying a User-Agent. Web Bot Auth signs requests with HTTP Message Signatures (RFC 9421). The architecture draft is still an IETF Internet-Draft, so the implemented version has to be pinned and the unsupported parts stated.
## Decision
- Implemented against `draft-meunier-web-bot-auth-architecture-05` (2 March 2026) and RFC 9421. Re-check the draft before relying on newer revisions.
- Signature-Input is parsed as an RFC 8941 structured-field dictionary (`services/api/identify/signatures.py`): covered components, `created`, `expires`, `keyid`, `alg`, `nonce`, `tag`. Only signatures with `tag="web-bot-auth"` are evaluated; other tags are ignored (`signature_status` stays NULL, the request is not penalised).
- `Signature-Agent` is read as a dictionary member, a bare URL or an sf-string (older draft forms). Its origin is the key directory host.
- Keys come from `<origin>/.well-known/http-message-signatures-directory` (JWKS). `keyid` must equal the RFC 7638 JWK thumbprint of the Ed25519 key (`kty=OKP`, `crv=Ed25519`). Keys are cached in `key_cache` with a TTL (`identification.yaml`). Resolution order: fresh cache, live fetch, stale cache, bundled keys. `offline_mode: true` skips the live fetch. The demo operator's public JWKS (`https://agents.desithreads.test`) is bundled in `identify/bundled_keys.json`.
- The RFC 9421 signature base is rebuilt from the stored request record: `@authority` (host), `@method`, `@path`, `@query`, `@target-uri`, `@scheme`, `@request-target`, and any header field (including `;key=` parameters), followed by the `@signature-params` line. Header values are trimmed only. Verification uses Ed25519 via `cryptography`.
- `created <= ts <= expires` is checked with `clock_skew_s` (60). Statuses: `valid`, `invalid_sig`, `expired`, `unknown_key`, `fetch_failed`. An `invalid_sig` or `unknown_key` signature adds the `invalid_signature` suspicion weight (+30).
- Raw signature headers are kept in `request_signatures`, because verification needs them and the main table keeps only `has_signature`.
## Not implemented
- Algorithms other than Ed25519.
- Verification of the directory's own self-signature (draft section on key directory signing).
- Nonce replay tracking, and signature `tag` values other than `web-bot-auth`.
- Real-world operator directories: only the bundled test operator is trusted offline.
## Alternatives considered
- Trusting `Signature-Agent` or a UA token alone: forgeable, so it only reaches Declared.
- Verifying at the store: the store only logs; verification belongs to the analytics layer so it can be re-run on historical logs.
## Consequences
- A forged signature (valid format, wrong key) is Suspected, never Verified (SC1: zero false Verified).
- Verification is reproducible offline from logs plus the cached or bundled directory.
- The limitation text (PRD 11.4) lives in `identify/constants.py::HONEST_LIMITATION` for the API and README.
