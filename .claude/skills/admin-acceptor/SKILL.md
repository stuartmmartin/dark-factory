---
name: admin-acceptor
description: Expose a pure policy as a SQLAdmin acceptor so humans can verify business math — enter inputs, see outputs and the policy version. Use whenever a new or changed policy has numbers a reviewer should check by hand.
---
# Admin acceptor
An acceptor is a tiny admin module where a human runs a pure policy with inputs they choose, checks
the outputs and accepts the business logic.

Reference: [admin architecture](../../../docs/architecture/admin.md). Rules: A5 (pure policies),
A8 (thin interface), T9 (boundary tests).

1. The policy is a pure function in `application/policies/<name>.py` that takes a pydantic input
   model and returns a pydantic output model. Give input fields `Field(description=...)`: the
   descriptions become the form's help text. Money fields are `Decimal` (C3).
2. **Raise an `sb_kernel.errors` error for input a user should be told about**, usually
   `ValidationFailed("rate must be below the cap")`. Policies import only `sb_kernel` (A2), never
   `sb_admin`. The acceptor shows any `DomainError`'s message verbatim with a 422. Any other
   exception is logged and shown as a generic "acceptor failed (see server logs)", so a
   `ValueError` message never reaches the user. Never put secrets or internals in the message.
   (`sb_admin.acceptor.InputRejected` exists only for interface-layer acceptor glue, an
   adapter in `interface/admin/`, not for policies.)
3. In `interface/admin/acceptors.py`:
   `Acceptor("<slug>", "<Title>", InputModel, policy_fn, version="<n>", description="...")`.
   Bump `version` whenever the policy's behaviour changes.
4. Add it to the `acceptors=[...]` of `sb_admin.admin.create_admin(engine, title=..., auth=...,
   acceptors=..., views=..., mount_path="/admin")` in `bootstrap.py`, and mount the result with
   `sb_http.app.mount_admin(app, admin_app)`. It mounts at the admin's own `mount_path`. That is
   the only public mount.
5. Tests (T9): POST valid inputs and assert the output; POST invalid input and get a 422 that
   re-renders the form; POST an input the policy rejects (it raises `ValidationFailed`) and assert
   the message is shown.
Acceptors never touch the database. For a calculation that needs stored data, write a read-only
use case plus a normal admin view. Do not write an acceptor.
