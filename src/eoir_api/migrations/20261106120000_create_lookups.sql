-- name: migrate-20261106120000-up
CREATE TABLE lookups (
    id INTEGER PRIMARY KEY,
    tenant TEXT NOT NULL,
    ts TEXT NOT NULL, -- ISO 8601 UTC
    a_number_last_4 TEXT NOT NULL,
    outcome TEXT NOT NULL,
    cached INTEGER NOT NULL,
    duration_ms INTEGER -- NULL for cache hits
);
CREATE INDEX lookups_tenant_ts ON lookups (tenant, ts);

-- name: migrate-20261106120000-down
DROP TABLE lookups;
