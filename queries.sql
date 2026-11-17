-- The same questions as xray.py, asked in SQL.
-- Written for SQLite. run_queries.py loads event_log.csv into a table called events and runs each one.

-- name: Paths, most common first
WITH ordered AS (
  SELECT DISTINCT
         order_id,
         group_concat(step, ' > ') OVER (
           PARTITION BY order_id ORDER BY started_at
           ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
         ) AS path
  FROM events
)
SELECT path,
       COUNT(*) AS orders,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(DISTINCT order_id) FROM events), 1) AS pct
FROM ordered
GROUP BY path
ORDER BY orders DESC, path;

-- name: Orders that never had a credit check
SELECT COUNT(*) AS orders
FROM (
  SELECT order_id
  FROM events
  GROUP BY order_id
  HAVING SUM(step = 'Credit check') = 0
);

-- name: Orders packed more than once
SELECT COUNT(*) AS orders
FROM (
  SELECT order_id
  FROM events
  WHERE step = 'Pack'
  GROUP BY order_id
  HAVING COUNT(*) > 1
);

-- name: Hand-offs between steps
WITH pairs AS (
  SELECT step AS from_step,
         LEAD(step) OVER (PARTITION BY order_id ORDER BY started_at) AS to_step
  FROM events
)
SELECT from_step, to_step, COUNT(*) AS orders
FROM pairs
WHERE to_step IS NOT NULL
GROUP BY from_step, to_step
ORDER BY orders DESC, from_step, to_step;

-- name: Average wait before each step, in hours
WITH gaps AS (
  SELECT step,
         (julianday(started_at)
          - julianday(LAG(finished_at) OVER (PARTITION BY order_id ORDER BY started_at))) * 24 AS hours
  FROM events
)
SELECT step, ROUND(AVG(hours), 1) AS avg_wait_hours, COUNT(*) AS times
FROM gaps
WHERE hours IS NOT NULL
GROUP BY step
ORDER BY avg_wait_hours DESC;
