import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")


class OperationTimeoutError(RuntimeError):
    def __init__(self, operation: str, timeout_seconds: int | float) -> None:
        super().__init__(
            f"{operation} timed out after {timeout_seconds} seconds"
        )
        self.operation = operation
        self.timeout_seconds = timeout_seconds


async def run_with_timeout(
    awaitable: Awaitable[T],
    *,
    operation: str,
    timeout_seconds: int | float,
) -> T:
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except asyncio.TimeoutError as error:
        raise OperationTimeoutError(operation, timeout_seconds) from error


async def run_sync_with_timeout(
    function: Callable[..., T],
    *args: Any,
    operation: str,
    timeout_seconds: int | float,
    **kwargs: Any,
) -> T:
    return await run_with_timeout(
        asyncio.to_thread(function, *args, **kwargs),
        operation=operation,
        timeout_seconds=timeout_seconds,
    )
