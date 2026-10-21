# Workflow architecture

Long-running and scheduled processes run on Temporal. The helpers are in `libs/py/sb_workflows`.
Rules: A12 (deterministic workflows), A8 (thin interface), C4, C6.

## Local server

`make up infra` starts a Temporal dev server (`temporalio/temporal`, `server start-dev`, sqlite
in a named volume). gRPC is on `127.0.0.1:7233` and the UI on `http://127.0.0.1:8233`. Like every
compose port, both bind to the loopback interface only.

## Where things live

- Workflows: `interface/workflows/<name>.py`. Activities: `interface/workflows/activities.py`.
  The worker is wired in `bootstrap.py` / `worker.py`.
- An activity restores the tenant context from its pydantic input and calls **one** use case.
  Business rules stay in the use case (A3, A8).
- `sb_workflows.client.connect(target, namespace, connect_timeout_s=10, *, tls=False,
  api_key=None)` connects with a bounded wait (C6). `tls` (a `TLSConfig` for mTLS) and `api_key`
  pass straight through to `Client.connect`.
- **Every client call needs its own deadline.** The SDK sets no per-call deadline by default, so
  pass `rpc_timeout=timedelta(seconds=10)` (or similar) to `start_workflow`, `execute_workflow`,
  `signal` and `query` (C6).
- `sb_workflows.worker.build_worker` builds a worker with a sandboxed runner. Its
  `graceful_shutdown_timeout` (default 10 s) is how long in-flight activities may finish on
  shutdown before they are cancelled. It **must stay below the pod's Kubernetes
  `terminationGracePeriodSeconds`** (default 30 s), or the kubelet kills the worker mid-shutdown.
  Activities are idempotent anyway, so a cancelled one is retried safely.

## Determinism (A12)

Workflow code is replayed from history, so it must do the same thing every time. No I/O, no
`datetime.now()`, no `random`, no unordered iteration. Use `workflow.now()` and `workflow.random()`.
All side effects belong in activities, which retry, so they must be idempotent.

**Time in workflows is `workflow.now()`, never a `Clock`.** `sb_kernel.clock.Clock` (and
`sb_testing.FakeClock` in tests) is for use cases and activities. Inside workflow code it would
read wall-clock time and break replay; `workflow.now()` is deterministic and is what the
time-skipping test server advances.

## Trust boundary

Temporal is trusted, authenticated infrastructure: in production only our services can reach the
frontend and start workflows (mTLS or API keys, per-namespace access). The tenant id and actor in
a workflow's or activity's input are therefore trusted **because of that**, and an activity
restores its context from them. Never let an untrusted caller start a workflow directly: an HTTP
endpoint authenticates first and passes the context from `current_context()`.

**Deterministic ids.** `workflow_id(name, tenant_id, key)` returns `<name>-<tenant_id>-<key>`.
`name` must be a strict lowercase slug with no UUID in it. `tenant_id` must be a `UUID`. `key`
is 1 to 200 printable characters, with no whitespace and not containing the tenant id. Those
rules keep ids injective, so two different inputs can never collide. Starting a workflow with an
id that is already running is rejected, which gives you dedupe.

## Data converter and sandbox

The client uses `pydantic_data_converter`, so workflow and activity inputs and outputs are pydantic
models. The workflow sandbox re-imports modules per run, which is slow and breaks type identity for
pydantic. `build_worker` passes `sb_kernel`, `pydantic` and `pydantic_core` through the sandbox
without re-importing them.

## Testing

- **Time skipping:** `async with sb_workflows.testing.time_skipping_env() as env:` runs workflows
  with timers skipped, so a 30-day timer takes milliseconds (T8).
- **Replay:** record a history with `fetch_history()`, commit it, and replay it with `Replayer`. A
  nondeterministic change then fails before deploy.
- **Platform caveat:** the time-skipping test server is an x64 binary. On Apple Silicon it needs
  Rosetta. On Linux ARM, use `WorkflowEnvironment.start_local()`, which runs the dev server and does
  not skip time (use short timers).

See the [`temporal-workflow`](../../.claude/skills/temporal-workflow/SKILL.md) skill.
