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