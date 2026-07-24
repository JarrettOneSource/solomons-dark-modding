#!/usr/bin/env python3
"""Proxy a local UDP pair with deterministic one-way latency and jitter."""

from __future__ import annotations

import argparse
import heapq
import json
import random
import select
import socket
import time
from pathlib import Path


def endpoint(value: str) -> tuple[str, int]:
    host, separator, port_text = value.rpartition(":")
    if not separator or not host:
        raise argparse.ArgumentTypeError(
            f"expected HOST:PORT, got {value!r}"
        )
    try:
        port = int(port_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid port in {value!r}"
        ) from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(
            f"port is out of range in {value!r}"
        )
    return host, port


def endpoint_text(value: tuple[str, int]) -> str:
    return f"{value[0]}:{value[1]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-proxy", type=endpoint, required=True)
    parser.add_argument("--host-game", type=endpoint, required=True)
    parser.add_argument("--client-proxy", type=endpoint, required=True)
    parser.add_argument("--client-game", type=endpoint, required=True)
    parser.add_argument("--latency-ms", type=float, required=True)
    parser.add_argument("--jitter-ms", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, required=True)
    args = parser.parse_args()
    if args.latency_ms < 0.0:
        parser.error("--latency-ms must not be negative")
    if args.jitter_ms < 0.0:
        parser.error("--jitter-ms must not be negative")

    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    args.stop_file.parent.mkdir(parents=True, exist_ok=True)
    args.stop_file.unlink(missing_ok=True)

    host_proxy = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_proxy = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    host_proxy.bind(args.host_proxy)
    client_proxy.bind(args.client_proxy)
    host_proxy.setblocking(False)
    client_proxy.setblocking(False)

    rng = random.Random(args.seed)
    pending: list[
        tuple[
            float,
            int,
            socket.socket,
            tuple[str, int],
            bytes,
            str,
        ]
    ] = []
    schedule_sequence = 0
    started = time.monotonic()
    metrics: dict[str, object] = {
        "schema": "sd-local-udp-latency-proxy-v1",
        "host_proxy": endpoint_text(args.host_proxy),
        "host_game": endpoint_text(args.host_game),
        "client_proxy": endpoint_text(args.client_proxy),
        "client_game": endpoint_text(args.client_game),
        "latency_ms": args.latency_ms,
        "jitter_ms": args.jitter_ms,
        "seed": args.seed,
        "host_to_client_received": 0,
        "host_to_client_sent": 0,
        "client_to_host_received": 0,
        "client_to_host_sent": 0,
        "maximum_pending_datagrams": 0,
        "socket_errors": [],
    }

    def schedule(
        send_socket: socket.socket,
        target: tuple[str, int],
        payload: bytes,
        direction: str,
    ) -> None:
        nonlocal schedule_sequence
        jitter_ms = rng.uniform(-args.jitter_ms, args.jitter_ms)
        delay_seconds = max(0.0, args.latency_ms + jitter_ms) / 1000.0
        schedule_sequence += 1
        heapq.heappush(
            pending,
            (
                time.monotonic() + delay_seconds,
                schedule_sequence,
                send_socket,
                target,
                payload,
                direction,
            ),
        )
        metrics["maximum_pending_datagrams"] = max(
            int(metrics["maximum_pending_datagrams"]),
            len(pending),
        )

    print(
        "proxy_ready "
        f"host={endpoint_text(args.host_proxy)} "
        f"client={endpoint_text(args.client_proxy)}",
        flush=True,
    )
    try:
        while not args.stop_file.exists():
            now = time.monotonic()
            while pending and pending[0][0] <= now:
                (
                    _,
                    _,
                    send_socket,
                    target,
                    payload,
                    direction,
                ) = heapq.heappop(pending)
                try:
                    send_socket.sendto(payload, target)
                    key = f"{direction}_sent"
                    metrics[key] = int(metrics[key]) + 1
                except OSError as exc:
                    errors = metrics["socket_errors"]
                    assert isinstance(errors, list)
                    if len(errors) < 20:
                        errors.append(str(exc))

            timeout = 0.01
            if pending:
                timeout = min(
                    timeout,
                    max(0.0, pending[0][0] - time.monotonic()),
                )
            readable, _, _ = select.select(
                [host_proxy, client_proxy],
                [],
                [],
                timeout,
            )
            for source in readable:
                try:
                    payload, _ = source.recvfrom(65535)
                except OSError as exc:
                    errors = metrics["socket_errors"]
                    assert isinstance(errors, list)
                    if len(errors) < 20:
                        errors.append(str(exc))
                    continue
                if source is host_proxy:
                    metrics["host_to_client_received"] = (
                        int(metrics["host_to_client_received"]) + 1
                    )
                    schedule(
                        client_proxy,
                        args.client_game,
                        payload,
                        "host_to_client",
                    )
                else:
                    metrics["client_to_host_received"] = (
                        int(metrics["client_to_host_received"]) + 1
                    )
                    schedule(
                        host_proxy,
                        args.host_game,
                        payload,
                        "client_to_host",
                    )
    finally:
        host_proxy.close()
        client_proxy.close()
        metrics["pending_datagrams_at_stop"] = len(pending)
        metrics["duration_seconds"] = time.monotonic() - started
        args.metrics.write_text(
            json.dumps(metrics, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
