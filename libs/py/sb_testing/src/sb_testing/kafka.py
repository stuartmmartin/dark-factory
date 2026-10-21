"""Session-scoped real Apache Kafka (KRaft) for integration tests (T5, ADR-0009).

Kafka advertises the address clients must use, so the host port is chosen *before* start and
both published and advertised with the same number.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Iterator

import pytest
from confluent_kafka import KafkaException
from confluent_kafka.admin import AdminClient
from testcontainers.core.container import DockerContainer

IMAGE = "apache/kafka:4.1.0"
READY_TIMEOUT_SECONDS = 90
LOOPBACK = "127.0.0.1"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((LOOPBACK, 0))
        return int(sock.getsockname()[1])


def _wait_until_ready(bootstrap: str) -> None:
    """Poll one AdminClient until the broker answers; its handle dies when this returns."""
    admin = AdminClient({"bootstrap.servers": bootstrap})
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            admin.list_topics(timeout=2)
            return
        except KafkaException as exc:  # broker not ready yet
            last_error = exc
            time.sleep(1)  # container readiness poll, not test logic (T8 applies to tests)
    raise RuntimeError(f"Kafka not ready after {READY_TIMEOUT_SECONDS}s") from last_error


@pytest.fixture(scope="session")
def kafka_bootstrap() -> Iterator[str]:
    port = _free_port()
    container = (
        DockerContainer(IMAGE)
        .with_bind_ports(9092, port)
        .with_env("KAFKA_NODE_ID", "1")
        .with_env("KAFKA_PROCESS_ROLES", "broker,controller")
        .with_env("KAFKA_LISTENERS", "HOST://:9092,CONTROLLER://:9093")
        .with_env("KAFKA_ADVERTISED_LISTENERS", f"HOST://{LOOPBACK}:{port}")
        .with_env("KAFKA_LISTENER_SECURITY_PROTOCOL_MAP", "HOST:PLAINTEXT,CONTROLLER:PLAINTEXT")
        .with_env("KAFKA_CONTROLLER_QUORUM_VOTERS", "1@localhost:9093")
        .with_env("KAFKA_CONTROLLER_LISTENER_NAMES", "CONTROLLER")
        .with_env("KAFKA_INTER_BROKER_LISTENER_NAME", "HOST")
        .with_env("KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR", "1")
        .with_env("KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR", "1")
        .with_env("KAFKA_TRANSACTION_STATE_LOG_MIN_ISR", "1")
        .with_env("KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS", "0")
    )
    # Bind on loopback only: the broker is unauthenticated PLAINTEXT.
    container.ports["9092"] = (LOOPBACK, port)  # pyright: ignore[reportArgumentType]
    with container:
        bootstrap = f"{LOOPBACK}:{port}"
        _wait_until_ready(bootstrap)
        yield bootstrap
