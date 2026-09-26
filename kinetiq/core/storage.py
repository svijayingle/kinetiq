from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiosqlite

from kinetiq.core.store import QueueAlreadyExistsError, QueueNotFoundError


class SQLiteStorage:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(self.database_path, timeout=5)
        connection.row_factory = aiosqlite.Row
        await connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            await connection.close()

    async def initialize(self) -> None:
        async with self._connect() as connection:
            await connection.execute("PRAGMA journal_mode = WAL")
            await connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS queues (
                    queue_name TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    visibility_timeout INTEGER NOT NULL,
                    max_receive_count INTEGER NOT NULL,
                    dlq_name TEXT
                );
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    queue_name TEXT NOT NULL REFERENCES queues(queue_name)
                        ON DELETE CASCADE,
                    body TEXT NOT NULL,
                    deduplication_id TEXT,
                    message_group_id TEXT,
                    sent_at TEXT NOT NULL,
                    receive_count INTEGER NOT NULL DEFAULT 0,
                    visible_at REAL NOT NULL,
                    receipt_handle TEXT
                );
                CREATE INDEX IF NOT EXISTS messages_available_idx
                    ON messages(queue_name, visible_at, sent_at);
                CREATE INDEX IF NOT EXISTS messages_dedup_idx
                    ON messages(queue_name, deduplication_id);
                """
            )
            await connection.commit()

    async def create_queue(
        self,
        queue_name: str,
        visibility_timeout: int,
        max_receive_count: int,
        dlq_name: str | None,
        created_at: str,
    ) -> dict[str, Any]:
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            if dlq_name is not None:
                cursor = await connection.execute(
                    "SELECT 1 FROM queues WHERE queue_name = ?", (dlq_name,)
                )
                if await cursor.fetchone() is None:
                    await connection.rollback()
                    raise QueueNotFoundError(dlq_name)
            try:
                await connection.execute(
                    """INSERT INTO queues
                       (queue_name, created_at, visibility_timeout,
                        max_receive_count, dlq_name)
                       VALUES (?, ?, ?, ?, ?)""",
                    (queue_name, created_at, visibility_timeout, max_receive_count, dlq_name),
                )
            except aiosqlite.IntegrityError as error:
                await connection.rollback()
                raise QueueAlreadyExistsError(queue_name) from error
            await connection.commit()
        return {"queue_name": queue_name, "created_at": created_at}

    async def get_queue(self, queue_name: str) -> dict[str, Any]:
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT * FROM queues WHERE queue_name = ?", (queue_name,)
            )
            row = await cursor.fetchone()
        if row is None:
            raise QueueNotFoundError(queue_name)
        return dict(row)

    async def update_queue_visibility_timeout(
        self, queue_name: str, visibility_timeout: int
    ) -> dict[str, Any]:
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                "UPDATE queues SET visibility_timeout = ? WHERE queue_name = ?",
                (visibility_timeout, queue_name),
            )
            if cursor.rowcount != 1:
                await connection.rollback()
                raise QueueNotFoundError(queue_name)
            cursor = await connection.execute(
                "SELECT * FROM queues WHERE queue_name = ?", (queue_name,)
            )
            row = await cursor.fetchone()
            await connection.commit()
        return dict(row)

    async def count_messages(self, queue_name: str) -> int:
        async with self._connect() as connection:
            cursor = await connection.execute(
                                """SELECT queue_name,
                                                    (SELECT COUNT(*) FROM messages
                                                     WHERE messages.queue_name = queues.queue_name)
                                                            AS message_count
                                     FROM queues WHERE queue_name = ?""",
                (queue_name,),
            )
            row = await cursor.fetchone()
        if row is None:
            raise QueueNotFoundError(queue_name)
        return int(row["message_count"])

    async def publish(
        self,
        queue_name: str,
        message_id: str,
        body: str,
        deduplication_id: str | None,
        message_group_id: str | None,
        sent_at: str,
        now: float,
    ) -> str:
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                "SELECT 1 FROM queues WHERE queue_name = ?", (queue_name,)
            )
            if await cursor.fetchone() is None:
                await connection.rollback()
                raise QueueNotFoundError(queue_name)
            if deduplication_id is not None:
                cursor = await connection.execute(
                    """SELECT message_id FROM messages
                       WHERE queue_name = ? AND deduplication_id = ?
                       ORDER BY sent_at LIMIT 1""",
                    (queue_name, deduplication_id),
                )
                existing = await cursor.fetchone()
                if existing is not None:
                    await connection.commit()
                    return str(existing["message_id"])
            await connection.execute(
                """INSERT INTO messages
                   (message_id, queue_name, body, deduplication_id,
                    message_group_id, sent_at, visible_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (message_id, queue_name, body, deduplication_id, message_group_id, sent_at, now),
            )
            await connection.commit()
        return message_id

    async def route_exhausted_messages(self, queue_name: str, now: float) -> int:
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                "SELECT dlq_name, max_receive_count FROM queues WHERE queue_name = ?",
                (queue_name,),
            )
            source = await cursor.fetchone()
            if source is None:
                await connection.rollback()
                raise QueueNotFoundError(queue_name)
            dlq_name = source["dlq_name"]
            if dlq_name is None:
                await connection.commit()
                return 0
            cursor = await connection.execute(
                "SELECT 1 FROM queues WHERE queue_name = ?", (dlq_name,)
            )
            if await cursor.fetchone() is None:
                await connection.rollback()
                raise QueueNotFoundError(dlq_name)
            cursor = await connection.execute(
                """SELECT * FROM messages
                   WHERE queue_name = ? AND visible_at <= ? AND receive_count >= ?
                   ORDER BY sent_at, message_id""",
                (queue_name, now, source["max_receive_count"]),
            )
            exhausted = await cursor.fetchall()
            for message in exhausted:
                await connection.execute(
                    """INSERT INTO messages
                       (message_id, queue_name, body, message_group_id, sent_at,
                        receive_count, visible_at)
                       VALUES (?, ?, ?, ?, ?, 0, ?)""",
                    (str(uuid4()), dlq_name, message["body"], message["message_group_id"],
                     message["sent_at"], now),
                )
                await connection.execute(
                    "DELETE FROM messages WHERE message_id = ?", (message["message_id"],)
                )
            await connection.commit()
        return len(exhausted)

    async def claim_messages(
        self, queue_name: str, max_messages: int, visibility_timeout: int, now: float
    ) -> list[dict[str, Any]]:
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                "SELECT 1 FROM queues WHERE queue_name = ?", (queue_name,)
            )
            if await cursor.fetchone() is None:
                await connection.rollback()
                raise QueueNotFoundError(queue_name)
            cursor = await connection.execute(
                """SELECT message.* FROM messages AS message
                   WHERE message.queue_name = ? AND message.visible_at <= ?
                     AND (message.message_group_id IS NULL OR NOT EXISTS (
                         SELECT 1 FROM messages AS earlier
                         WHERE earlier.queue_name = message.queue_name
                           AND earlier.message_group_id = message.message_group_id
                           AND (earlier.sent_at < message.sent_at OR
                               (earlier.sent_at = message.sent_at AND
                                earlier.message_id < message.message_id))
                     ))
                   ORDER BY message.sent_at, message.message_id LIMIT ?""",
                (queue_name, now, max_messages),
            )
            rows = await cursor.fetchall()
            claimed: list[dict[str, Any]] = []
            for row in rows:
                receipt_handle = str(uuid4())
                await connection.execute(
                    """UPDATE messages
                       SET receive_count = receive_count + 1,
                           visible_at = ?, receipt_handle = ?
                       WHERE message_id = ?""",
                    (now + visibility_timeout, receipt_handle, row["message_id"]),
                )
                claimed.append(
                    {
                        "message_id": row["message_id"],
                        "receipt_handle": receipt_handle,
                        "body": row["body"],
                        "receive_count": row["receive_count"] + 1,
                        "sent_at": row["sent_at"],
                    }
                )
            await connection.commit()
        return claimed

    async def acknowledge(self, queue_name: str, receipt_handle: str, now: float) -> bool:
        async with self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                "SELECT 1 FROM queues WHERE queue_name = ?", (queue_name,)
            )
            if await cursor.fetchone() is None:
                await connection.rollback()
                raise QueueNotFoundError(queue_name)
            cursor = await connection.execute(
                """DELETE FROM messages
                   WHERE queue_name = ? AND receipt_handle = ? AND visible_at > ?""",
                (queue_name, receipt_handle, now),
            )
            await connection.commit()
        return cursor.rowcount == 1