-- Add historical delay/taxi features to ranking prepared table
-- and fill them from 2025 stats

ALTER TABLE "PRC_prc_ranking_prepared" 
  ADD COLUMN IF NOT EXISTS hist_median_delay_sec NUMERIC,
  ADD COLUMN IF NOT EXISTS hist_p90_delay_sec NUMERIC,
  ADD COLUMN IF NOT EXISTS hist_mean_delay_sec NUMERIC,
  ADD COLUMN IF NOT EXISTS hist_median_taxi_sec NUMERIC,
  ADD COLUMN IF NOT EXISTS hist_p90_taxi_sec NUMERIC,
  ADD COLUMN IF NOT EXISTS hist_mean_taxi_sec NUMERIC;

-- Fill delay features
UPDATE "PRC_prc_ranking_prepared" r
SET 
  hist_median_delay_sec = d.median_delay_sec,
  hist_p90_delay_sec = d.p90_delay_sec,
  hist_mean_delay_sec = d.mean_delay_sec
FROM prc_2025_delay_stats d
WHERE r."ADEP_mvt" = d.airport
  AND r."RUNWAY_mvt" = d.runway
  AND EXTRACT(HOUR FROM to_timestamp(r."sched_time_ts"))::int = d.hour
  AND EXTRACT(DOW FROM to_timestamp(r."sched_time_ts"))::int = d.dow;

-- Fill taxi-roll features
UPDATE "PRC_prc_ranking_prepared" r
SET 
  hist_median_taxi_sec = t.median_taxi_sec,
  hist_p90_taxi_sec = t.p90_taxi_sec,
  hist_mean_taxi_sec = t.mean_taxi_sec
FROM prc_2025_taxiroll_stats t
WHERE r."ADEP_mvt" = t.airport
  AND r."RUNWAY_mvt" = t.runway
  AND EXTRACT(HOUR FROM to_timestamp(r."sched_time_ts"))::int = t.hour
  AND EXTRACT(DOW FROM to_timestamp(r."sched_time_ts"))::int = t.dow;

-- Verify fill rates
SELECT 
  round(100.0 * count(hist_median_delay_sec) / count(*)::numeric, 2) as delay_fill_pct,
  round(100.0 * count(hist_median_taxi_sec) / count(*)::numeric, 2) as taxi_fill_pct
FROM "PRC_prc_ranking_prepared";