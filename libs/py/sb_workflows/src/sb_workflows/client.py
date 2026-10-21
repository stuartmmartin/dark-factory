"""Temporal client connection using the pydantic data converter.

`connect()` bounds only the connection. Client calls carry their own deadline: pass
`rpc_timeout=` (e.g. `timedelta(seconds=10)`) to `start_workflow`, `execute_workflow`,
`signal`, `query` and friends (C6). The Temporal SDK default is no per-call deadline.
"""

import asyncio

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.service import TLSConfig

__all__ = ["connect"]


async def connect(
    target: str,
    namespace: str = "default",
    connect_timeout_s: float = 10.0,
    *,
    tls: bool | TLSConfig = False,
    api_key: str | None = None,
) -> Client:
    """Connect to Temporal at `target` within `connect_timeout_s` (C6); pydantic models pass.

    `tls` and `api_key` are passed straight to `Client.connect` (mTLS / Temporal Cloud).
    """
    try:
        async with asyncio.timeout(connect_timeout_s):
            return await Client.connect(
                target,
                namespace=namespace,
                data_converter=pydantic_data_converter,
                tls=tls,
                api_key=api_key,
            )
    except TimeoutError as exc:
        raise TimeoutError(f"timed out after {connect_timeout_s}s connecting to {target}") from exc
