# tests/e2e/fixtures/mock_llm.py
"""
Mock LLM Server Fixture for AutomataGrid E2E Testing.

Provides an offline, deterministic, OpenAI-compatible HTTP server implementing
the `/v1/chat/completions` endpoint.
Captures all prompt and request payloads for test assertion, and supports
canned actions, dynamic logic, and error injection (status codes, corrupt JSON, empty choices).
"""

import json
import logging
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable, List, Optional, Union

logger = logging.getLogger("mock_llm")


class _MockLLMRequestHandler(BaseHTTPRequestHandler):
    """Internal HTTP handler for mock OpenAI completions."""

    server: "MockLLMServer"  # Type annotation for reference

    def log_message(self, format, *args):
        # Suppress standard noisy console logging from BaseHTTPRequestHandler
        pass

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "Not found"}')
            return

        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)
        
        parsed_body = {}
        try:
            parsed_body = json.loads(raw_body.decode("utf-8"))
        except Exception:
            parsed_body = {"raw": raw_body.decode("utf-8", errors="ignore")}

        # Record incoming request
        self.server_obj.record_request({
            "path": self.path,
            "headers": dict(self.headers),
            "body": parsed_body,
            "timestamp": time.time(),
        })

        # Check for simulated artificial latency
        if self.server_obj.delay_seconds > 0:
            time.sleep(self.server_obj.delay_seconds)

        # Check for error status injection
        if self.server_obj.error_status is not None:
            self.send_response(self.server_obj.error_status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            err_payload = json.dumps({"error": f"Simulated HTTP {self.server_obj.error_status}"}).encode("utf-8")
            self.wfile.write(err_payload)
            return

        # Check for corrupt non-JSON body injection
        if self.server_obj.corrupt_body:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"CORRUPTED_NON_JSON_STREAM_500_UNPARSEABLE")
            return

        # Check for empty choices injection
        if self.server_obj.empty_choices:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {
                "id": "chatcmpl-mock-empty",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "mock-model",
                "choices": [],
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))
            return

        # Determine response action text
        action_text = self.server_obj.resolve_action(parsed_body)

        # Format standard OpenAI completion response
        resp = {
            "id": "chatcmpl-mock-id",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": parsed_body.get("model", "mock-model"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": action_text,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 15,
                "completion_tokens": 5,
                "total_tokens": 20,
            },
        }

        resp_bytes = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.end_headers()
        self.wfile.write(resp_bytes)


class MockLLMServer:
    """
    Offline Mock LLM Server running OpenAI-compatible completions endpoint.
    Operates in a background daemon thread with zero external dependencies.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.requested_port = port
        self.port: int = 0
        self.httpd: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None

        # Configuration options
        self.default_action: str = "x grid map"
        self.canned_responses: List[str] = []
        self.custom_handler: Optional[Callable[[dict], str]] = None

        # Error injection flags
        self.error_status: Optional[int] = None
        self.corrupt_body: bool = False
        self.empty_choices: bool = False
        self.delay_seconds: float = 0.0

        # Request history
        self.requests: List[dict] = []
        self._lock = threading.Lock()

    def start(self):
        """Start the HTTP server on a background daemon thread."""
        handler_class = _MockLLMRequestHandler
        self.httpd = HTTPServer((self.host, self.requested_port), handler_class)
        self.port = self.httpd.server_port
        # Set back-reference on handler
        handler_class.server_obj = self

        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        logger.info(f"[MockLLM] Server started at http://{self.host}:{self.port}")
        return self

    def stop(self):
        """Stop and shutdown the HTTP server."""
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        logger.info("[MockLLM] Server stopped.")

    def get_endpoint(self) -> str:
        """Returns the full completions URL."""
        return f"http://{self.host}:{self.port}/v1/chat/completions"

    @property
    def endpoint(self) -> str:
        return self.get_endpoint()

    def record_request(self, req_data: dict):
        with self._lock:
            self.requests.append(req_data)

    def enqueue_response(self, action_string: str):
        """Enqueue an action string to be returned by next request in FIFO order."""
        with self._lock:
            self.canned_responses.append(action_string)

    def resolve_action(self, parsed_body: dict) -> str:
        """Resolves what text response to return."""
        with self._lock:
            if self.custom_handler:
                return self.custom_handler(parsed_body)
            if self.canned_responses:
                return self.canned_responses.pop(0)
            return self.default_action

    def reset_state(self):
        """Resets canned responses, flags, and request logs."""
        with self._lock:
            self.requests.clear()
            self.canned_responses.clear()
            self.custom_handler = None
            self.error_status = None
            self.corrupt_body = False
            self.empty_choices = False
            self.delay_seconds = 0.0
            self.default_action = "x grid map"
