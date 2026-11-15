from copy import deepcopy

import httpx
import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from loom.sdk import Client
from loom.signing import public_key, sign


@pytest.fixture
def setup():
    private = Ed25519PrivateKey.generate()
    now = [0]
    client = Client("http://localhost:8080", "token", public_key(private), "acme/prod", 10, lambda: now[0])
    payload = {"schema_version": 1, "environment": "acme/prod", "generation": 1,
               "bundle": {"flags": [{"key": "checkout", "salt": "v1", "rollout": 10000}]}}
    return private, now, client, payload


def test_verified_cache_expires_at_boundary(setup):
    private, now, client, payload = setup
    assert client.evaluate("checkout", "x")["reason"] == "stale"
    client.accept(sign(private, payload))
    now[0] = 9.99
    assert client.evaluate("checkout", "x")["value"]
    now[0] = 10
    assert not client.evaluate("checkout", "x")["value"]
    assert client.evaluate("checkout", "x", default=True)["value"]


def test_tampering_and_wrong_key(setup):
    private, _, client, payload = setup
    envelope = sign(private, payload)
    envelope["payload"] = deepcopy(payload)
    envelope["payload"]["generation"] = 999
    with pytest.raises(InvalidSignature):
        client.accept(envelope)
    with pytest.raises(InvalidSignature):
        client.accept(sign(Ed25519PrivateKey.generate(), payload))
    assert client.evaluate("checkout", "x")["reason"] == "stale"


def test_scope_regression_and_equivocation(setup):
    private, _, client, payload = setup
    client.accept(sign(private, payload))
    for bad in [{**payload, "environment": "other/prod"}, {**payload, "generation": 0},
                {**payload, "generation": True}, {**payload, "bundle": {"flags": []}}]:
        with pytest.raises(ValueError):
            client.accept(sign(private, bad))
    assert client.evaluate("checkout", "x")["value"]


def test_transport_failure_does_not_extend_freshness(setup, monkeypatch):
    private, now, client, payload = setup
    client.accept(sign(private, payload))
    def fail(*args, **kwargs):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(httpx, "get", fail)
    now[0] = 9
    assert not client.refresh()
    now[0] = 10
    assert client.evaluate("checkout", "x")["reason"] == "stale"


def test_etag_refresh_and_corrupt_response(setup, monkeypatch):
    private, now, client, payload = setup
    responses = [httpx.Response(200, json=sign(private, payload), headers={"etag": '"one"'},
                               request=httpx.Request("GET", "http://localhost")),
                 httpx.Response(304), httpx.Response(200, json={"bad": True},
                                                    request=httpx.Request("GET", "http://localhost"))]
    def get(url, headers, **kwargs):
        assert url.endswith("/v1/environments/prod/snapshot")
        if len(responses) < 3:
            assert headers["If-None-Match"] == '"one"'
        return responses.pop(0)
    monkeypatch.setattr(httpx, "get", get)
    assert client.refresh()
    now[0] = 9
    assert client.refresh()
    now[0] = 18
    assert not client.refresh()
    assert client.evaluate("checkout", "x")["value"]
    now[0] = 19
    assert client.evaluate("checkout", "x")["reason"] == "stale"
