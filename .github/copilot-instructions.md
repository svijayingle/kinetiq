# Copilot Instructions

## Project Structure

Keep the project organized as follows:

```text
KinetiQ/
├── openapi.yaml               # Source-of-truth API specification
├── pyproject.toml             # Project metadata and uv dependencies
├── uv.lock                    # Locked dependency versions
├── kinetiq/
│   ├── __init__.py
│   ├── main.py                # FastAPI entry point
│   ├── models.py              # Pydantic schemas generated from the spec
│   ├── core/
│   │   ├── queue_engine.py    # Visibility timeout and long polling logic
│   │   ├── storage.py         # SQLite WAL persistence layer
│   │   └── dlq.py             # Dead-letter queue routing
│   └── routes/
│       └── queues.py          # Route handlers matching operationIds
├── tests/
│   └── test_queue.py          # Integration and unit tests
└── api_test.http              # VS Code REST Client requests
```

## Development Rules

- Treat `openapi.yaml` as the source of truth for the HTTP API. Update it before or alongside implementation changes that affect endpoints, parameters, schemas, or responses.
- Use `uv` to manage dependencies. Declare runtime dependencies in `pyproject.toml` and commit the generated `uv.lock` file; do not maintain a separate `requirements.txt` unless deployment specifically requires one.
- Keep `datamodel-code-generator` in the development dependency group and regenerate schemas with `uv run datamodel-codegen --input openapi.yaml --output kinetiq/models.py` after API schema changes.
- Keep FastAPI routes in `kinetiq/routes/queues.py` aligned with the specification's `operationId` values: `create_queue`, `send_message`, `receive_messages`, and `delete_message`.
- Keep request and response schemas in `kinetiq/models.py` generated from the OpenAPI specification. Do not manually introduce schema behavior that conflicts with the specification.
- Keep message delivery behavior, visibility leases, and long polling in `kinetiq/core/queue_engine.py`; persistence and SQLite WAL behavior in `kinetiq/core/storage.py`; and dead-letter routing in `kinetiq/core/dlq.py`.
- Keep `kinetiq/main.py` focused on application setup and router registration.
- Use the declared runtime dependencies in `pyproject.toml`: FastAPI, Uvicorn, Pydantic, and aiosqlite. Avoid adding dependencies unless the feature requires them.
- Add or update tests in `tests/test_queue.py` for API contract changes and queue behavior, including visibility timeout, long polling, retry limits, and DLQ routing when relevant.
- Keep `api_test.http` examples consistent with the current API contract so they can be run with the VS Code REST Client extension.
- Prefer small, focused changes that preserve the separation between routes, queue logic, persistence, and DLQ handling.