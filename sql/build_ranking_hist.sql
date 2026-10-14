-- Ranking-side history features.
-- Identical key definitions and filters to the TRAINING recipe (compute_prc_enriched.hist_src,
-- cap 86400), but the aggregate is taken over all of 2025 -- which is exactly the history
-- available to a 2026 movement. Training uses trailing windows per row; for a 2026 row every
-- 2025 movement is in the past, so the full-year aggregate IS the trailing value.
DROP TABLE IF EXISTS "PRC_ranking_hist";
CREATE TABLE "PRC_ranking_hist" AS
WITH hist_src AS (
    select
        case when "ADEP_mvt" is not null and "STAND_mvt" is not null and "RUNWAY_mvt" is not null
             then "ADEP_mvt" || '_' || "STAND_mvt" || '_' || "RUNWAY_mvt" end as "k_stand_rwy",
        case when "ADEP_mvt" is not null and "RUNWAY_mvt" is not null
             then "ADEP_mvt" || '_' || "RUNWAY_mvt" end as "k_rwy",
        case when "ADEP_mvt" is not null and "STAND_mvt" is not null
             then "ADEP_mvt" || '_' || "STAND_mvt" end as "k_stand",
        case when "ADEP_mvt" is not null and "AIRCRAFT_TYPE_mvt" is not null and "RUNWAY_mvt" is not null
             then "ADEP_mvt" || '_' || "AIRCRAFT_TYPE_mvt" || '_' || "RUNWAY_mvt" end as "k_type_rwy",
        case when "ADEP_mvt" is not null and left("CALLSIGN_flt",3) is not null and "RUNWAY_mvt" is not null
             then "ADEP_mvt" || '_' || left("CALLSIGN_flt",3) || '_' || "RUNWAY_mvt" end as "k_carr_rwy",
        "ADEP_mvt" as "k_apt",
        case when "ADEP_mvt" is not null and "RUNWAY_mvt" is not null
             then "ADEP_mvt" || '_' || "RUNWAY_mvt" || '_' ||
                  extract(hour from "SCHED_TIME_UTC_mvt"::timestamptz)::int end as "k_rwy_hour",
        case when "ADEP_mvt" is not null and "RUNWAY_mvt" is not null
             then "ADEP_mvt" || '_' || "RUNWAY_mvt" || '_' ||
                  extract(dow from "SCHED_TIME_UTC_mvt"::timestamptz)::int end as "k_rwy_dow",
        case when "ADEP_mvt" is not null and "STAND_mvt" is not null and "RUNWAY_mvt" is not null
             then "ADEP_mvt" || '_' || "STAND_mvt" || '_' || "RUNWAY_mvt" || '_' ||
                  extract(hour from "SCHED_TIME_UTC_mvt"::timestamptz)::int end as "k_stand_rwy_hour",
        case when "TAXITIME_SEC_mvt" > 0 and "TAXITIME_SEC_mvt" < 86400 then "TAXITIME_SEC_mvt" end as "taxi"
    from "prc_movements_raw"
    where "PHASE_mvt" = 'DEP'
      and ("TAXITIME_SEC_mvt" is null or ("TAXITIME_SEC_mvt" > 0 and "TAXITIME_SEC_mvt" < 86400))
      and "SCHED_TIME_UTC_mvt" is not null and "SCHED_TIME_UTC_mvt" <> ''
),
a_sr  as (select "k_stand_rwy"      k, avg("taxi") a, stddev("taxi") s, count("taxi") n from hist_src where "k_stand_rwy"      is not null group by 1),
a_r   as (select "k_rwy"            k, avg("taxi") a from hist_src where "k_rwy"            is not null group by 1),
a_s   as (select "k_stand"          k, avg("taxi") a from hist_src where "k_stand"          is not null group by 1),
a_tr  as (select "k_type_rwy"       k, avg("taxi") a from hist_src where "k_type_rwy"       is not null group by 1),
a_cr  as (select "k_carr_rwy"       k, avg("taxi") a from hist_src where "k_carr_rwy"       is not null group by 1),
a_a   as (select "k_apt"            k, avg("taxi") a from hist_src where "k_apt"            is not null group by 1),
a_rh  as (select "k_rwy_hour"       k, avg("taxi") a from hist_src where "k_rwy_hour"       is not null group by 1),
a_rd  as (select "k_rwy_dow"        k, avg("taxi") a from hist_src where "k_rwy_dow"        is not null group by 1),
a_srh as (select "k_stand_rwy_hour" k, avg("taxi") a from hist_src where "k_stand_rwy_hour" is not null group by 1),
tgt AS (
    select
        "MVT_ID_mvt",
        case when "ADEP_mvt" is not null and "STAND_mvt" is not null and "RUNWAY_mvt" is not null
             then "ADEP_mvt" || '_' || "STAND_mvt" || '_' || "RUNWAY_mvt" end as "k_stand_rwy",
        case when "ADEP_mvt" is not null and "RUNWAY_mvt" is not null
             then "ADEP_mvt" || '_' || "RUNWAY_mvt" end as "k_rwy",
        case when "ADEP_mvt" is not null and "STAND_mvt" is not null
             then "ADEP_mvt" || '_' || "STAND_mvt" end as "k_stand",
        case when "ADEP_mvt" is not null and "AIRCRAFT_TYPE_mvt" is not null and "RUNWAY_mvt" is not null
             then "ADEP_mvt" || '_' || "AIRCRAFT_TYPE_mvt" || '_' || "RUNWAY_mvt" end as "k_type_rwy",
        case when "ADEP_mvt" is not null and left("CALLSIGN_flt",3) is not null and "RUNWAY_mvt" is not null
             then "ADEP_mvt" || '_' || left("CALLSIGN_flt",3) || '_' || "RUNWAY_mvt" end as "k_carr_rwy",
        "ADEP_mvt" as "k_apt",
        case when "ADEP_mvt" is not null and "RUNWAY_mvt" is not null
             then "ADEP_mvt" || '_' || "RUNWAY_mvt" || '_' ||
                  extract(hour from "SCHED_TIME_UTC_mvt"::timestamptz)::int end as "k_rwy_hour",
        case when "ADEP_mvt" is not null and "RUNWAY_mvt" is not null
             then "ADEP_mvt" || '_' || "RUNWAY_mvt" || '_' ||
                  extract(dow from "SCHED_TIME_UTC_mvt"::timestamptz)::int end as "k_rwy_dow",
        case when "ADEP_mvt" is not null and "STAND_mvt" is not null and "RUNWAY_mvt" is not null
             then "ADEP_mvt" || '_' || "STAND_mvt" || '_' || "RUNWAY_mvt" || '_' ||
                  extract(hour from "SCHED_TIME_UTC_mvt"::timestamptz)::int end as "k_stand_rwy_hour"
    from "final_ranking_stage"
    where "PHASE_mvt" = 'DEP'
)
select
    t."MVT_ID_mvt",
    a_sr.a  as "hist_avg_taxi_stand_rwy",
    a_sr.s  as "hist_std_taxi_stand_rwy",
    coalesce(a_sr.n, 0) as "hist_count_stand_rwy",
    a_r.a   as "hist_avg_taxi_rwy",
    a_s.a   as "hist_avg_taxi_stand",
    a_tr.a  as "hist_avg_taxi_type_rwy",
    a_cr.a  as "hist_avg_taxi_carr_rwy",
    a_a.a   as "hist_avg_taxi_apt",
    a_rh.a  as "hist_avg_taxi_rwy_hour",
    a_rd.a  as "hist_avg_taxi_rwy_dow",
    a_srh.a as "hist_avg_taxi_stand_rwy_hour"
from tgt t
left join a_sr  on a_sr.k  = t."k_stand_rwy"
left join a_r   on a_r.k   = t."k_rwy"
left join a_s   on a_s.k   = t."k_stand"
left join a_tr  on a_tr.k  = t."k_type_rwy"
left join a_cr  on a_cr.k  = t."k_carr_rwy"
left join a_a   on a_a.k   = t."k_apt"
left join a_rh  on a_rh.k  = t."k_rwy_hour"
left join a_rd  on a_rd.k  = t."k_rwy_dow"
left join a_srh on a_srh.k = t."k_stand_rwy_hour";
CREATE INDEX IF NOT EXISTS idx_ranking_hist_mvt ON "PRC_ranking_hist" ("MVT_ID_mvt");
ANALYZE "PRC_ranking_hist";
