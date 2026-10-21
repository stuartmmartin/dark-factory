# Coding conventions (C-rules)

### C1 — Types everywhere
Every function, parameter and return is annotated. pyright `strict` applies to `domain/`,
`application/`, `libs/py/sb_kernel` and `tools/*/src`, and `standard` applies elsewhere. Don't add
`# type: ignore` without a trailing reason.
*Enforced:* `make typecheck`; post-edit hook.

### C2 — Absolute imports
`from ledger.application.ports import JournalRepository`, never `from ..ports import …`.
*Enforced:* ruff `TID252`.

### C3 — Money is Decimal
Amounts are `sb_kernel.Money` (a `Decimal` plus an ISO 4217 currency), stored as Postgres `NUMERIC`,
and serialized as strings on the wire. `float` is banned in logic layers. Rounding is always
explicit (`ROUND_HALF_EVEN` unless an ADR says otherwise). Allocation uses largest-remainder, so no
minor unit is lost.
*Enforced:* `no-float` check; Hypothesis properties (T6).

### C4 — Time is injected
Read time only through the `Clock` port. Datetimes are timezone-aware UTC; business dates are
`date`. Never call `datetime.now()`, `date.today()` or `time.time()` in `src/`.
*Enforced:* `no-naive-now` check; ruff `DTZ`.

### C5 — Configuration in one place
Environment variables are read only in `infrastructure/settings.py` (`pydantic-settings`), and
settings are passed down from `bootstrap.py`.
*Enforced:* `no-env-read` check.

### C6 — Bounded external I/O
Every outbound call has an explicit timeout, and retries are bounded in both count and total wall
time. See the `external-io` skill (AP-1…AP-11).
*Enforced:* `httpx-timeout` check; review.

### C7 — Shaped data is a model
Any data with a known shape that crosses a boundary (HTTP, events, workflow inputs, use case
commands and results) is a frozen pydantic model or a domain dataclass. Never pass `dict[str, Any]`
between layers.
*Enforced:* review; pyright.

### C8 — Errors are typed and never swallowed
Inner layers raise `sb_kernel.errors` subclasses (`NotFound`, `Conflict`, `ValidationFailed`,
`Forbidden`). HTTP mapping happens once, in `sb_http`. Don't use bare `except:`. Don't write
`except Exception: pass`. Don't return a default value silently on failure.
*Enforced:* ruff `E722` (bare except) and `S110` (silent pass); review of broad catches.
`BLE` is not enabled: explicit boundary catches that log and translate failures are permitted.

### C9 — Structured, redacted logging
Use `structlog` with event names `"<module>.<event>"` and context as keyword arguments. Never log
secrets or fields annotated as PII. `SecretStr` for secrets.
*Enforced:* redaction processor in `sb_obs`; review; security review.

### C10 — Typed, bounded SQL
Use typed SQLAlchemy 2.0 (`Mapped[...]`, `select()`). Never build SQL strings. Every list query is
bounded (`limit`/pagination) or carries a comment justifying why it can't grow.
*Enforced:* ruff `S608`; review; performance review.

### C11 — Names and size
Name modules and functions after what they do. `utils`, `helpers`, `common` and `misc` are banned.
Each file has one responsibility, and a file over ~300 lines is a signal to split it.
*Enforced:* `banned-module-names` check; review.

### C12 — No deprecated APIs
Never introduce a deprecated API. Existing uses are debt, not precedent.
*Enforced:* review; pytest `filterwarnings = ["error"]`. Fix warning causes rather than adding
blanket ignores.

### C13 — Dependencies are declared and justified
Each workspace member declares every dependency it imports. A new third-party dependency needs a
one-line justification in the PR.
*Enforced:* deptry; `sb-graph check`; supply-chain review.

### C14 — Secrets never enter the repo
Only `.env.example` (keys, no values) is committed. Agents never read or edit `.env` files.
*Enforced:* gitleaks (pre-commit + CI); pre-edit and pre-bash hooks.
