"""Test-suite safety net: prevent a real external network call from hanging the whole suite.

Motivation: the backend has many external clients (genai / Google Cloud Storage / Firestore / httpx
across app/repository.py, app/ai_client.py, app/rag/providers.py, ...). If any test path constructs a
real client and calls out WITHOUT a mock, the connection can block indefinitely and stall the entire
pytest run (observed in CI: an ~8-minute `futex`/socket hang with no visible progress).

This module installs two guardrails so a missing mock becomes a fast, clearly-attributed failure
instead of an invisible hang:

1. `_block_external_network` (autouse): any attempt to open a socket to a NON-local address raises
   immediately, naming the offending test, so you know exactly which test to mock. Localhost / UNIX
   sockets (FastAPI TestClient, local fixtures) are allowed. Socket-based clients (httpx/requests/REST)
   are covered; see guardrail 2 for transports that bypass Python sockets (e.g. grpc).
2. A default per-test timeout via `pytest-timeout` (configured in pytest.ini) is the transport-agnostic
   backstop: ANY test that blocks — including grpc/native calls the socket guard can't see — fails with
   a traceback after the timeout instead of hanging forever.

Eval tests (`tests/test_eval_*`) intentionally exercise real providers and are excluded from the default
/ CI suite, so they are exempt from the socket guard.
"""

import socket

import pytest

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0", "", "::"}


def _is_local(address) -> bool:
    # Non-tuple addresses (AF_UNIX str, etc.) are local by definition.
    if not isinstance(address, tuple) or not address:
        return True
    host = address[0]
    return host in _LOCAL_HOSTS


@pytest.fixture(autouse=True)
def _block_external_network(request):
    # Eval tests legitimately hit real providers; leave them untouched.
    if "eval" in request.node.nodeid:
        yield
        return

    def _guard(self, address, *args, **kwargs):
        if not _is_local(address):
            raise RuntimeError(
                f"External network call blocked in test '{request.node.nodeid}' → {address!r}. "
                "Mock the external client (genai / GCS / Firestore / httpx / requests) — a real "
                "network call can hang the whole test suite."
            )
        return _real_connect(self, address, *args, **kwargs)

    def _guard_ex(self, address, *args, **kwargs):
        if not _is_local(address):
            raise RuntimeError(
                f"External connect_ex blocked in test '{request.node.nodeid}' → {address!r}."
            )
        return _real_connect_ex(self, address, *args, **kwargs)

    socket.socket.connect = _guard
    socket.socket.connect_ex = _guard_ex
    try:
        yield
    finally:
        socket.socket.connect = _real_connect
        socket.socket.connect_ex = _real_connect_ex
