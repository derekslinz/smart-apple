-- v9: taxiing-window counts + rolling realized taxi-out regime per runway/airport.
DROP TABLE IF EXISTS taxi_features_v9_all_v20;
CREATE TABLE taxi_features_v9_all_v20 AS
WITH intervals AS (
    select "ADEP_mvt" as "airport", "RUNWAY_mvt" as "runway", 'DEP'::text as "phase",
           nullif("IOBT_flt",'')::timestamptz as "start_t",
           nullif("MVT_TIME_UTC_mvt",'')::timestamptz as "end_t",
           extract(epoch from nullif("MVT_TIME_UTC_mvt",'')::timestamptz - nullif("IOBT_flt",'')::timestamptz) as "dur"
    from "movements_all"
    where "PHASE_mvt" = 'DEP'
      and nullif("IOBT_flt",'') is not null and nullif("MVT_TIME_UTC_mvt",'') is not null
      and nullif("RUNWAY_mvt",'') is not null and "RUNWAY_mvt" <> 'NA'
      and nullif("MVT_TIME_UTC_mvt",'')::timestamptz > nullif("IOBT_flt",'')::timestamptz
      and nullif("MVT_TIME_UTC_mvt",'')::timestamptz - nullif("IOBT_flt",'')::timestamptz < interval '3 hours'
    union all
    select "ADES_mvt", "RUNWAY_mvt", 'ARR',
           nullif("MVT_TIME_UTC_mvt",'')::timestamptz,
           nullif("MVT_TIME_UTC_mvt",'')::timestamptz + ("TAXITIME_SEC_mvt" * interval '1 second'),
           "TAXITIME_SEC_mvt"
    from "movements_all"
    where "PHASE_mvt" = 'ARR'
      and nullif("MVT_TIME_UTC_mvt",'') is not null
      and nullif("RUNWAY_mvt",'') is not null and "RUNWAY_mvt" <> 'NA'
      and "TAXITIME_SEC_mvt" is not null and "TAXITIME_SEC_mvt" > 0 and "TAXITIME_SEC_mvt" < 7200
),
marks AS (
    select "airport", "runway", "phase", "start_t" as "ts", 1 as "is_start", 0 as "is_end",
           null::double precision as "dur", null::double precision as "mvt", 0 as "self_dep"
    from intervals
    union all
    select "airport", "runway", "phase", "end_t", 0, 1, "dur", null, 0 from intervals
    union all
    select "ADEP_mvt", "RUNWAY_mvt", 'QRY',
           coalesce(nullif("IOBT_flt",'')::timestamptz, nullif("SCHED_TIME_UTC_mvt",'')::timestamptz),
           0, 0, null, "MVT_ID_mvt",
           case when nullif("IOBT_flt",'') is not null then 1 else 0 end
    from "movements_all"
    where "PHASE_mvt" = 'DEP'
      and nullif("RUNWAY_mvt",'') is not null and "RUNWAY_mvt" <> 'NA'
      and coalesce(nullif("IOBT_flt",'')::timestamptz, nullif("SCHED_TIME_UTC_mvt",'')::timestamptz) is not null
)
select "mvt",
       greatest("dep_act" - "self_dep", 0) as "rwy_taxiing_dep",
       "arr_act" as "rwy_taxiing_arr",
       "rwy_taxi_roll_30", "rwy_taxi_roll_90", "rwy_taxi_roll_n90",
       "apt_taxi_roll_90", "rwy_taxi_roll_max_90", "rwy_dep_gap_last"
from (
    select "mvt", "self_dep",
           sum(case when "phase"='DEP' then "is_start" else 0 end) over wr
         - sum(case when "phase"='DEP' then "is_end"  else 0 end) over wr as "dep_act",
           sum(case when "phase"='ARR' then "is_start" else 0 end) over wr
         - sum(case when "phase"='ARR' then "is_end"  else 0 end) over wr as "arr_act",
           avg(case when "phase"='DEP' and "is_end"=1 then "dur" end) over w30 as "rwy_taxi_roll_30",
           avg(case when "phase"='DEP' and "is_end"=1 then "dur" end) over w90 as "rwy_taxi_roll_90",
           count(case when "phase"='DEP' and "is_end"=1 then 1 end) over w90 as "rwy_taxi_roll_n90",
           max(case when "phase"='DEP' and "is_end"=1 then "dur" end) over w90 as "rwy_taxi_roll_max_90",
           avg(case when "phase"='DEP' and "is_end"=1 then "dur" end) over wa90 as "apt_taxi_roll_90",
           extract(epoch from "ts" - max(case when "phase"='DEP' and "is_end"=1 then "ts" end) over wrows) as "rwy_dep_gap_last"
    from marks
    window
      wr   as (partition by "airport", "runway" order by "ts" range between unbounded preceding and current row),
      wrows as (partition by "airport", "runway" order by "ts" rows between unbounded preceding and current row),
      w30  as (partition by "airport", "runway" order by "ts" range between interval '30 minutes' preceding and current row),
      w90  as (partition by "airport", "runway" order by "ts" range between interval '90 minutes' preceding and current row),
      wa90 as (partition by "airport" order by "ts" range between interval '90 minutes' preceding and current row)
) x
where "mvt" is not null;
CREATE INDEX idx_tf_v20_mvt ON taxi_features_v9_all_v20 ("mvt");
