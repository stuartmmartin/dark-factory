---
name: security-review
description: Security review for changes touching auth, tenancy/RLS, HTTP endpoints, SQL, secrets, PII, file/URL input, external calls, CI workflows or dependencies. Stack-specific checklist; findings are evidence-bound and blocking.
---
# Security review

Threat model: a family office's private financial data, multiple families and entities in one
deployment (A13), and AI-written code. Every finding cites `path:line` and quotes the diff.

## Checklist
1. **Tenancy (A13):** every new table has `tenant_id` + an RLS policy; the tenant is taken only
   from `RequestContext`; no query uses a role with `BYPASSRLS`; there is an isolation test.
2. **AuthZ:** every new route has an explicit auth dependency, and access decisions happen in
   use cases. Never trust `is_admin`-style flags sent by the client.
3. **Input:** pydantic models with bounds (lengths, ranges, enums) at every boundary (C7). No
   `eval`/`pickle`/`yaml.load` on input.
4. **SQL (C10):** no string-built SQL, no `text()` with interpolated values.
5. **Outbound I/O (C6):** timeouts; SSRF (no user-controlled URLs without an allowlist); TLS
   verification never disabled.
6. **Secrets (C14):** nothing in code, fixtures or logs; `SecretStr`; no new env var without a
   `.env.example` key.
7. **PII and logging (C9):** no PII or financial identifiers in logs or exceptions; redaction
   annotations on new fields.
8. **Audit (A14):** state changes are auditable (who, what, when, why).
9. **Idempotency:** writes accept an `Idempotency-Key`; consumers dedupe (A11).
10. **CI/workflows:** actions pinned by SHA, least-privilege `permissions:`, no `${{ }}` inside
    `run:`, secrets never echoed.
11. **Dependencies:** run the `supply-chain-audit` skill for any `pyproject.toml`/`uv.lock` change.

## Verdict
PASS or FAIL, using the reviewer output format in `../code-review/reviewer-prompt.md`.
Security findings are always blocking.
