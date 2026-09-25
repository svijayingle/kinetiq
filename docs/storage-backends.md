# Configuring Queue Storage Backends

KinetiQ's storage implementation is selected by the host application's Python code. There is no `KINETIQ_STORE=redis` setting and no built-in Redis, SQL, NoSQL, or S3 adapter today. SQLite is the built-in default; every other backend must be implemented as an adapter and supplied to `create_app()`.

## Quick Start

Install KinetiQ and the selected backend's driver in the host project. Create an adapter that implements `QueueStore`, then inject it into the ASGI app:

```python
# queue_service.py
from kinetiq import create_app
from my_service.storage import RedisQueueStore

store = RedisQueueStore.from_url("redis://localhost:6379/0")
app = create_app(store=store)
```

Run the host application's ASGI app as usual, for example:

```sh
uv run uvicorn queue_service:app --host 0.0.0.0 --port 8000
```

When a custom `store` is supplied, do not also pass `database_path`. The default `create_app()` configuration and `KINETIQ_DATABASE` environment variable apply only to SQLite.

## Built-in SQLite

SQLite is suitable for local development and single-host deployments where a local file is appropriate. KinetiQ initializes the schema and enables WAL mode at app startup. Set the file path with `database_path`:

```python
from kinetiq import create_app

app = create_app(database_path="/var/lib/kinetiq/queue.db")
```

Alternatively, set `KINETIQ_DATABASE` and call `create_app()` with no arguments. SQLite is not a distributed database; do not put its database file on a shared network filesystem to coordinate multiple service hosts.

## Adapter Contract

The public protocol is defined in [`../kinetiq/core/store.py`](../kinetiq/core/store.py). An adapter must implement these asynchronous methods:

| Method | Responsibility |
| --- | --- |
| `initialize()` | Prepare or validate schemas, tables, indexes, scripts, and connections. Called when the ASGI app starts. |
| `create_queue(...)` | Persist queue settings and return a mapping with `queue_name` and `created_at`. Raise `QueueAlreadyExistsError` for a duplicate and `QueueNotFoundError` if the configured DLQ does not exist. |
| `get_queue(queue_name)` | Return queue settings including `visibility_timeout`; raise `QueueNotFoundError` when absent. |
| `publish(...)` | Store the message and return its message ID. Enforce queue existence and deduplication when a deduplication ID is provided. |
| `claim_messages(...)` | Atomically claim up to the requested number of eligible messages, increment delivery counts, set visibility leases and fresh receipt handles, and return message mappings. |
| `acknowledge(...)` | Delete only the message currently associated with the receipt handle, in the named queue, while that lease is still valid. Return `False` for invalid or expired handles. |
| `route_exhausted_messages(...)` | Move expired messages that reached `max_receive_count` to the configured DLQ and return the number moved. A failed transfer must not lose the source message. |

Message mappings returned by `claim_messages` must include `message_id`, `receipt_handle`, `body`, `receive_count`, and `sent_at`. Raise the shared `QueueNotFoundError` and `QueueAlreadyExistsError` imported from `kinetiq.core.store` so the API can translate them into HTTP responses.

The most important correctness property is atomic claiming across concurrent service instances. A read followed by an unconditional write is not sufficient: two consumers could receive the same message. DLQ transfer must also be loss-safe, and acknowledgement must reject stale receipt handles after redelivery.

## Redis

**Prerequisites:** Redis with persistence and availability appropriate for the durability requirements, plus the host project's `redis` client dependency (for example, `redis[hiredis]`). Store the connection URL in a secret/environment variable, not in source control.

**Suggested layout:** queue settings in hashes; ready messages in sorted sets ordered by enqueue time; message payload and lease state in hashes. Use a Redis Lua script or another atomic server-side operation to select and lease messages, increment receive counts, and replace receipt handles. Perform a DLQ move atomically in one script. Configure Redis persistence, replication, backups, and eviction policy; an eviction policy that can remove queued messages is not appropriate for durable queues.

**What to add/change:** implement `RedisQueueStore` in the consuming project, map the above structures to every `QueueStore` method, construct it from the Redis URL, and pass it to `create_app(store=...)`. KinetiQ does not currently parse Redis URLs or create Redis clients automatically.

Illustrative host wiring (the adapter class is application-provided):

```python
import os
from redis.asyncio import Redis
from kinetiq import create_app
from my_service.storage import RedisQueueStore

redis_client = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
app = create_app(store=RedisQueueStore(redis_client))
```

The adapter should close its client during application shutdown. The current `QueueStore` protocol has `initialize()` but no `close()` hook, so manage cleanup through the host app's lifespan or add a lifecycle extension before relying on adapter-owned resources in production.

## Relational SQL

**Prerequisites:** a reachable database, credentials and migrations, plus an async driver such as `asyncpg` for PostgreSQL or an async SQLAlchemy setup. Keep credentials in environment variables or a secret manager.

**Suggested layout:** tables for queues and messages, with indexes on `(queue_name, visible_at, sent_at)` and a uniqueness constraint for queue-scoped deduplication IDs when they are present. Claim messages in a transaction using row locking, such as `SELECT ... FOR UPDATE SKIP LOCKED`, then update the lease and receipt handle before committing. Keep the exhausted-message transfer and source deletion in one transaction when both queues share the same database.

**What to add/change:** implement a `PostgresQueueStore` (or equivalent) with the adapter methods, apply migrations before serving traffic, build the store using the host project's database pool, and inject it into `create_app(store=store)`. No SQLAlchemy or PostgreSQL dependencies are required by KinetiQ itself.

Illustrative host wiring:

```python
from kinetiq import create_app
from my_service.storage import PostgresQueueStore

store = PostgresQueueStore.from_dsn_from_environment()
app = create_app(store=store)
```

The adapter factory in this example is application-provided. It should read `DATABASE_URL`, and the adapter's `initialize()` method should create the async pool and apply or verify schema migrations during app startup. As with Redis, the current protocol does not define a standard close hook; arrange pool cleanup in the host lifespan.

## NoSQL Database

NoSQL products differ significantly, so there is no single implementation strategy. For DynamoDB, a typical design uses a queue-settings table and a messages table keyed by queue name and message ID, with a status/visibility index for finding eligible messages.

**Prerequisites:** provisioned tables and indexes, an async-capable client or an executor strategy, IAM permissions limited to the required tables, and the host project's SDK dependency. For DynamoDB, use conditional updates or transactions to claim a message only if it is still visible and to rotate its receipt handle. Use a transaction for DLQ copy plus source removal where possible; account for transaction size limits when routing batches.

**What to add/change:** implement a `DynamoDBQueueStore` in the host project, provision and migrate tables/indexes, provide AWS credentials through the standard role/credential chain, and inject the adapter. Do not assume a database TTL feature will enforce visibility deadlines precisely; visibility eligibility must be checked by the claim operation itself.

Illustrative host wiring (the adapter and client setup are application-provided):

```python
from kinetiq import create_app
from my_service.storage import DynamoDBQueueStore, create_dynamodb_client

client = create_dynamodb_client()  # Uses the host's role/region configuration.
app = create_app(store=DynamoDBQueueStore(client, table_prefix="kinetiq-prod"))
```

The same contract can be implemented for MongoDB or another NoSQL system, but its claim and DLQ operations must have appropriate atomicity/transaction guarantees for the deployment's topology.

## S3 or Other Object Storage

Object storage is generally not a good sole queue backend. S3 stores objects but does not provide queue-native atomic claims, receipt-handle leases, ordered message groups, or transactions spanning a source queue and DLQ. Conditional object writes alone do not automatically provide the full coordination and recovery behavior the `QueueStore` contract requires.

If S3 is required, use it for durable message payloads and add a coordination/index store, such as DynamoDB, to atomically claim messages, track visibility leases, enforce deduplication, and record DLQ state. Make transfers recoverable: use an idempotent state machine or transactional outbox pattern so a crash between copying and deleting cannot lose or duplicate a message silently. For a managed queue with S3-backed payloads, consider using a queue service designed for that combination instead of implementing these guarantees from scratch.

**Prerequisites:** an S3 bucket, encryption and lifecycle policies, IAM permissions, and a coordination service with conditional writes/transactions. The host project must supply an async S3 client and implement the composite adapter.

Illustrative host wiring only; `S3QueueStore` is not included in KinetiQ:

```python
from kinetiq import create_app
from my_service.storage import S3QueueStore

store = S3QueueStore.from_environment(
    bucket="kinetiq-message-payloads",
    coordination_table="kinetiq-message-state",
)
app = create_app(store=store)
```

Do not use this configuration until the adapter has concurrency, crash-recovery, duplicate-delivery, and DLQ-transfer tests. For most deployments, Redis or a relational database is a simpler custom backend; SQLite remains the easiest built-in option for a single-host deployment.

## Testing a Custom Adapter

Before deploying an adapter, run the existing API tests against it and add backend-specific concurrency and failure tests. At minimum verify:

- Two concurrent claims never return the same active message.
- A message becomes available after its lease expires and receives a new receipt handle.
- An old receipt handle cannot acknowledge a redelivered message.
- Repeated publish calls with the same deduplication ID do not create duplicates.
- Message-group ordering remains intact when a message is leased or retried.
- DLQ routing survives failures between copy and source removal without message loss.
- Initialization is safe when multiple service workers start at the same time.
