# Queue Flow Diagrams

These diagrams describe the current KinetiQ implementation. `QueueStore` is the backend contract; `SQLiteStorage` is the built-in implementation.

## Components

```mermaid
flowchart LR
    Client[API client] --> Routes[FastAPI queue routes]
    Routes --> Engine[QueueEngine]
    Engine -->|receive checks| DLQ[DeadLetterRouter]
    Engine --> Store[QueueStore protocol]
    DLQ -->|route_exhausted_messages| Store
    Store -. implemented by .-> SQLite[SQLiteStorage]
    SQLite --> DB[(SQLite database<br/>WAL mode)]
    Routes -->|HTTP errors and responses| Client
```

Routes translate HTTP requests and store errors. `QueueEngine` applies queue defaults, creates message metadata, and runs receive polling. Storage owns persistence and atomic queue operations. The DLQ router is called during receive processing and delegates the transfer to the store.

## Message Lifecycle

```mermaid
flowchart TD
    Send[POST message] --> Publish[QueueEngine.send_message]
    Publish --> Persist[store.publish<br/>visible_at = now, receive_count = 0]
    Persist --> Ready[Message is visible]

    Receive[GET messages] --> Load[Load queue settings]
    Load --> Loop[Receive polling loop]
    Loop --> Exhausted{Configured DLQ and<br/>expired receive_count >= max?}
    Exhausted -->|Yes| Move[Move message to DLQ<br/>within store transaction]
    Exhausted -->|No| Claim
    Move --> Claim[Atomically claim eligible messages]
    Claim --> Eligible{visible_at <= now and<br/>group ordering allows it?}
    Eligible -->|No messages| Wait{Long-poll deadline reached?}
    Wait -->|No| Loop
    Wait -->|Yes| Empty[Return empty list]
    Eligible -->|Message found| Lease[Increment receive_count;<br/>set fresh receipt_handle;<br/>visible_at = now + timeout]
    Lease --> Delivered[Return message and receipt handle]
    Delivered --> Ack[DELETE with receipt handle]
    Ack --> Valid{Handle matches and<br/>lease is still active?}
    Valid -->|Yes| Delete[Delete message]
    Valid -->|No| Reject[Return not found]
    Lease --> Expire[Lease expires; message becomes eligible again]
    Expire --> Receive
```

Receive uses the queue's visibility timeout unless the request overrides it. Long polling repeats the DLQ check and claim until a message is found or the wait deadline passes. An expired message at the retry limit is moved only when a DLQ is configured, and this happens on a subsequent receive pass. A message group cannot advance past an earlier message that is still present, including one under a visibility lease.

## Operations and Store Methods

```mermaid
flowchart TB
    subgraph Queue management
        Create[POST /queues] --> CreateM[create_queue]
        Details[GET /queues/name] --> GetM[get_queue]
        Timeout[PATCH /queues/name] --> UpdateM[update_queue_visibility_timeout]
        Configure[PUT /queues/name/dlq<br/>DELETE /queues/name/dlq] --> DlqM[configure_queue_dlq]
        Length[GET /queues/name/length] --> CountM[count_messages]
    end

    subgraph Message operations
        SendOp[POST /queues/name/messages] --> PublishM[publish]
        ReceiveOp[GET /queues/name/messages] --> GetQueue[get_queue]
        GetQueue --> RouteM[route_exhausted_messages]
        RouteM --> ClaimM[claim_messages]
        DeleteOp[DELETE /queues/name/messages] --> AckM[acknowledge]
    end

    Methods[QueueStore protocol] --> CreateM
    Methods --> GetM
    Methods --> UpdateM
    Methods --> DlqM
    Methods --> CountM
    Methods --> PublishM
    Methods --> RouteM
    Methods --> ClaimM
    Methods --> AckM
    Methods -. SQLite implementation .-> SQLite[SQLiteStorage]
```

| Store method | What it does |
| --- | --- |
| `initialize` | Creates the SQLite schema and enables WAL mode at app startup. |
| `create_queue` | Persists queue settings; validates a configured DLQ. |
| `get_queue` | Loads queue settings, including the default visibility timeout and DLQ. |
| `update_queue_visibility_timeout` | Changes the default timeout for future receives. |
| `configure_queue_dlq` | Sets or clears a DLQ and rejects missing queues or routing cycles. |
| `count_messages` | Counts every outstanding message, including leased messages. |
| `publish` | Inserts a message, or returns the existing ID for a matching queued deduplication ID. |
| `route_exhausted_messages` | Moves expired messages at the retry limit to the DLQ. |
| `claim_messages` | Atomically picks eligible messages, increments delivery counts, and issues leases and receipt handles. |
| `acknowledge` | Deletes a message only when its receipt handle is current and its lease has not expired. |