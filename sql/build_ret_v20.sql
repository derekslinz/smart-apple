-- ===========================================================================
-- ret_* : gate retention at the REAL push clock (t = own AOBT_3), from
-- src/pista.py colunas_retencao. Without AOBT_3 the whole block is NULL.
-- ===========================================================================
SET statement_timeout = 0;
SET work_mem = '2GB';

-- their _retidas guards: both clocks present, EOBT <= AOBT, the wait is under 7200 s
-- (above that it is a date rollover), and the flight did take off (MVT >= AOBT).
DROP TABLE IF EXISTS ret_dep_v20;
CREATE TABLE ret_dep_v20 AS
SELECT airport, rwy, mvt_ts, aobt_ts, eobt_ts, sched_ts
FROM mov_pool_v20
WHERE phase = 'DEP' AND aobt_ts IS NOT NULL AND eobt_ts IS NOT NULL AND mvt_ts IS NOT NULL
  AND aobt_ts - eobt_ts >= 0 AND aobt_ts - eobt_ts < 7200 AND mvt_ts >= aobt_ts;

-- their _ativas guards: pushed and took off (AOBT <= MVT). No EOBT, no 7200 cap.
DROP TABLE IF EXISTS ret_act_v20;
CREATE TABLE ret_act_v20 AS
SELECT airport, rwy, aobt_ts, mvt_ts FROM mov_pool_v20
WHERE phase = 'DEP' AND aobt_ts IS NOT NULL AND mvt_ts IS NOT NULL AND aobt_ts <= mvt_ts;

DROP TABLE IF EXISTS ret_state_v20;
CREATE TABLE ret_state_v20 AS
WITH q AS (
    SELECT mvt AS qid, airport, rwy, aobt_ts AS ts, mvt_ts
    FROM dep_target_v20 WHERE aobt_ts IS NOT NULL
),
-- overdue: |{EOBT <= t}| - |{AOBT <= t}| ; the flight itself cancels in both counts
ev_o AS (
    SELECT airport, rwy, eobt_ts AS ts, 1 AS k_e, 0 AS k_a FROM ret_dep_v20
    UNION ALL
    SELECT airport, rwy, aobt_ts AS ts, 0, 1 FROM ret_dep_v20
),
-- active on the ground: |{AOBT <= t}| - |{MVT <= t}|
ev_a AS (
    SELECT airport, rwy, aobt_ts AS ts, 1 AS k_p, 0 AS k_m FROM ret_act_v20
    UNION ALL
    SELECT airport, rwy, mvt_ts AS ts, 0, 1 FROM ret_act_v20
),
-- mean AOBT_3 - SCHED of the airport's departures that pushed in [t-15min, t)
ev_d AS (
    SELECT airport, rwy, aobt_ts AS ts, (aobt_ts - sched_ts) AS d, 1 AS is_d
    FROM mov_pool_v20
    WHERE phase = 'DEP' AND aobt_ts IS NOT NULL AND sched_ts IS NOT NULL
),
-- departures per hour with an EWMA of half-life 10 min, evaluated at t.
-- 2^((mvt-t)/600) = 2^((mvt-origin)/600) * 2^((origin-t)/600) with origin = 6h chunk
-- boundary, so every exponent stays inside [-72, 72). Events are copied into the three
-- chunks a query in the middle one can reach.
ev_w AS (
    SELECT airport, mvt_ts AS ts, floor(mvt_ts/21600)::bigint + off AS chunk,
           power(2.0, (mvt_ts - (floor(mvt_ts/21600)::bigint + off) * 21600) / 600.0) AS wt
    FROM mov_pool_v20 CROSS JOIN generate_series(-1, 1) AS off
    WHERE phase = 'DEP' AND mvt_ts IS NOT NULL
),
stream_o AS (
    SELECT airport, rwy, ts, NULL::double precision AS qid, k_e, k_a FROM ev_o
    UNION ALL SELECT airport, rwy, ts, qid, 0, 0 FROM q
),
w_o AS (
    SELECT qid,
           sum(k_e) OVER wa - sum(k_a) OVER wa AS overdue_apt,
           sum(k_e) OVER wr - sum(k_a) OVER wr AS overdue_rwy
    FROM stream_o
    WINDOW wa AS (PARTITION BY airport ORDER BY ts RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW),
           wr AS (PARTITION BY airport, rwy ORDER BY ts RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
stream_a AS (
    SELECT airport, rwy, ts, NULL::double precision AS qid, k_p, k_m FROM ev_a
    UNION ALL SELECT airport, rwy, ts, qid, 0, 0 FROM q
),
w_a AS (
    SELECT qid, sum(k_p) OVER wr - sum(k_m) OVER wr AS active_rwy
    FROM stream_a
    WINDOW wr AS (PARTITION BY airport, rwy ORDER BY ts RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
stream_d AS (
    SELECT airport, ts, NULL::double precision AS qid, d FROM ev_d
    UNION ALL SELECT airport, ts, qid, NULL FROM q
),
w_d AS (
    SELECT qid, avg(d) OVER (PARTITION BY airport ORDER BY ts
            RANGE BETWEEN 900 PRECEDING AND 1 PRECEDING) AS atraso_15m
    FROM stream_d
),
stream_w AS (
    SELECT airport, chunk, ts, NULL::double precision AS qid, wt FROM ev_w
    UNION ALL SELECT airport, floor(ts/21600)::bigint, ts, qid, NULL FROM q
),
w_w AS (
    SELECT qid, ts, chunk,
           sum(wt) OVER (PARTITION BY airport, chunk ORDER BY ts
               RANGE BETWEEN 7200 PRECEDING AND 1 PRECEDING) AS s
    FROM stream_w
)
SELECT q.qid AS mvt,
       wo.overdue_rwy AS ret_overdue_rwy,
       wo.overdue_apt AS ret_overdue_apt,
       greatest(wa.active_rwy - CASE WHEN q.mvt_ts > q.ts THEN 1 ELSE 0 END, 0) AS ret_ativos_rwy,
       wd.atraso_15m AS ret_atraso_15m,
       power(2.0, (ww.chunk * 21600 - ww.ts) / 600.0) * coalesce(ww.s, 0) * (3600.0 * ln(2.0) / 600.0) AS ret_ewma_dep
FROM q
LEFT JOIN w_o wo ON wo.qid = q.qid
LEFT JOIN w_a wa ON wa.qid = q.qid
LEFT JOIN w_d wd ON wd.qid = q.qid
LEFT JOIN w_w ww ON ww.qid = q.qid;
CREATE INDEX idx_ret_v20 ON ret_state_v20 (mvt);
