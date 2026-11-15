"""Real HTTP + PostgreSQL assertions; run against isolated Compose or local test DB."""

import concurrent.futures
import os
import uuid

import httpx
import pytest

from loom.sdk import Client
from loom.signing import verify

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("TEST_URL"), reason="TEST_URL required"),
]
URL = os.getenv("TEST_URL", "http://localhost:8080")
ADMIN = os.getenv("ADMIN_KEY", "")


def call(method, path, token, body=None, **kwargs):
    return httpx.request(
        method, URL + path, headers={"Authorization": "Bearer " + token}, json=body, timeout=10, **kwargs
    )


def credential(tenant, actor, role):
    response = call("POST", "/admin/credentials", ADMIN, {"tenant": tenant, "actor": actor, "role": role})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def scope():
    tenant = "test-" + uuid.uuid4().hex[:12]
    author = credential(tenant, "alice", "author")["token"]
    reviewer = credential(tenant, "bob", "reviewer")["token"]
    reader = credential(tenant, "sdk", "reader")["token"]
    assert call("POST", "/v1/environments", author, {"name": "prod"}).status_code == 201
    return tenant, author, reviewer, reader


def propose(author, generation=0, rollout=10000):
    bundle = {"flags": [{"key": "checkout", "rollout": rollout, "salt": "v1"}]}
    response = call(
        "POST", "/v1/environments/prod/revisions", author, {"base_generation": generation, "bundle": bundle}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def action(ident, verb, token, body=None):
    return call("POST", f"/v1/environments/prod/revisions/{ident}/{verb}", token, body)


def test_full_release_rollback_sdk_and_audit(scope):
    tenant, author, reviewer, reader = scope
    first = propose(author)
    assert action(first, "activate", reviewer, {"expected_generation": 0}).status_code == 403
    assert action(first, "approve", reviewer).status_code == 200
    assert action(first, "approve", reviewer).status_code == 200  # idempotent approval, one audit event
    assert action(first, "activate", reviewer, {"expected_generation": 0}).json()["generation"] == 1
    snapshot = call("GET", "/v1/environments/prod/snapshot", reader)
    key = call("GET", "/v1/key", reader).json()["public_key"]
    assert verify(key, snapshot.json())["generation"] == 1
    sdk = Client(URL, reader, key, tenant + "/prod")
    assert sdk.refresh() and sdk.evaluate("checkout", "user")["value"]
    assert sdk.refresh()  # authenticated 304
    second = propose(author, 1, 0)
    assert action(second, "approve", reviewer).status_code == 200
    assert action(second, "activate", reviewer, {"expected_generation": 1}).status_code == 200
    assert sdk.refresh() and not sdk.evaluate("checkout", "user")["value"]
    assert (
        action(first, "activate", reviewer, {"expected_generation": 2, "rollback": True}).json()["generation"]
        == 3
    )
    assert sdk.refresh() and sdk.evaluate("checkout", "user")["value"]
    events = call("GET", "/v1/environments/prod/audit", reader).json()
    assert len(events) == 8
    assert events[-1]["event"]["action"] == "release.rolled_back"
    assert len({x["event"]["event_id"] for x in events}) == 8
    after = events[-2]["sequence"]
    assert len(call("GET", f"/v1/environments/prod/audit?after={after}", reader).json()) == 1


def test_concurrent_activation_single_winner(scope):
    _, author, reviewer, reader = scope
    ids = [propose(author) for _ in range(2)]
    for ident in ids:
        assert action(ident, "approve", reviewer).status_code == 200
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as workers:
        results = list(
            workers.map(
                lambda i: action(ids[i % 2], "activate", reviewer, {"expected_generation": 0}).status_code,
                range(8),
            )
        )
    assert results.count(200) == 1
    assert results.count(409) == 7
    assert call("GET", "/v1/environments", reader).json()[0]["generation"] == 1
    events = call("GET", "/v1/environments/prod/audit", reader).json()
    assert sum(e["event"]["action"] == "release.activated" for e in events) == 1


def test_roles_tenant_isolation_self_approval_revocation(scope):
    tenant, author, reviewer, reader = scope
    ident = propose(author)
    own_review = credential(tenant, "alice", "reviewer")["token"]
    assert action(ident, "approve", own_review).status_code == 403
    assert action(ident, "approve", author).status_code == 403
    assert action(ident, "approve", reader).status_code == 403
    other = credential("other-" + uuid.uuid4().hex[:8], "eve", "reviewer")["token"]
    assert action(ident, "approve", other).status_code == 404
    assert call("GET", "/v1/environments/prod/audit", other).status_code == 404
    assert call("GET", "/v1/environments", ADMIN).status_code == 401
    assert (
        call(
            "POST", "/admin/credentials", reader, {"tenant": tenant, "actor": "eve", "role": "reviewer"}
        ).status_code
        == 403
    )
    revocable = credential(tenant, "shortlived", "reader")
    assert call("DELETE", "/admin/credentials/" + revocable["id"], ADMIN).status_code == 204
    assert call("GET", "/v1/environments", revocable["token"]).status_code == 401
    assert call("GET", "/v1/environments", "wrong").status_code == 401


def test_stale_drafts_invalid_rollback_and_validation(scope):
    _, author, reviewer, reader = scope
    one, two = propose(author), propose(author)
    for ident in [one, two]:
        assert action(ident, "approve", reviewer).status_code == 200
    assert action(one, "activate", reviewer, {"expected_generation": 0}).status_code == 200
    assert action(two, "activate", reviewer, {"expected_generation": 1}).status_code == 409
    assert action(two, "activate", reviewer, {"expected_generation": 1, "rollback": True}).status_code == 409
    assert (
        call(
            "POST", "/v1/environments/prod/revisions", author, {"base_generation": 0, "bundle": {"flags": []}}
        ).status_code
        == 409
    )
    assert call("POST", "/v1/environments", author, {"name": "prod"}).status_code == 409
    assert call("POST", "/v1/environments", reader, {"name": "other"}).status_code == 403
    assert call("POST", "/v1/environments", author, {"name": "BAD SPACE"}).status_code == 422
    assert httpx.post(URL + "/v1/environments", content=b"x" * 65537).status_code == 413
    assert call("GET", "/v1/environments/prod/audit?after=-1", reader).status_code == 422


def test_preview_matches_signed_sdk(scope):
    tenant, author, reviewer, reader = scope
    ident = propose(author, rollout=3456)
    action(ident, "approve", reviewer).raise_for_status()
    action(ident, "activate", reviewer, {"expected_generation": 0}).raise_for_status()
    snapshot = call("GET", "/v1/environments/prod/snapshot", reader).json()
    key = call("GET", "/v1/key", reader).json()["public_key"]
    sdk = Client(URL, reader, key, tenant + "/prod")
    sdk.accept(snapshot)
    subjects = [f"u-{n}" for n in range(100)]
    preview = call(
        "POST",
        "/v1/environments/prod/preview",
        reader,
        {"bundle": snapshot["payload"]["bundle"], "flag": "checkout", "subjects": subjects},
    ).json()
    assert [r["value"] for r in preview] == [sdk.evaluate("checkout", s)["value"] for s in subjects]
