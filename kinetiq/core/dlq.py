from kinetiq.core.store import QueueStore


class DeadLetterRouter:
    def __init__(self, store: QueueStore) -> None:
        self.store = store

    async def route_exhausted(self, queue_name: str, now: float) -> int:
        return await self.store.route_exhausted_messages(queue_name, now)