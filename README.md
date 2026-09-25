# KinetiQ

KinetiQ is an SQS-inspired message queue API built with FastAPI and SQLite WAL persistence. It supports visibility leases, long polling, message groups, deduplication, and dead-letter queue routing.

## Install and Host KinetiQ

After a release is published to PyPI, add KinetiQ to another project with:

```sh
uv add kinetiq
```

Or install it with pip:

```sh
python -m pip install kinetiq
```

Create an ASGI application from your project's module and run it with an ASGI server:

```python
# queue_service.py
from kinetiq import create_app

app = create_app(database_path="./kinetiq.db")
```

```sh
uv run uvicorn queue_service:app --host 0.0.0.0 --port 8000
```

`create_app()` accepts an optional SQLite database path. If omitted, it uses `KINETIQ_DATABASE`, then defaults to `kinetiq.db` in the current working directory. The package includes FastAPI and its runtime dependencies; the consuming project only needs to provide an ASGI server if it wants to run the service with one other than Uvicorn.

Until the first PyPI release is published, KinetiQ can also be installed directly from the repository:

```sh
uv add git+https://github.com/<owner>/<repository>.git
```

## Development Requirements

- Python 3.10 or newer
- [uv](https://docs.astral.sh/uv/)

The development and CI Python version is pinned in [.python-version](.python-version).

## Setup

Install the locked runtime and development dependencies:

```sh
uv sync --locked --all-groups
```

Start the API locally:

```sh
uv run uvicorn kinetiq.main:app --reload
```

The API listens at `http://127.0.0.1:8000`. Interactive OpenAPI documentation is available at `http://127.0.0.1:8000/docs`; the source contract is in [openapi.yaml](openapi.yaml).

## Configuration

By default, KinetiQ stores data in `kinetiq.db` in the current working directory. Set `KINETIQ_DATABASE` to use another SQLite file.

PowerShell:

```powershell
$env:KINETIQ_DATABASE = "C:\data\kinetiq.db"
uv run uvicorn kinetiq.main:app --reload
```

macOS or Linux:

```sh
KINETIQ_DATABASE=/var/lib/kinetiq/kinetiq.db uv run uvicorn kinetiq.main:app --reload
```

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/queues` | Create a queue |
| `POST` | `/queues/{queue_name}/messages` | Publish a message |
| `GET` | `/queues/{queue_name}/messages` | Receive messages |
| `DELETE` | `/queues/{queue_name}/messages` | Acknowledge a message using its receipt handle |

Create a queue with `queue_name`; optional settings include `visibility_timeout`, `max_receive_count`, and `dlq_name`. Create a dead-letter queue first if a source queue will reference it.

Publish a JSON body containing a string `body`. Optional `deduplication_id` and `message_group_id` values enable duplicate suppression for queued messages and ordered delivery within a message group.

Receive supports `max_messages` (1-10), an optional `visibility_timeout` override, and `wait_time_seconds` (0-20). When no override is supplied, the queue's configured visibility timeout is used. Each delivery includes a `receipt_handle`; submit it to the delete endpoint before the lease expires to acknowledge the message. After `max_receive_count` deliveries, an expired message is moved to its configured dead-letter queue on a subsequent receive request.

See [api_test.http](api_test.http) for runnable VS Code REST Client examples.

## Development

Run the API and integration tests:

```sh
uv run pytest -q
```

Build the installable source distribution and wheel:

```sh
uv build
```

Regenerate Pydantic models after changing the OpenAPI schemas:

```sh
uv run datamodel-codegen --input openapi.yaml --output kinetiq/models.py
```

The CI workflow runs the tests on pull requests and pushes to `main`.
