-- name: record_lookup
-- param: tenant str
-- param: ts str
-- param: a_number_last_4 str
-- param: outcome str
-- param: cached int
-- param: duration_ms int?
INSERT INTO lookups (tenant, ts, a_number_last_4, outcome, cached, duration_ms)
VALUES (?, ?, ?, ?, ?, ?);

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
SELECT ts, a_number_last_4, outcome, cached, duration_ms
FROM lookups
WHERE tenant = ? AND coalesce(ts < ?, 1) AND coalesce(ts >= ?, 1)
ORDER BY ts DESC, id DESC
LIMIT ?;
