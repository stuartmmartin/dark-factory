---
name: temporal-workflow
description: Add a Temporal workflow or activity — scheduled jobs, long-running processes, retries with timers, multi-step orchestration — using sb_workflows. Deterministic workflow code, activities call one use case, deterministic ids, time-skipping and replay tests.
---
# Temporal workflow
Reference: [workflows architecture](../../../docs/architecture/workflows.md). Rules: A12
(deterministic workflows), A8 (thin interface), C4 (time), C6 (bounded I/O).

1. The workflow goes in `interface/workflows/<name>.py` (`@workflow.defn`). It does no I/O, does
   not read the clock or randomness (use `workflow.now()` / `workflow.random()`, **never** a
   `sb_kernel` `Clock` or `FakeClock` in workflow code), and does not iterate over unordered
   sets. Inputs and outputs are pydantic models (the client uses the
   pydantic data converter).
2. Activities go in `interface/workflows/activities.py`. Each `@activity.defn` restores the tenant
   context from its pydantic input (`sb_kernel.context.use_context(...)`) and calls **one** use
   case. Activities retry, so the use case must be idempotent. Give every activity a timeout.
3. Workflow ids: `sb_workflows.ids.workflow_id("<name>", tenant_id, "<business key>")`. `name` is a
   lowercase slug, `tenant_id` must be a `UUID`, and the key must not contain the tenant id or
   whitespace. The function raises otherwise. Starting a workflow whose id is already running is rejected, which is the dedupe.
4. Connect with `sb_workflows.client.connect(target)` (10 s connect timeout by default; `tls=`
   and `api_key=` pass through). Pass `rpc_timeout=` on every `start_workflow`,
   `execute_workflow`, `signal` and `query` call: the SDK has no per-call deadline. Then
   build the worker with `sb_workflows.worker.build_worker(client, task_queue=..., workflows=...,
   activities=...)`. It passes `sb_kernel`, `pydantic` and `pydantic_core` through the sandbox.
5. Tests:
   - `tests/integration/workflows/` with `sb_workflows.testing.time_skipping_env()`. Timers are
     skipped. The time-skipping server is an x64 binary: on Apple Silicon it needs Rosetta. On
     Linux ARM use `WorkflowEnvironment.start_local()` instead.
   - Record a history once (`handle.fetch_history()`) into
     `tests/integration/workflows/histories/<name>.json` and add a `Replayer` test, so a
     nondeterministic change fails before deploy.
