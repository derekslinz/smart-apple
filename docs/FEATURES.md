# Feature reference

The inference feature vector is 196 columns; the exact list actually exported is in
`sql/predict_export_example.sql`. Every feature below is either computable from information
known **before off-block**, or is an aggregate over movements **strictly earlier** than the
one being predicted. Nothing derived from `BLOCK_TIME_UTC_mvt` (the target's other endpoint)
is used, and no movement/flight identifier is used as a model input.

## Families

### Identity and flight attributes
`ADEP_mvt` `ADES_mvt` `ADEP_flt` `ADES_flt` `ADES_FILED_flt` `RUNWAY_mvt` `STAND_mvt`
`AIRCRAFT_TYPE_mvt` `AIRCRAFT_TYPE_flt` `WK_TBL_CAT_flt` `MARKET_SEGMENT_flt`
`FLIGHT_RULE_mvt` `FLIGHT_RULE_flt` `FLIGHT_TYPE_flt` `AIRCRAFT_OPERATOR_flt`
`CALLSIGN_flt` → `carrier_code`

`AC_GROUP_mvt` collapses raw ICAO type codes into operational size classes (Heli,
SmallProp, Turboprop, BizRegional, Narrowbody, Widebody, Super). Raw type codes number in
the hundreds and are sparse per airport; the behaviour that affects taxi time is size, stand
complexity and wake category.

Composite keys let the trees learn behaviour specific to a combination rather than a single
attribute: `ac_group_adest`, `ac_group_runway`, `ac_group_mkt`, `adep_ades`,
`carrier_ac_adest`, `carrier_ac_runway`, `carrier_ac_mkt`, `carrier_group_stand`,
`carrier_group_runway`, `focus_airport`.

### Stand → runway geometry  *(the distance enrichment)*
`departure_runway_dist_m` `min_runway_dist_m` `nearest_runway` `runway_heading` `runway_side`

and the historical counterpart, keyed on the actual stand/runway pair:
`hist_avg_taxi_stand_rwy` `hist_std_taxi_stand_rwy` `hist_count_stand_rwy`
`hist_tail_rate_stand_rwy` `n_hist_stand_rwy` `stand_rwy_hist_mean`
`hist_avg_taxi_stand_rwy_hour` `hist_avg_taxi_stand` `hist_avg_taxi_type_rwy`
`hist_avg_taxi_carr_rwy`.

Measured coverage on the 2026 ranking rows:

| Airport | DEP rows | distance feature filled | mean distance | max distance | distinct nearest runways |
|---|---|---|---|---|---|
| EDDF | 70,671 | 68.70 % | 2,119 m | 5,593 m | 5 |
| EDDM | 50,872 | 54.07 % | 1,119 m | 2,549 m | 4 |
| EGLL | 77,221 | 98.08 % | 733 m | 2,216 m | 4 |
| EHAM | 75,865 | 68.49 % | 1,771 m | 7,052 m | 10 |
| LEBL | 59,314 | 89.11 % | 1,205 m | 2,134 m | 5 |
| LEMD | 72,480 | 98.56 % | 2,436 m | 5,355 m | 8 |
| LFPG | 77,520 | 96.02 % | 1,341 m | 5,706 m | 4 |
| LIRF | 52,146 | 98.51 % | 982 m | 3,941 m | 4 |
| LSZH | 44,908 | 96.17 % | 685 m | 2,264 m | 8 |
| LTFM | 89,793 | 98.87 % | 1,043 m | 3,840 m | 9 |

Coverage is lower at EDDM/EHAM/EDDF because some stands present in 2026 do not appear in
the 2025 movements, so no distance could be established for them. Those rows fall back on
airport/runway-level aggregates.

### Traffic state — runway and airport load
Around the scheduled off-block: `per_runway_dep_30m` `per_runway_arr_30m`
`per_runway_arr_15m` `arr_airport_30m` `dep_airport_30m` `apt_dep_to_30m` `apt_arr_ld_30m`
`apt_arr_taxi_in_avg_30m` `stand_dep_to_30m` `stand_arr_ld_30m` `rwy_taxiing_dep`
`rwy_taxiing_arr` `sched_rwy_taxiing_dep` `sched_rwy_taxiing_arr` `rwy_taxi_roll_30`
`rwy_taxi_roll_90` `rwy_taxi_roll_n90` `apt_taxi_roll_90` `rwy_taxi_roll_max_90`

Near-future and recent-past events (schedulable, therefore ex-ante): `arr_land_past_15`
`arr_land_past_30` `arr_land_next_10` `arr_land_next_20` `arr_next_20` `arr_apt_next_30`
`arr_apt_next_60` `arr_apt_past_30` `dep_tko_next_15` `dep_tko_next_30`
`rwy_dep_sched_next_15m` `rwy_dep_sched_next_30m` `rwy_arr_sched_next_15m`
`rwy_arr_sched_next_30m` `rwy_sched_next_30`.

Headways and queue pressure: `rwy_dep_gap_min` `rwy_arr_gap_min` `arr_gap_med_rwy`
`dep_gap_med_rwy` `rwy_dep_gap_last` `rwy_queue_ahead` `rwy_queue_ahead_raw`
`rwy_queue_wake_weighted` `rwy_queue_heavy_ahead` `rwy_queue_pending` `rwy_occ_sec_ahead`
`stand_occ_sec_ahead` `stand_queue_ahead` `rwy_load_sec_next_20` `dep_queue_realized`
`dep_blk_past` `tail_prev_30` `tail_prev_60` `hist_tail_rate_apt_hour`.

`rwy_queue_wake_weighted` weights queued aircraft by wake category, because the separation
a Heavy imposes on the following aircraft is what actually lengthens a departure sequence.

### Departure-metering queue state (`sql/build_ret_v20.sql`)
`ret_overdue_rwy` `ret_overdue_apt` `ret_ativos_rwy` `ret_atraso_15m` `ret_ewma_dep`

Built from event sweeps on the real push clock:

```
overdue(t)  = |{EOBT ≤ t}| − |{AOBT ≤ t}|
active(t)   = |{AOBT ≤ t}| − |{MVT ≤ t}|
```

with the guards `0 ≤ AOBT − EOBT < 7200 s` (above that it is a date rollover) and
`MVT ≥ AOBT`. `pista_*` columns (`pista_cfg_mudou`, `pista_cfg_dep`, `pista_cfg_arr`,
`pista_dominante`, `pista_parte_rwy`, `pista_fila_peso`, `pista_fila_pesadas`,
`pista_span20`, `pista_dep_h30`) are the configuration and queue-state variables of the
published Madrid departure-metering model, reimplemented here from its documented rules.

### Historical aggregates (`sql/build_2025_stats.sql`, `sql/build_ranking_hist.sql`)
`hist_avg_taxi_rwy` `hist_avg_taxi_apt` `hist_avg_taxi_rwy_hour` `hist_avg_taxi_rwy_dow`
`hist_median_taxi_sec` `hist_p90_taxi_sec` `hist_mean_taxi_sec`
`hist_median_delay_sec` `hist_p90_delay_sec` `hist_mean_delay_sec` `apt_mean_7d`
`rwy_delay_max_1h` `rwy_delay_avg_30m` `rwy_arr_delay_avg_30m` `rwy_arr_delay_max_30m`
`prev_flight_delay_flt`

Keys are (airport, runway), (airport, runway, hour), (airport, runway, day-of-week),
(airport, stand, runway), (airport, aircraft type, runway) and (airport, operator, runway).
Groups with fewer than 10 samples are dropped rather than imputed. For a 2026 movement every
2025 movement is in the past, so the full-year 2025 aggregate *is* the trailing value a
forecaster legitimately has.

### Clock anchors — the load-bearing features
`mvt_minus_lobt` `mvt_minus_aobt3` `mvt_minus_iobt` `mvt_minus_eobt` `mvt_minus_sched`
`sched_lobt_margin` `to_takeoff_from_IOBT_flt` `to_takeoff_from_EOBT_1_flt`
`dep_delay_flt` `eobt_delay_flt` `resid_lobt`

`MVT_TIME_UTC_mvt` is known in the ranking data; `BLOCK_TIME_UTC_mvt` is not. These
features express the gap between take-off and every available estimate of push-back.
`resid_lobt` is the model's own residual against the LOBT anchor, used by the blending
stage rather than by the regressor.

Time-of-day context is taken from the **scheduled** clock, not the realised one:
`sched_time_ts` `dep_dow` `dep_month` `dep_hour` `dep_minute` `round_SCHED_TIME_UTC_mvt`
`round5_SCHED_TIME_UTC_mvt` `is_christmas_eve` `is_newyear_eve` `is_christmas_period`
`is_newyear_period`.

### Weather
`tmpc` `dwpc` `relh` `drct` `sknt` `gust` `precip_mm` `ptype` `cbh_m` `skyl1_ft`
`vsby_miles` `vis_lt1mi` `vis_lt3mi` `vis_lt5mi` `fg_flag` `ceiling_low` `wx_precip`
`is_raining` `is_snowing` `is_thunderstorm` `is_freezing_precip` `wx_severe_count`
`wx_snow_lowvis` `wx_snow_lowceil` `wx_snow_lowceil_lowvis` `wx_lowceil_lowvis`
`wx_snow_freezing`

ERA5 reanalysis, hourly, bounding box (52.5 N, 5.0 W)–(39.5 N, 30.0 E), joined laterally to
the nearest observation within ±30 minutes of scheduled off-block. Composite flags matter
more than any single variable: low visibility *and* a low ceiling *and* snow changes departure
handling in a way no one of them does alone.

### Data-quality flags
`is_unmatched` `nm_missing` `missing_ac_type` `missing_iobt_eobt` `missing_callsign`
`is_artifact` `is_extreme_taxi`

The movement↔flight match in the source data is imperfect. Rather than dropping or silently
repairing those rows, the defect is exposed so the model can treat an unmatched movement as a
different prediction problem — which it is, because most of the clock anchors are absent.

### Blend control
`is_copy` `copy_q_opband` `sample_weight`

`is_copy` is the target of a second model: the probability that copying an anchor is the
best available answer. `copy_q_opband` is the calibrated airport × operator × delay-band
fallback used when a copy partition is unavailable. `sample_weight` down-weights rows whose
target looks like a source artifact rather than real taxiing.
