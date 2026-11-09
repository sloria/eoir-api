-- name: record_lookup
-- param: tenant str
-- param: ts str
-- param: outcome str
-- param: cached int
-- param: duration_ms int?
INSERT INTO lookups (tenant, ts, outcome, cached, duration_ms)
VALUES (?, ?, ?, ?, ?);

-- name: outcomes_since
-- param: tenant str
-- param: since str
SELECT outcome, count(*) AS count, min(ts) AS oldest
FROM lookups
WHERE tenant = ? AND ts > ? AND cached = 0
GROUP BY outcome;

-- name: prune_lookups
-- param: before str
DELETE FROM lookups WHERE ts < ?;

-- name: lookups
-- param: tenant str
-- param: before str?
-- param: after str?
-- param: limit int
-- A null bound makes its comparison null, which coalesce turns into true.
SELECT ts, outcome, cached, duration_ms
FROM lookups
WHERE tenant = ? AND coalesce(ts < ?, 1) AND coalesce(ts >= ?, 1)
ORDER BY ts DESC, id DESC
LIMIT ?;

-- name: lookups_after
-- param: tenant str
-- param: cursor str
-- param: before str?
-- param: limit int
SELECT ts, outcome, cached, duration_ms
FROM lookups
WHERE tenant = ? AND ts > ? AND coalesce(ts < ?, 1)
ORDER BY ts ASC, id ASC
LIMIT ?;

-- name: count_lookups
-- param: newer_than str?
-- param: tenant str
-- param: before str?
-- param: after str?
SELECT count(*) AS total, coalesce(sum(ts > ?), 0) AS newer
FROM lookups
WHERE tenant = ? AND coalesce(ts < ?, 1) AND coalesce(ts >= ?, 1);
