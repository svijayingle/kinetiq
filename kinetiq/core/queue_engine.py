from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timezone
from uuid import uuid4

from kinetiq.core.dlq import DeadLetterRouter
from kinetiq.core.store import QueueStore
from kinetiq.models import (
    CreateQueueRequest,
    Message,
    QueueResponse,
    SendMessageRequest,
    SendMessageResponse,
)


class QueueEngine:
    def __init__(self, store: QueueStore, poll_interval: float = 0.1) -> None:
        self.store = store
        self.dead_letter_router = DeadLetterRouter(store)
        self.poll_interval = poll_interval

    async def initialize(self) -> None:
        await self.store.initialize()

    async def create_queue(self, request: CreateQueueRequest) -> QueueResponse:
        created_at = datetime.now(timezone.utc)
        result = await self.store.create_queue(
            queue_name=request.queue_name,
            visibility_timeout=(
                30 if request.visibility_timeout is None else request.visibility_timeout
            ),
            max_receive_count=(
                5 if request.max_receive_count is None else request.max_receive_count
            ),
            dlq_name=request.dlq_name,
            created_at=created_at.isoformat(),
        )
        return QueueResponse.model_validate(result)

    async def send_message(
        self, queue_name: str, request: SendMessageRequest
    ) -> SendMessageResponse:
        sent_at = datetime.now(timezone.utc)
        message_id = await self.store.publish(
            queue_name=queue_name,
            message_id=str(uuid4()),
            body=request.body,
            deduplication_id=request.deduplication_id,
            message_group_id=request.message_group_id,
            sent_at=sent_at.isoformat(),
            now=time.time(),
        )
        checksum = hashlib.md5(request.body.encode("utf-8")).hexdigest()
        return SendMessageResponse(message_id=message_id, md5_checksum=checksum)

    async def receive_messages(
        self,
        queue_name: str,
        max_messages: int,
        visibility_timeout: int | None,
        wait_time_seconds: int,
    ) -> list[Message]:
        queue = await self.store.get_queue(queue_name)
        timeout = (
            queue["visibility_timeout"]
            if visibility_timeout is None
            else visibility_timeout
        )
        deadline = time.monotonic() + wait_time_seconds
        while True:
            now = time.time()
            await self.dead_letter_router.route_exhausted(queue_name, now)
            claimed = await self.store.claim_messages(
                queue_name, max_messages, timeout, now
            )
            if claimed or time.monotonic() >= deadline:
                return [Message.model_validate(message) for message in claimed]
            await asyncio.sleep(
                min(self.poll_interval, max(0, deadline - time.monotonic()))
            )

    async def delete_message(self, queue_name: str, receipt_handle: str) -> bool:
        return await self.store.acknowledge(queue_name, receipt_handle, time.time())