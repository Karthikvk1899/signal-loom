CREATE TABLE IF NOT EXISTS schema_version (version integer PRIMARY KEY CHECK (version = 1));
INSERT INTO schema_version VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS credentials (
 id uuid PRIMARY KEY, tenant text NOT NULL, actor text NOT NULL,
 role text NOT NULL CHECK (role IN ('author','reviewer','reader')),
 key_hash text NOT NULL UNIQUE, revoked boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS environments (
 tenant text NOT NULL, name text NOT NULL, generation bigint NOT NULL DEFAULT 0,
 active_revision uuid, PRIMARY KEY (tenant,name)
);
CREATE TABLE IF NOT EXISTS revisions (
 id uuid PRIMARY KEY, tenant text NOT NULL, environment text NOT NULL,
 bundle jsonb NOT NULL, author text NOT NULL, base_generation bigint NOT NULL,
 status text NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','approved')),
 reviewer text, created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant,environment) REFERENCES environments(tenant,name)
);
CREATE INDEX IF NOT EXISTS revisions_scope ON revisions(tenant,environment,created_at DESC);
CREATE TABLE IF NOT EXISTS activations (
 tenant text NOT NULL, environment text NOT NULL, generation bigint NOT NULL,
 revision uuid NOT NULL REFERENCES revisions(id), envelope jsonb NOT NULL,
 PRIMARY KEY (tenant,environment,generation)
);
CREATE TABLE IF NOT EXISTS audit (
 sequence bigserial PRIMARY KEY, tenant text NOT NULL, environment text NOT NULL,
 event jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_scope ON audit(tenant,environment,sequence);
