from typing import Any, Protocol


class ReadingSessionRepository(Protocol):
    async def set(self, user_id: int, session: dict[str, Any]) -> None:
        ...

    async def get(self, user_id: int) -> dict[str, Any] | None:
        ...

    async def try_start_generation(self, user_id: int) -> bool:
        ...

    async def update(self, user_id: int, **fields: Any) -> None:
        ...

    async def cleanup(self, user_id: int) -> None:
        ...

    async def cleanup_expired(self) -> int:
        ...

    async def cleanup_all(self) -> None:
        ...
