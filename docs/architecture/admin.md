# Admin architecture

The admin UI is SQLAdmin, wrapped by `libs/py/sb_admin`. Its main purpose is to let humans verify
business math: an **acceptor** is a tiny module that runs one of the pure policies the use cases
use, so a human can test the business logic by hand and accept it. Rules: A5, A8, T9.

## Mounting

`sb_admin.admin.create_admin(engine, *, title, auth, acceptors=(), views=(), mount_path="/admin")`
returns a standalone Starlette app that authenticates itself. It records `mount_path` as
`admin_app.state.mount_path`. Mount it on the service's FastAPI app with
`sb_http.app.mount_admin(app, admin_app)`, which mounts it at that recorded path, so the session
cookie path and the mount can never disagree. (`mount_admin` still takes an optional `path`, but
one that contradicts the recorded path raises `ValueError`.) That mount is public to `sb_http`'s
authentication (which exempts routes by identity: health, docs if `expose_docs=True`, and this
one mount), so the admin app **must** carry its own auth. `create_admin` does not modify the
`DevAdminAuth` you pass: it binds a copy to `mount_path`, so one auth object can serve several
admins.

## Authentication is dev-only

`DevAdminAuth(secret_key, username, password, *, environment)` is a single shared login with a
signed-cookie session. It refuses to construct unless `environment` is one of
`local`, `dev`, `test`, `ci`, and the secret must be at least 32 characters. Its limits (no per-user
identity, no CSRF protection, no throttling, no audit, cookie sessions that cannot be revoked
server-side) are listed in `sb_admin/auth.py`. **Production admin needs OIDC/SSO** and will come with
its own spec. Do not deploy this outside dev.

## Views

Add read-only `ModelView`s for ledger-like tables (no create, edit or delete), since those tables
are append-only (see [data](data.md)). Pass them as `views=[...]`.

SQLAdmin queries through the engine you pass to `create_admin`. Nothing in the admin sets
`app.tenant_id`, so on an `sb_app` engine RLS-scoped tables show no rows. Which role and tenant
scoping the admin uses is decided with the production-auth spec.

**Ruling D9 (Plan 4, flagged for a human):** services build the admin on their own `sb_app`
engine, so under FORCE RLS with no tenant set every list view shows **zero rows**. This is accepted
for Plan 4 as a demonstration of the RLS limit: the ledger's `AccountAdmin` list returns 200 and
lists none of the accounts a tenant opened (pinned by
`services/ledger/tests/integration/admin/test_admin.py`). Never give the admin `migrator_url` or
any other `BYPASSRLS` role to "fix" this; that would show every tenant's rows to one shared dev
login. A tenant picker (setting `app.tenant_id` per admin request) is a follow-up that needs a
human decision on who may pick which tenant.

The admin is mounted only when `environment != "prod"` (`DevAdminAuth` refuses anything outside
`local/dev/test/ci`). In prod the app does not start at all until OIDC exists (ruling D1).

## Acceptors

An `Acceptor(slug, title, input_model, fn, version, description)` renders a form from a pydantic
input model, calls the pure policy, and shows inputs, outputs and the version. It never touches the
database, so a reviewer can check a number by hand without writing SQL.

- Input field descriptions become help text. Optional fields left empty use the model default.
  `list[...]` fields take repeated values or a comma-separated one.
- Invalid input re-renders the form with a 422 and field-level messages.
- A `list[...]` field left blank counts as missing, so a required list reports "Field required"
  rather than silently becoming `[]`.
- A policy refuses input by raising an `sb_kernel.errors.DomainError` subclass, usually
  `ValidationFailed` (policies import only the kernel, A2). Its `message` is shown with a 422.
  `sb_admin.acceptor.InputRejected` does the same, but only for interface-layer acceptor
  glue, never in a policy. Any other exception is logged as `admin.acceptor_failed` and shown as
  a generic "acceptor failed" message, so internals never leak.
- **Versioning:** bump `version` whenever the policy's behaviour changes. A reviewer comparing two
  results can then tell which rule set produced each.

See the [`admin-acceptor`](../../.claude/skills/admin-acceptor/SKILL.md) skill.
