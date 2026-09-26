from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class QueueNotFoundError(Exception):
    def __init__(self, queue_name: str) -> None:
        self.queue_name = queue_name
        super().__init__(f"Queue '{queue_name}' does not exist")


class QueueAlreadyExistsError(Exception):
    def __init__(self, queue_name: str) -> None:
        self.queue_name = queue_name
        super().__init__(f"Queue '{queue_name}' already exists")


@runtime_checkable
class QueueStore(Protocol):
    """Backend contract required by the KinetiQ queue engine.

    Implementations must make message claims atomic across concurrent consumers,
    enforce receipt-handle lease expiry during acknowledgement, and move exhausted
    messages to a DLQ without losing them if a transfer fails.
    """

    async def initialize(self) -> None: ...

    async def create_queue(
        self,
        queue_name: str,
        visibility_timeout: int,
        max_receive_count: int,
        dlq_name: str | None,
        created_at: str,
    ) -> dict[str, Any]: ...

    async def get_queue(self, queue_name: str) -> dict[str, Any]: ...

    async def update_queue_visibility_timeout(
        self, queue_name: str, visibility_timeout: int
    ) -> dict[str, Any]: ...

    async def count_messages(self, queue_name: str) -> int: ...

    async def publish(
        self,
        queue_name: str,
        message_id: str,
        body: str,
        deduplication_id: str | None,
        message_group_id: str | None,
        sent_at: str,
        now: float,
    ) -> str: ...

    async def route_exhausted_messages(self, queue_name: str, now: float) -> int: ...

    async def claim_messages(
        self, queue_name: str, max_messages: int, visibility_timeout: int, now: float
    ) -> list[dict[str, Any]]: ...

    async def acknowledge(
        self, queue_name: str, receipt_handle: str, now: float
    ) -> bool: ...