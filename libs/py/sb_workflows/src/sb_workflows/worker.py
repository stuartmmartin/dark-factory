"""Worker builder: sandboxed workflows with pydantic and kernel modules passed through.

`graceful_shutdown_timeout` (default 10 s) is how long in-flight activities may finish when the
worker shuts down before they are cancelled. Keep it below the pod's Kubernetes
`terminationGracePeriodSeconds` (default 30 s), or the kubelet kills the process first.
"""

from collections.abc import Callable, Sequence
from datetime import timedelta

from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

PASSTHROUGH_MODULES = ("sb_kernel", "pydantic", "pydantic_core")
DEFAULT_GRACEFUL_SHUTDOWN = timedelta(seconds=10)


def build_worker(
    client: Client,
    *,
    task_queue: str,
    workflows: Sequence[type],
    activities: Sequence[Callable[..., object]],
    graceful_shutdown_timeout: timedelta = DEFAULT_GRACEFUL_SHUTDOWN,
) -> Worker:
    """Build a worker whose workflow sandbox does not re-import PASSTHROUGH_MODULES."""
    return Worker(
        client,
        task_queue=task_queue,
        workflows=workflows,
        activities=activities,
        graceful_shutdown_timeout=graceful_shutdown_timeout,
        workflow_runner=SandboxedWorkflowRunner(
            restrictions=SandboxRestrictions.default.with_passthrough_modules(*PASSTHROUGH_MODULES)
        ),
    )
