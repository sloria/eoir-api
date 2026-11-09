-- name: migrate-20261108120000-up
ALTER TABLE lookups DROP COLUMN a_number_last_4;

-- name: migrate-20261108120000-down
ALTER TABLE lookups ADD COLUMN a_number_last_4 TEXT NOT NULL DEFAULT '';
