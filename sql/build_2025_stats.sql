-- Build 2025 delay/queue features from 2025 historical patterns
-- For each (airport, runway, hour, dow): compute median delay from 2025 movements
-- Then fill 2026 ranking rows by lookup

DROP TABLE IF EXISTS prc_2025_delay_stats;
CREATE TABLE prc_2025_delay_stats AS
WITH mvts AS (
  SELECT
    "ADEP_mvt" AS airport,
    "RUNWAY_mvt" AS runway,
    EXTRACT(HOUR FROM to_timestamp("sched_time_ts"))::int AS hour,
    EXTRACT(DOW FROM to_timestamp("sched_time_ts"))::int AS dow,
    "mvt_minus_sched" AS delay_sec
  FROM "PRC_prc_enriched_prepared"
  WHERE "sched_time_ts" >= EXTRACT(EPOCH FROM TIMESTAMP '2025-01-01 00:00:00')
    AND "sched_time_ts" < EXTRACT(EPOCH FROM TIMESTAMP '2026-01-01 00:00:00')
    AND "mvt_minus_sched" IS NOT NULL
),
agg AS (
  SELECT
    airport,
    runway,
    hour,
    dow,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY delay_sec) AS median_delay_sec,
    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY delay_sec) AS p90_delay_sec,
    AVG(delay_sec) AS mean_delay_sec,
    COUNT(*) AS n_samples
  FROM mvts
  GROUP BY airport, runway, hour, dow
  HAVING COUNT(*) >= 10
)
SELECT * FROM agg;

-- Also compute 2025 taxi-roll statistics per (airport, runway, hour, dow)
DROP TABLE IF EXISTS prc_2025_taxiroll_stats;
CREATE TABLE prc_2025_taxiroll_stats AS
WITH mvts AS (
  SELECT
    "ADEP_mvt" AS airport,
    "RUNWAY_mvt" AS runway,
    EXTRACT(HOUR FROM to_timestamp("sched_time_ts"))::int AS hour,
    EXTRACT(DOW FROM to_timestamp("sched_time_ts"))::int AS dow,
    "TAXITIME_SEC_mvt" AS taxi_sec
  FROM "PRC_prc_enriched_prepared"
  WHERE "sched_time_ts" >= EXTRACT(EPOCH FROM TIMESTAMP '2025-01-01 00:00:00')
    AND "sched_time_ts" < EXTRACT(EPOCH FROM TIMESTAMP '2026-01-01 00:00:00')
    AND "TAXITIME_SEC_mvt" IS NOT NULL
    AND "TAXITIME_SEC_mvt" BETWEEN 60 AND 20000
),
agg AS (
  SELECT
    airport,
    runway,
    hour,
    dow,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY taxi_sec) AS median_taxi_sec,
    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY taxi_sec) AS p90_taxi_sec,
    AVG(taxi_sec) AS mean_taxi_sec,
    COUNT(*) AS n_samples
  FROM mvts
  GROUP BY airport, runway, hour, dow
  HAVING COUNT(*) >= 10
)
SELECT * FROM agg;

-- Verify
SELECT 'delay_stats' AS table_name, COUNT(*) FROM prc_2025_delay_stats
UNION ALL
SELECT 'taxiroll_stats', COUNT(*) FROM prc_2025_taxiroll_stats;