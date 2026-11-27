-- name: migrate-20261127120000-up
ALTER TABLE lookups ADD COLUMN request_id TEXT;

-- name: migrate-20261127120000-down
ALTER TABLE lookups DROP COLUMN request_id;
