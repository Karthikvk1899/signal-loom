import hashlib
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from psycopg.types.json import Jsonb
from psycopg_pool import PoolTimeout
from pydantic import Field

from loom.db import connection, pool
from loom.domain import Bundle, Name, StrictModel, Subject, canonical, evaluate
from loom.signing import load_private, public_key, sign

private = None
admin_key = ""


@asynccontextmanager
async def lifespan(_app):
    global private, admin_key
    admin_key = os.environ.get("ADMIN_KEY", "")
    if len(admin_key) < 32:
        raise RuntimeError("ADMIN_KEY must contain at least 32 characters")
    private = load_private(os.environ["SIGNING_KEY"])
    pool.open(wait=True, timeout=15)
    yield
    pool.close()


app = FastAPI(title="Signal Loom", version="0.1.0", lifespan=lifespan)


class BodyLimit:
    """Bound actual bytes, including chunked requests, before JSON parsing."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > 65536:
                return await JSONResponse({"detail": "body limit 65536 bytes"}, status_code=413)(scope, receive, send)
            chunks.append(message)
            if not message.get("more_body", False):
                break
        async def replay():
            return chunks.pop(0) if chunks else await receive()
        await self.app(scope, replay, send)


app.add_middleware(BodyLimit)


@app.middleware("http")
async def headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(psycopg.OperationalError)
@app.exception_handler(PoolTimeout)
async def unavailable(_request, _exc):
    return JSONResponse({"detail": "database unavailable; retry with backoff"}, status_code=503)


@app.exception_handler(psycopg.errors.UniqueViolation)
async def duplicate(_request, _exc):
    return JSONResponse({"detail": "resource already exists"}, status_code=409)


def bearer(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer ") or len(authorization) > 512:
        raise HTTPException(401, "bearer credential required")
    return authorization[7:]


def administrator(token: str = Depends(bearer)):
    if not secrets.compare_digest(token, admin_key):
        raise HTTPException(403, "bootstrap administrator required")


def principal(token: str = Depends(bearer)):
    with connection() as conn:
        actor = conn.execute("SELECT id,tenant,actor,role FROM credentials WHERE key_hash=%s AND NOT revoked",
                             (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if actor is None:
        raise HTTPException(401, "invalid or revoked credential")
    return actor


def require(actor, role):
    if actor["role"] != role:
        raise HTTPException(403, f"{role} credential required")


def environment(conn, tenant, name, lock=False):
    # Fixed queries; no caller-controlled SQL identifiers.
    query = ("SELECT * FROM environments WHERE tenant=%s AND name=%s FOR UPDATE" if lock
             else "SELECT * FROM environments WHERE tenant=%s AND name=%s")
    row = conn.execute(query, (tenant, name)).fetchone()
    if row is None:
        raise HTTPException(404, "environment not found")
    return row


def revision(conn, tenant, env, ident):
    row = conn.execute("SELECT * FROM revisions WHERE id=%s AND tenant=%s AND environment=%s",
                       (ident, tenant, env)).fetchone()
    if row is None:
        raise HTTPException(404, "revision not found")
    return row


def audit(conn, actor, env, action, **data):
    event = {"schema_version": 1, "event_id": str(uuid.uuid4()), "action": action,
             "actor": actor["actor"], "environment": env, **data}
    conn.execute("INSERT INTO audit(tenant,environment,event) VALUES (%s,%s,%s)",
                 (actor["tenant"], env, Jsonb(event)))


class CredentialInput(StrictModel):
    tenant: Name
    actor: Name
    role: Literal["author", "reviewer", "reader"]


@app.post("/admin/credentials", status_code=201, dependencies=[Depends(administrator)])
def create_credential(body: CredentialInput):
    token, ident = secrets.token_urlsafe(40), uuid.uuid4()
    with connection() as conn:
        conn.execute("INSERT INTO credentials(id,tenant,actor,role,key_hash) VALUES (%s,%s,%s,%s,%s)",
                     (ident, body.tenant, body.actor, body.role, hashlib.sha256(token.encode()).hexdigest()))
    return {"id": ident, "token": token, **body.model_dump()}


@app.delete("/admin/credentials/{ident}", status_code=204, dependencies=[Depends(administrator)])
def revoke_credential(ident: uuid.UUID):
    with connection() as conn:
        conn.execute("UPDATE credentials SET revoked=true WHERE id=%s", (ident,))


class EnvironmentInput(StrictModel):
    name: Name


@app.post("/v1/environments", status_code=201)
def create_environment(body: EnvironmentInput, actor=Depends(principal)):
    require(actor, "author")
    with connection() as conn:
        conn.execute("INSERT INTO environments(tenant,name) VALUES (%s,%s)", (actor["tenant"], body.name))
        audit(conn, actor, body.name, "environment.created")
    return {"name": body.name, "generation": 0}


@app.get("/v1/environments")
def list_environments(actor=Depends(principal)):
    with connection() as conn:
        return conn.execute("SELECT name,generation,active_revision FROM environments WHERE tenant=%s ORDER BY name LIMIT 100",
                            (actor["tenant"],)).fetchall()


class DraftInput(StrictModel):
    bundle: Bundle
    base_generation: int = Field(ge=0)


@app.post("/v1/environments/{env}/revisions", status_code=201)
def propose(env: Name, body: DraftInput, actor=Depends(principal)):
    require(actor, "author")
    ident = uuid.uuid4()
    with connection() as conn:
        current = environment(conn, actor["tenant"], env, lock=True)
        if current["generation"] != body.base_generation:
            raise HTTPException(409, "base generation is stale")
        conn.execute("""INSERT INTO revisions(id,tenant,environment,bundle,author,base_generation)
                     VALUES (%s,%s,%s,%s,%s,%s)""",
                     (ident, actor["tenant"], env, Jsonb(body.bundle.model_dump()), actor["actor"], body.base_generation))
        audit(conn, actor, env, "revision.proposed", revision=str(ident), base_generation=body.base_generation)
    return {"id": ident}


@app.get("/v1/environments/{env}/revisions")
def list_revisions(env: Name, actor=Depends(principal)):
    with connection() as conn:
        environment(conn, actor["tenant"], env)
        return conn.execute("""SELECT id,bundle,author,reviewer,status,base_generation,created_at FROM revisions
                            WHERE tenant=%s AND environment=%s ORDER BY created_at DESC,id LIMIT 100""",
                            (actor["tenant"], env)).fetchall()


@app.post("/v1/environments/{env}/revisions/{ident}/approve")
def approve(env: Name, ident: uuid.UUID, actor=Depends(principal)):
    require(actor, "reviewer")
    with connection() as conn:
        environment(conn, actor["tenant"], env, lock=True)
        draft = revision(conn, actor["tenant"], env, ident)
        if draft["author"] == actor["actor"]:
            raise HTTPException(403, "author cannot approve their own revision")
        if draft["status"] == "draft":
            conn.execute("UPDATE revisions SET status='approved',reviewer=%s WHERE id=%s", (actor["actor"], ident))
            audit(conn, actor, env, "revision.approved", revision=str(ident))
    return {"id": ident, "status": "approved"}


class ActivateInput(StrictModel):
    expected_generation: int = Field(ge=0)
    rollback: bool = False


@app.post("/v1/environments/{env}/revisions/{ident}/activate")
def activate(env: Name, ident: uuid.UUID, body: ActivateInput, actor=Depends(principal)):
    require(actor, "reviewer")
    with connection() as conn:
        state = environment(conn, actor["tenant"], env, lock=True)
        draft = revision(conn, actor["tenant"], env, ident)
        if state["generation"] != body.expected_generation:
            raise HTTPException(409, "generation conflict; reload before retry")
        if draft["status"] != "approved" or draft["author"] == actor["actor"]:
            raise HTTPException(403, "independently approved revision required")
        if body.rollback:
            previous = conn.execute("SELECT 1 FROM activations WHERE tenant=%s AND environment=%s AND revision=%s LIMIT 1",
                                    (actor["tenant"], env, ident)).fetchone()
            if not previous:
                raise HTTPException(409, "rollback target was never activated")
        elif draft["base_generation"] != state["generation"]:
            raise HTTPException(409, "revision based on stale generation; propose again")
        generation = state["generation"] + 1
        payload = {"schema_version": 1, "environment": f'{actor["tenant"]}/{env}',
                   "generation": generation, "revision": str(ident), "bundle": draft["bundle"]}
        envelope = sign(private, payload)
        conn.execute("INSERT INTO activations(tenant,environment,generation,revision,envelope) VALUES (%s,%s,%s,%s,%s)",
                     (actor["tenant"], env, generation, ident, Jsonb(envelope)))
        conn.execute("UPDATE environments SET generation=%s,active_revision=%s WHERE tenant=%s AND name=%s",
                     (generation, ident, actor["tenant"], env))
        audit(conn, actor, env, "release.rolled_back" if body.rollback else "release.activated",
              generation=generation, revision=str(ident))
    return {"generation": generation, "revision": ident}


@app.get("/v1/environments/{env}/snapshot")
def snapshot(env: Name, if_none_match: str = Header(default=""), actor=Depends(principal)):
    with connection() as conn:
        # One statement joins pointer and immutable activation from one MVCC snapshot.
        row = conn.execute("""SELECT a.envelope,e.generation FROM environments e JOIN activations a
            ON a.tenant=e.tenant AND a.environment=e.name AND a.generation=e.generation
            WHERE e.tenant=%s AND e.name=%s""", (actor["tenant"], env)).fetchone()
    if row is None:
        raise HTTPException(404, "no active release")
    etag = '"' + hashlib.sha256(canonical(row["envelope"])).hexdigest() + '"'
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return JSONResponse(row["envelope"], headers={"ETag": etag})


class PreviewInput(StrictModel):
    bundle: Bundle
    flag: Name
    subjects: list[Subject] = Field(min_length=1, max_length=100)


@app.post("/v1/environments/{env}/preview")
def preview(env: Name, body: PreviewInput, actor=Depends(principal)):
    with connection() as conn:
        environment(conn, actor["tenant"], env)
    return [evaluate(body.bundle, f'{actor["tenant"]}/{env}', body.flag, subject) for subject in body.subjects]


@app.get("/v1/environments/{env}/audit")
def history(env: Name, after: Annotated[int, Query(ge=0)] = 0, actor=Depends(principal)):
    with connection() as conn:
        environment(conn, actor["tenant"], env)
        return conn.execute("""SELECT sequence,event,created_at FROM audit
            WHERE tenant=%s AND environment=%s AND sequence>%s ORDER BY sequence LIMIT 100""",
                            (actor["tenant"], env, after)).fetchall()


@app.get("/v1/key", dependencies=[Depends(principal)])
def key():
    return {"algorithm": "Ed25519", "public_key": public_key(private)}


@app.get("/health/live")
def live():
    return {"status": "up"}


@app.get("/health/ready")
def ready():
    with connection() as conn:
        conn.execute("SELECT version FROM schema_version WHERE version=1").fetchone()
    return {"status": "ready"}
