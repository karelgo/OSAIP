"""Run blocking engine work off the event loop (ADR-0006 §4).

DuckDB and boto3 are blocking C/network code; calling them directly in an async
request would freeze the single-process uvicorn event loop. Every engine entry point
goes through `run_engine`, which offloads to a worker thread and bounds concurrency
with a semaphore so parallel conversions cannot exhaust memory.
"""

from collections.abc import Callable

import anyio

# Bounded concurrency for engine operations (env-tunable by the caller if needed).
_limiter = anyio.CapacityLimiter(3)


async def run_engine[T](func: Callable[[], T]) -> T:
    return await anyio.to_thread.run_sync(func, limiter=_limiter)
