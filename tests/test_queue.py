import time

import pytest
from fastapi.testclient import TestClient

from kinetiq import QueueStore, SQLiteStorage, create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "queue-test.db")
    with TestClient(app) as test_client:
        yield test_client


def create_queue(client, queue_name="orders"):
    response = client.post("/queues", json={"queue_name": queue_name})
    assert response.status_code == 201
    return response.json()


def send_message(client, queue_name, body="payload", **extra):
    return client.post(
        f"/queues/{queue_name}/messages", json={"body": body, **extra}
    )


def test_create_send_receive_and_acknowledge(client):
    created = create_queue(client)
    assert created["queue_name"] == "orders"
    assert created["created_at"]

    published = send_message(client, "orders", "hello")
    assert published.status_code == 200
    assert published.json()["md5_checksum"] == "5d41402abc4b2a76b9719d911017c592"

    received = client.get("/queues/orders/messages").json()
    assert len(received) == 1
    assert received[0]["body"] == "hello"
    assert received[0]["receive_count"] == 1

    acknowledged = client.request(
        "DELETE",
        "/queues/orders/messages",
        json={"receipt_handle": received[0]["receipt_handle"]},
    )
    assert acknowledged.status_code == 204
    assert client.get("/queues/orders/messages").json() == []


def test_queue_details_and_visibility_timeout_update(client):
    client.post(
        "/queues",
        json={
            "queue_name": "managed",
            "visibility_timeout": 20,
            "max_receive_count": 3,
        },
    )

    details = client.get("/queues/managed")
    assert details.status_code == 200
    assert details.json()["queue_name"] == "managed"
    assert details.json()["visibility_timeout"] == 20
    assert details.json()["max_receive_count"] == 3
    assert details.json()["dlq_name"] is None

    updated = client.patch(
        "/queues/managed", json={"visibility_timeout": 45}
    )
    assert updated.status_code == 200
    assert updated.json()["visibility_timeout"] == 45
    assert client.get("/queues/managed").json()["visibility_timeout"] == 45


def test_queue_length_counts_outstanding_messages_including_leased(client):
    create_queue(client, "counted")
    assert client.get("/queues/counted/length").json() == {
        "queue_name": "counted",
        "message_count": 0,
    }
    send_message(client, "counted", "first")
    send_message(client, "counted", "second")
    assert client.get("/queues/counted/length").json()["message_count"] == 2

    received = client.get("/queues/counted/messages?max_messages=1").json()[0]
    assert client.get("/queues/counted/length").json()["message_count"] == 2

    acknowledged = client.request(
        "DELETE",
        "/queues/counted/messages",
        json={"receipt_handle": received["receipt_handle"]},
    )
    assert acknowledged.status_code == 204
    assert client.get("/queues/counted/length").json()["message_count"] == 1


def test_queue_management_endpoints_validate_missing_queues_and_timeout(client):
    assert client.get("/queues/missing").status_code == 404
    assert client.get("/queues/missing/length").status_code == 404
    assert client.patch(
        "/queues/missing", json={"visibility_timeout": 10}
    ).status_code == 404

    create_queue(client, "validated")
    assert client.patch(
        "/queues/validated", json={"visibility_timeout": -1}
    ).status_code == 422


def test_visibility_lease_expires_and_old_receipt_is_rejected(client):
    client.post(
        "/queues",
        json={"queue_name": "leases", "visibility_timeout": 1},
    )
    send_message(client, "leases")
    first = client.get("/queues/leases/messages").json()[0]
    assert client.get("/queues/leases/messages").json() == []

    time.sleep(1.05)
    expired_ack = client.request(
        "DELETE",
        "/queues/leases/messages",
        json={"receipt_handle": first["receipt_handle"]},
    )
    assert expired_ack.status_code == 404

    redelivery = client.get("/queues/leases/messages").json()[0]
    assert redelivery["receive_count"] == 2
    assert redelivery["receipt_handle"] != first["receipt_handle"]


def test_message_group_preserves_order(client):
    create_queue(client, "fifo")
    send_message(client, "fifo", "first", message_group_id="group-a")
    send_message(client, "fifo", "second", message_group_id="group-a")

    first = client.get("/queues/fifo/messages?max_messages=10").json()
    assert [message["body"] for message in first] == ["first"]
    assert client.get("/queues/fifo/messages").json() == []

    client.request(
        "DELETE",
        "/queues/fifo/messages",
        json={"receipt_handle": first[0]["receipt_handle"]},
    )
    second = client.get("/queues/fifo/messages").json()
    assert [message["body"] for message in second] == ["second"]


def test_long_poll_waits_for_message_availability(client):
    create_queue(client, "empty")
    started = time.monotonic()
    response = client.get("/queues/empty/messages?wait_time_seconds=1")
    elapsed = time.monotonic() - started

    assert response.status_code == 200
    assert response.json() == []
    assert elapsed >= 0.9


def test_exhausted_message_is_moved_to_dead_letter_queue(client):
    client.post(
        "/queues",
        json={"queue_name": "dead-letters", "visibility_timeout": 0},
    )
    client.post(
        "/queues",
        json={
            "queue_name": "source",
            "visibility_timeout": 0,
            "max_receive_count": 1,
            "dlq_name": "dead-letters",
        },
    )
    send_message(client, "source", "poison")

    first_delivery = client.get("/queues/source/messages").json()
    assert first_delivery[0]["receive_count"] == 1
    assert client.get("/queues/source/messages").json() == []

    dead_letter = client.get("/queues/dead-letters/messages").json()
    assert len(dead_letter) == 1
    assert dead_letter[0]["body"] == "poison"


def test_dlq_can_be_configured_after_queue_creation_and_routes_messages(client):
    create_queue(client, "parking-lot")
    client.post(
        "/queues",
        json={
            "queue_name": "source-after-create",
            "visibility_timeout": 0,
            "max_receive_count": 1,
        },
    )

    configured = client.put(
        "/queues/source-after-create/dlq", json={"dlq_name": "parking-lot"}
    )
    assert configured.status_code == 200
    assert configured.json()["dlq_name"] == "parking-lot"

    send_message(client, "source-after-create", "after configuration")
    first_delivery = client.get("/queues/source-after-create/messages").json()
    assert first_delivery[0]["receive_count"] == 1
    assert client.get("/queues/source-after-create/messages").json() == []

    dead_letter = client.get("/queues/parking-lot/messages").json()
    assert [message["body"] for message in dead_letter] == ["after configuration"]


def test_dlq_configuration_validates_targets_and_cycles_and_can_be_cleared(client):
    create_queue(client, "queue-a")
    client.post(
        "/queues", json={"queue_name": "queue-b", "dlq_name": "queue-a"}
    )

    assert client.delete("/queues/missing/dlq").status_code == 404
    assert client.put(
        "/queues/queue-a/dlq", json={"dlq_name": "missing"}
    ).status_code == 404
    assert client.put(
        "/queues/queue-a/dlq", json={"dlq_name": "queue-a"}
    ).status_code == 409
    assert client.put(
        "/queues/queue-a/dlq", json={"dlq_name": "queue-b"}
    ).status_code == 409
    assert client.post(
        "/queues", json={"queue_name": "self-dlq", "dlq_name": "self-dlq"}
    ).status_code == 409

    cleared = client.delete("/queues/queue-b/dlq")
    assert cleared.status_code == 200
    assert cleared.json()["dlq_name"] is None


def test_duplicate_queue_and_unknown_queue_responses(client):
    create_queue(client, "unique")
    assert client.post("/queues", json={"queue_name": "unique"}).status_code == 409
    assert send_message(client, "missing").status_code == 404


def test_store_can_be_injected_through_public_factory(tmp_path):
    store = SQLiteStorage(tmp_path / "injected-store.db")
    assert isinstance(store, QueueStore)

    with TestClient(create_app(store=store)) as client:
        response = client.post("/queues", json={"queue_name": "injected"})

    assert response.status_code == 201


def test_custom_store_and_sqlite_path_are_mutually_exclusive(tmp_path):
    store = SQLiteStorage(tmp_path / "injected-store.db")

    with pytest.raises(ValueError, match="either 'store' or 'database_path'"):
        create_app(tmp_path / "another.db", store=store)