# Using the Bruno Collection

The repository includes a Bruno collection for exercising KinetiQ's queue API. Its requests are at the collection root and cover queue creation, queue details, visibility-timeout updates, message publishing and receiving, queue length, and message acknowledgement.

## Start the API

From the repository root, start the development server:

```sh
uv run uvicorn kinetiq.main:app --reload
```

The collection's default `baseUrl` is `http://127.0.0.1:8000`. Keep the server running while using Bruno.

## Open the Collection

1. Open Bruno.
2. Open the repository's `bruno` directory as a collection.
3. Select the `local` environment before sending requests.

The `local` environment is defined in [`../bruno/environments/local.bru`](../bruno/environments/local.bru):

| Variable | Default | Purpose |
| --- | --- | --- |
| `baseUrl` | `http://127.0.0.1:8000` | KinetiQ API address |
| `queueName` | `kinetiq-hello-world` | Queue used by the example |

Change these values if the API is hosted at another address or the queue name is already in use.

## Run Hello World

Send the requests in this order, or run the collection so Bruno executes them by their sequence numbers:

1. **Create Queue** creates the queue using `queueName` and sets its visibility timeout to 30 seconds. Expected status: `201 Created`.
2. **Update Queue Visibility Timeout** changes the default timeout to 45 seconds. Expected status: `200 OK`.
3. **Get Queue Details** verifies the queue's settings, including the updated timeout. Expected status: `200 OK`.
4. **Send Message** publishes `Hello, world!` to the queue. Expected status: `200 OK`.
5. **Receive Message** waits up to five seconds for one message. Expected status: `200 OK`; the response is an array containing the message and its `receipt_handle`.
6. **Get Queue Length After Receive** returns `message_count: 1`, including the message with its active visibility lease. Expected status: `200 OK`.
7. **Delete Message** acknowledges the message using that receipt handle. Expected status: `204 No Content`.
8. **Get Queue Length After Delete** verifies the acknowledged message is no longer outstanding and returns `message_count: 0`. Expected status: `200 OK`.

The receive request's post-response script saves the first message's receipt handle as the runtime variable `receiptHandle`. The delete request uses that variable. Run Receive Message before Delete Message, and delete before the visibility lease expires. If receive returns an empty array, send a message and receive again. Queue length counts all outstanding messages, both visible and leased.

## Run It Again

Queue names must be unique. After the first successful run, change `queueName` in the `local` environment to a new value before running the collection again. Creating an existing queue returns `409 Conflict`.

## Add Screenshots

Capture each screenshot from the running KinetiQ collection in Bruno. Save the image files under `docs/images/bruno/`, then place each image immediately after the matching request description in **Run Hello World**:

| Request | Filename | Capture |
| --- | --- | --- |
| **Create Queue** | `01-create-queue.png` | The request and its `201 Created` response. |
| **Update Queue Visibility Timeout** | `02-update-visibility-timeout.png` | The PATCH request and its updated queue settings response. |
| **Get Queue Details** | `03-get-queue-details.png` | Queue metadata showing the updated timeout. |
| **Send Message** | `04-send-message.png` | The request and its `200 OK` response, including the returned message ID. |
| **Receive Message** | `05-receive-message.png` | The request and response showing `Hello, world!` and the `receipt_handle`. Crop or redact the handle if you do not want to publish a live receipt value. |
| **Get Queue Length After Receive** | `06-get-length-after-receive.png` | The response showing `message_count: 1` while the message is leased. |
| **Delete Message** | `07-delete-message.png` | The request and its successful `204 No Content` response. |
| **Get Queue Length After Delete** | `08-get-length-after-delete.png` | The response showing `message_count: 0` after acknowledgement. |

Use paths relative to this guide when embedding the images. Insert each line directly after its matching request description:

```markdown
![Bruno Create Queue request returning 201 Created](images/bruno/01-create-queue.png)
![Bruno visibility-timeout update](images/bruno/02-update-visibility-timeout.png)
![Bruno queue details showing the updated timeout](images/bruno/03-get-queue-details.png)
![Bruno Send Message request returning 200 OK](images/bruno/04-send-message.png)
![Bruno Receive Message response showing Hello, world!](images/bruno/05-receive-message.png)
![Bruno queue length showing one leased message](images/bruno/06-get-length-after-receive.png)
![Bruno Delete Message request returning 204 No Content](images/bruno/07-delete-message.png)
![Bruno queue length showing zero outstanding messages](images/bruno/08-get-length-after-delete.png)
```

Keep screenshots tightly cropped to the relevant Bruno request and response, and make sure they do not expose credentials or other private information.

## Request Files

| File | Operation |
| --- | --- |
| [`1 - Create Queue.bru`](../bruno/1%20-%20Create%20Queue.bru) | `POST /queues` |
| [`2 - Update Queue Visibility Timeout.bru`](../bruno/2%20-%20Update%20Queue%20Visibility%20Timeout.bru) | `PATCH /queues/{queue_name}` |
| [`3 - Get Queue Details.bru`](../bruno/3%20-%20Get%20Queue%20Details.bru) | `GET /queues/{queue_name}` |
| [`4 - Send Message.bru`](../bruno/4%20-%20Send%20Message.bru) | `POST /queues/{queue_name}/messages` |
| [`5 - Receive Message.bru`](../bruno/5%20-%20Receive%20Message.bru) | `GET /queues/{queue_name}/messages` |
| [`6 - Get Queue Length After Receive.bru`](../bruno/6%20-%20Get%20Queue%20Length%20After%20Receive.bru) | `GET /queues/{queue_name}/length` |
| [`7 - Delete Message.bru`](../bruno/7%20-%20Delete%20Message.bru) | `DELETE /queues/{queue_name}/messages` |
| [`8 - Get Queue Length After Delete.bru`](../bruno/8%20-%20Get%20Queue%20Length%20After%20Delete.bru) | `GET /queues/{queue_name}/length` |

For the same workflow using VS Code's REST Client extension, see [`../api_test.http`](../api_test.http).