#!/usr/bin/env python3
"""Windows-loopback lobby-directory recorder for real game launches."""

from __future__ import annotations

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


MAX_BODY_BYTES = 1024 * 1024
MOD_UPDATE_RESPONSE = b'{"updates":[]}'
LOBBY_ANNOUNCE_RESPONSE = b'{"id":1,"expiresInSeconds":60}'


def _post_route(path: str) -> tuple[bytes | None, bool]:
    if path == "/api/mods/updates":
        return MOD_UPDATE_RESPONSE, True
    if path == "/api/lobbies/announce":
        return LOBBY_ANNOUNCE_RESPONSE, True
    return None, False


def _read_chunked_body(handler: BaseHTTPRequestHandler) -> bytes:
    body = bytearray()
    while True:
        size_line = handler.rfile.readline(128)
        if not size_line:
            raise ValueError("chunked request ended before a zero chunk")
        size_text = size_line.split(b";", 1)[0].strip()
        size = int(size_text, 16)
        if size == 0:
            while handler.rfile.readline(4096) not in (b"\r\n", b"\n", b""):
                pass
            return bytes(body)
        if len(body) + size > MAX_BODY_BYTES:
            raise ValueError("request body is too large")
        chunk = handler.rfile.read(size)
        if len(chunk) != size or handler.rfile.read(2) != b"\r\n":
            raise ValueError("invalid chunked request framing")
        body.extend(chunk)


def _read_request_body(handler: BaseHTTPRequestHandler) -> bytes:
    length_text = handler.headers.get("Content-Length")
    if length_text:
        length = int(length_text)
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("invalid request body length")
        return handler.rfile.read(length)
    if "chunked" in handler.headers.get("Transfer-Encoding", "").lower():
        return _read_chunked_body(handler)
    raise ValueError("request has no body framing")


def serve(port: int, events_path: Path, ready_path: Path, stop_path: Path) -> None:
    events_path.parent.mkdir(parents=True, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _record(self, method: str, body: Any = None) -> None:
            event: dict[str, Any] = {
                "method": method,
                "path": self.path,
                "receivedAtUnixSeconds": time.time(),
                "secretHeaderPresent": bool(
                    self.headers.get("X-SDR-Lobby-Secret")
                ),
            }
            if body is not None:
                event["body"] = body
            with events_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(event, separators=(",", ":")) + "\n")

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
            try:
                body = json.loads(_read_request_body(self).decode("utf-8"))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                self.send_error(400)
                return
            path = urlsplit(self.path).path
            response, record_body = _post_route(path)
            if record_body:
                self._record("POST", body)
            else:
                self._record("POST")
            if response is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
            self._record("DELETE")
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.timeout = 0.2
    ready_path.write_text(str(os.getpid()), encoding="ascii")
    try:
        while not stop_path.exists():
            server.handle_request()
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    parser.add_argument("--stop", type=Path, required=True)
    args = parser.parse_args()
    serve(args.port, args.events, args.ready, args.stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
