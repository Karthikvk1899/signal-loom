# Threat model

Assets: release integrity, tenant configurations, actor identity, signing key, credentials and audit continuity. Boundaries: browser→API, API→PostgreSQL, trusted key provisioning→SDK, snapshot transport→SDK. Threat actors include unauthenticated network callers, a tenant reader, a compromised author/reviewer, a malicious transport intermediary, and privileged infrastructure operators.

| Threat | Implemented control | Residual risk |
|---|---|---|
| Cross-tenant reads/writes | Tenant derived from hashed bearer credential; every scoped lookup includes tenant; integration negatives | App-only isolation, no PostgreSQL RLS |
| Author silently ships change | Distinct author/reviewer role checks and different actor string on approval and activation | Admin can provision arbitrary identities; no OIDC/SSO or human identity proof |
| Concurrent lost update | Environment row lock plus expected generation and draft base | Lock contention and DB availability limit throughput |
| Snapshot modification | Ed25519 signature, pinned key, strict bundle validation | Stolen signing key defeats this boundary |
| Replay/downgrade | In-memory generation check; no freshness extension on failed refresh; age deadline | Restart loses high-water mark; signatures have no expiry; hostile trusted origin can replay; TLS required |
| API token theft | Random 320-bit token input, SHA-256 digest at rest, one-time issuance, revoke API, UI memory only | XSS/browser compromise can read token; no OIDC, MFA or automatic expiry |
| SQL injection | Parameterized values; only fixed SQL strings | Compromised app/DB credentials can mutate all tenant rows |
| XSS/UI framing | React escaping, no raw HTML rendering, CSP, X-Frame-Options, no third-party scripts/fonts | Browser extension compromise is outside scope |
| CSRF | Bearer header rather than ambient cookies; no permissive CORS | Stolen bearer can make authorized requests |
| Request exhaustion | 64 KiB body limit, bounded model lists, bounded pool, statement/lock timeouts, list caps | No app-level rate limit; ingress quotas and slow-client controls needed |
| Audit tampering | Release event commits with release state; no audit edit API | DB operator can alter events; no external append-only ledger |
| Sensitive targeting data | Local evaluation does not transmit subjects | Allow/deny lists and preview requests contain IDs; use pseudonymous/synthetic values |

No arbitrary rule interpreter, remote URL fetch, user code execution, webhook egress, or automatic flag-driven authorization is offered. Empty/missing flags default false; stale SDK bundles use the application's explicit default. That default must be selected per business risk—false is not universally safe.

The API container runs non-root with dropped capabilities and read-only filesystem in Compose. Dev DB credentials are public demo values on a network with no host DB port; they are unsuitable for production. `.env` contains secrets and must never be committed. Dependency audits/CodeQL reduce some classes of risk; they do not substitute for adversarial review. Container base images, live identity providers, TLS deployment, penetration testing, tenant quotas and high availability remain unverified.
