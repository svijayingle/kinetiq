from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI

from kinetiq.core.queue_engine import QueueEngine
from kinetiq.core.store import QueueStore
from kinetiq.core.storage import SQLiteStorage
from kinetiq.routes.queues import router as queues_router


def create_app(
    database_path: str | Path | None = None,
    *,
    store: QueueStore | None = None,
) -> FastAPI:
    """Create a KinetiQ ASGI application.

    Args:
        database_path: SQLite database file path when using the default backend.
            Defaults to ``KINETIQ_DATABASE`` or ``kinetiq.db``.
        store: Optional custom backend implementing ``QueueStore``. If provided,
            ``database_path`` must not be set.
    """
    if store is not None and database_path is not None:
        raise ValueError("Set either 'store' or 'database_path', not both")
    resolved_path = database_path or os.getenv("KINETIQ_DATABASE", "kinetiq.db")
    configured_store = store or SQLiteStorage(resolved_path)
    engine = QueueEngine(configured_store)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await engine.initialize()
        app.state.queue_engine = engine
        yield

    app = FastAPI(title="KinetiQ", version="1.0.0", lifespan=lifespan)
    app.include_router(queues_router)
    return app