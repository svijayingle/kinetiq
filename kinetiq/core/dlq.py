from kinetiq.core.storage import SQLiteStorage


class DeadLetterRouter:
    def __init__(self, storage: SQLiteStorage) -> None:
        self.storage = storage

    async def route_exhausted(self, queue_name: str, now: float) -> int:
        return await self.storage.route_exhausted_messages(queue_name, now)