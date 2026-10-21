---
name: external-io
description: Reference catalog of external I/O anti-patterns AP-1..AP-11 (timeouts, retries, fallbacks, circuit breakers, secrets in logs) — cited by code-review, security-review and performance-review when a diff calls databases, brokers, HTTP APIs or SDKs.
---
# External I/O anti-patterns (C6)

| ID | Anti-pattern | Do instead |
|---|---|---|
| AP-1 | Unbounded wait: no timeout on HTTP/DB/SDK calls | Explicit timeout on every call and client |
| AP-2 | Unbounded retry wall time | Cap attempts *and* total time; jittered backoff |
| AP-3 | Silent default fallback on failure | Fail closed with a typed error (C8) |
| AP-4 | A long-lived client missing timeout or pool config | Configure it once in the adapter constructor |
| AP-5 | No circuit breaker on a flaky dependency | Breaker or bulkhead, with a metric on open |
| AP-6 | Trusting unverified external input | Validate into a pydantic model at the adapter (C7) |
| AP-7 | A synchronous call longer than the endpoint budget | Move it to a Temporal activity or a background job |
| AP-8 | Secrets or tokens in logs or exceptions | Redact; `SecretStr` (C9, C14) |
| AP-9 | Floating references (unpinned API versions, `latest` images) | Pin versions |
| AP-10 | Refactor leftovers (dead clients, duplicate calls) | Delete them |
| AP-11 | Long work in the request path | Do it asynchronously: outbox → consumer, or a workflow |
