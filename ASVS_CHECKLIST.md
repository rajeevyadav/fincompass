# OWASP ASVS-Oriented Self-Assessment — FinCompass

FinCompass uses OWASP ASVS Level 1 concepts as a practical checklist for a no-auth freeware research app. This is a self-assessment, not certification.

| Area | Status | FinCompass control |
|---|---|---|
| Architecture/threat boundaries | Implemented | `ARCHITECTURE.md`; evidence, forecast, data and registry boundaries separated |
| Authentication/session management | N/A | No accounts or server user sessions |
| Access control | N/A for user roles | Public research endpoints; no privileged browser workflow |
| Input validation | Implemented | strict ticker validation; Pydantic/query bounds; settings whitelist/range validation |
| Output/XSS | Implemented | escaped/text-based rendering; provider HTML is not trusted |
| Secret handling | Implemented at app layer | environment credentials; no key-bearing exception URLs |
| Error handling | Implemented | short client errors; request IDs; no client stack traces |
| Logging/privacy | Implemented | daily-hashed client ID default; rotation controls |
| Transport security | Deployment responsibility | HSTS on HTTPS; TLS/proxy external |
| Business-logic abuse | Implemented | endpoint-group limits; background refresh coordination |
| File upload | N/A | no upload endpoint |
| Model artifact trust | Implemented/operational | hash-verified registry; only validated tiers live; no untrusted uploads; joblib trust warning documented |
| API validation/versioning | Implemented | `/api/v1/*` evidence; `/api/v1/*` forecast/settings; v1 forecast aliases compatibility-only |
| Security headers | Implemented | CSP, nosniff, frame deny, referrer, permissions, COOP/CORP |
| Browser third-party dependency | Minimized | no runtime app CDN/library dependency |
| Export safety | Implemented | CSV formula-injection neutralization |
| Runtime filesystem | Implemented in Docker | non-root; `/app/data` writable, app/model files immutable to service user |
| Dependency/build integrity | Partial | CI/tests/release hashes; signed releases and SBOM not yet established |

## Residual risk

Primary residual risks are upstream data correctness, public-host configuration, dependency vulnerabilities, trusted-model artifact handling, statistical/model risk, regime shift, and lack of independent penetration/accessibility testing. Automated tests do not close these risks by themselves.

## Adaptive/event additions

- [x] External event ingest disabled by default.
- [x] Ingest protected by bearer secret when enabled.
- [x] Token not accepted as URL query parameter.
- [x] Event payload size bounded and event schema normalized.
- [x] Event replay duplication reduced with deterministic IDs / insert-ignore semantics.
- [x] Dedicated realtime/ingest/adaptive rate-limit groups.
- [x] Adaptive registry state hash verified before eligible load.
- [x] Synthetic/rejected adaptive artifacts excluded from live use.
- [x] Stale/warming/degraded adaptive state fails back to zero residual influence.
- [x] Runtime data separated from immutable application/model artifacts in container packaging.
