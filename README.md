# smart-apple — PRC Data Challenge 2026: taxi-out time prediction

Predicting `TAXITIME_SEC_mvt` (taxi-out time, seconds) for departing movements at ten
major European airports: EDDF, EDDM, EGLL, EHAM, LEBL, LEMD, LFPG, LIRF, LTFM, LSZH.

Submitted entry: `smart-apple_final.parquet` (670,790 rows — Jan, Feb, Jun and Jul 2026
departures), derived from board submission **v13**, official score **434.22**.

---

## 1. The core idea

The target is not really "how long does this aircraft taxi". It is *the gap between two
noisy clocks*:

```
TAXI_OUT  =  take-off time  -  off-block time
```

Both ends of that gap are present in the ranking data:

| field | meaning | available in ranking? |
|---|---|---|
| `MVT_TIME_UTC_mvt` | take-off (DEP) | **yes** |
| `LOBT_flt` | last known off-block time | **yes**, ~98.6 % of rows |
| `IOBT_flt` / `EOBT_1_flt` | initial / estimated off-block | yes |
| `SCHED_TIME_UTC_mvt` | scheduled off-block | yes |
| `BLOCK_TIME_UTC_mvt` | actual off-block | **blanked** — this is what we must infer |

So the task is: *given a known take-off time and several noisy estimates of when the
aircraft pushed back, plus everything known about the airport state at that moment,
estimate the actual ground time.*

`MVT − LOBT` is a direct anchor for the answer. It is not the answer: LOBT is a *last
known* value, frequently stale or from an earlier attempt. The whole design is about
**deciding when to trust each clock** and when to fall back on a model of the airport.

That reframing drove every decision below.

---

## 2. Pipeline

```
2025 training parquets ─┐
                        ├─► feature construction (PostgreSQL) ─► per-airport LightGBM (Dataiku)
2026 ranking parquet ───┘                                             │
                                                                    ▼
                       anchor clamping ─► copy blend ─► tail calibration ─► ship.py
```

### 2.1 Feature construction (`sql/`)

All features are **ex-ante** — computable from information available before off-block, or
from history strictly earlier than the movement.

* **Movement / flight attributes** — airport, destination, stand, runway, ICAO aircraft
  type, wake turbulence category, market segment, flight rules, operator. Aircraft types
  are collapsed into an operational size class (`AC_GROUP_mvt`: Heli, SmallProp,
  Turboprop, BizRegional, Narrowbody, Widebody, Super) because raw type codes are too
  sparse and the physical behaviour that matters is size and stand complexity.
* **Runway / stand geometry** — `departure_runway_dist_m`, `min_runway_dist_m`,
  `nearest_runway`, `runway_heading`, `runway_side`, plus the historical stand→runway exit
  statistics (`hist_avg_taxi_stand_rwy`, `hist_std_taxi_stand_rwy`, `hist_count_stand_rwy`,
  `hist_tail_rate_stand_rwy`, `n_hist_stand_rwy`, `stand_rwy_hist_mean`). The physical
  distance from the stand to the departure runway is present as a metric feature, and it is
  paired with the empirical *time* those taxiing historically takes — a straight-line
  distance alone does not know about taxiway layout, one-way flows or intersection holds,
  but the historical duration already encodes them. Coverage of the distance feature per
  airport is tabulated in `docs/FEATURES.md`; where a stand is unseen in 2025 the distance
  is missing and the historical aggregates are absent, and the model falls back on the
  airport/runway-level aggregates.
* **Traffic state** — counts and headways on the runway and at the airport in windows
  around the scheduled off-block (`per_runway_dep_30m`, `per_runway_arr_15m`,
  `rwy_queue_ahead`, `rwy_occ_sec_ahead`, `arr_land_next_10`, `dep_tko_next_15`, …).
  These describe the queue the aircraft will join.
* **Gate retention (`sql/build_ret_v20.sql`)** — a queue-state reconstruction built on the
  real push clock: *overdue* = |{EOBT ≤ t}| − |{AOBT ≤ t}| and *active on the ground* =
  |{AOBT ≤ t}| − |{MVT ≤ t}|, evaluated as event sweeps per airport/runway. This gives the
  number of aircraft actually waiting at the moment of interest rather than a scheduled
  proxy. Guards mirror the published Madrid (Barajas) departure-metering method: both clocks
  present, `0 ≤ AOBT − EOBT < 7200 s` (beyond that it is a date rollover) and `MVT ≥ AOBT`.
* **Historical aggregates (`sql/build_2025_stats.sql`, `sql/build_ranking_hist.sql`)** —
  median / p90 / mean taxi time and departure delay keyed by
  (airport, runway, hour, day-of-week) and by (airport, stand, runway), computed over 2025
  only. For a 2026 movement every 2025 movement is strictly in the past, so a full-year
  2025 aggregate *is* the trailing value a forecaster would legitimately have. Groups with
  fewer than 10 samples are dropped rather than imputed.
* **Clock-difference features** — `mvt_minus_lobt`, `mvt_minus_iobt`, `mvt_minus_eobt`,
  `mvt_minus_sched`, `sched_lobt_margin`, `to_takeoff_from_IOBT_flt`. These are the
  anchors described above, exposed to the model as ordinary numeric inputs.
* **Data-quality flags** — `is_unmatched`, `nm_missing`, `missing_ac_type`,
  `missing_iobt_eobt`, `missing_callsign`, `is_artifact`, `is_extreme_taxi`. The join
  between movement records and NM flight records is imperfect in the source data; rather
  than silently dropping or repairing those rows, the mismatch is made explicit so the
  model can learn that an unmatched row is a *different kind of prediction problem*.
* **Weather** — ERA5 reanalysis on a (52.5, −5.0)–(39.5, 30.0) bounding box, joined
  laterally to the nearest observation within ±30 min of scheduled off-block: temperature,
  dewpoint, relative humidity, wind direction/speed, cloud layers, visibility, and derived
  low-visibility / snow / freezing / thunderstorm flags.

**Ex-ante discipline.** `BLOCK_TIME_UTC_mvt` and anything derived from it are excluded
throughout — it is the target's other endpoint. So are `MVT_ID_mvt`, `FLIGHT_ID_mvt` and
`FLIGHT_mvt` as model inputs: they are identifiers, and a tree model will memorise them
rather than generalise. (They are kept in the working tables purely as join keys.)

### 2.2 Models

* **Per-airport LightGBM regressors.** One model per airport, trained in Dataiku DSS on
  the 2025 movements, with a **time-ordered split** (sorted on scheduled time) so that no
  fold ever predicts the past from the future. Per-airport models rather than one pooled
  model: runway topology, stand layout, ATFM regime and carrier mix differ enough between
  these ten airports that a shared model spends its capacity learning the airport instead
  of the taxi behaviour.
* **A "copy" classifier** (`is_copy`, `src/blend_fill.py`, `sql/` blend tables). A second
  model that predicts, per row, the probability that the best available answer is simply to
  *copy* an anchor — i.e. that LOBT/SCHED is trustworthy for this movement. It yields a
  blend weight `p`. Where a copy partition is unavailable, `p` falls back to a calibrated
  airport × operator × delay-band table.

### 2.3 Post-processing (`src/`)

Applied in this order:

1. **Anchor clamp** (`ship.py`, `CLAMP = 3606`) — clip the prediction into
   `[A − 3606, A + 3606]` where `A = MVT − LOBT`. A departure that took off more than an
   hour from its last known off-block is either a stale LOBT or a de-icing/queue event; in
   both cases the plausible answer is bounded by the anchor. Applied only where LOBT exists.
2. **Copy blend** — `y = (1 − p) · model + p · (MVT − SCHED)`. The blend is what handles
   ATFM-delayed departures, where the model's "typical taxi time" is the wrong answer but
   the scheduled-to-takeoff gap is close to right.
3. **Tail calibration** (`src/calibrate.py`, `src/calib_blend.py`) — the regressor is
   systematically low in the upper prediction buckets. Bucket by predicted value, take the
   mean truth per bucket from **out-of-time** rows, and apply a *shrunk* piecewise-linear
   correction (`λ` shrinks the curve toward the identity) so a ~400 k-row fit cannot chase
   noise. The shrink factor is chosen on held-out rows, never on the board.
4. **Range clip** to `[60, 20000]` s.

`src/anchor_tail.py` tests whether the anchor should replace or blend with the model in the
long-tail band, on the full out-of-time holdout, deliberately biased in favour of the model.

---

## 3. Design decisions worth stating

| Decision | Why |
|---|---|
| Treat the problem as clock reconciliation, not taxi-time regression | Both endpoints of the target are observable in the ranking data in some form; ignoring them discards the strongest signal available. |
| Clamp predictions to the LOBT anchor | Bounds the damage from stale LOBT and from a model extrapolating into ATFM regimes it never saw. |
| Blend with `MVT − SCHED` via a learned copy probability | Delayed departures have long taxi times for a *schedulable* reason; the model alone under-predicts them. |
| Per-airport models | Airport-specific topology dominates the residual; a pooled model spends capacity on the wrong thing. |
| Historical aggregates keyed by (airport, runway, hour, dow) and (airport, stand, runway) | Encodes real taxi distances and queue behaviour empirically, including the stand→runway component, without needing an airport map. |
| Time-ordered validation only | A random split leaks the same day, the same weather and the same ATFM event into train and test. |
| Shrink all calibration toward the identity | Calibration fit on hundreds of thousands of rows can over-fit the tail; shrinking bounds the harm if it does not transfer. |
| Keep data-quality flags as features | The movement↔flight match is genuinely broken in places; pretending otherwise makes the model confidently wrong on those rows. |
| Reject identifier and off-block-derived columns as inputs | Direct leakage of the target. |

---

## 4. Results

Official scores from the challenge scoring service (`<file>_result.json` in the submission
bucket, scored against `truthing.parquet` over 344,841 Jan+Jul departure pairs). Lower is
better; the metric is RMSE in seconds.

| Submission | Official score |
|---|---|
| v2 | 598.30 |
| v3 | 567.60 |
| v4 | 543.89 |
| v7 | 536.37 |
| v5 | 514.08 |
| v6 | 439.91 |
| v8 | 436.57 |
| v14 | 437.41 |
| v9 | 437.42 |
| v12 | 434.42 |
| **v13** | **434.22** |
| v15 | 434.26 |

v1 was uploaded but no stored score for it remains in the bucket. v11 and v16 were
rejected by the five-uploads-per-day limit and were never scored.

The large step is v5 → v6 (514 → 440): introducing the anchor clamp plus the copy blend.
Everything after that is refinement, and the last four entries are within ~0.2 s of each
other — i.e. the approach had plateaued, which is why the final submission reuses the
best-measured version rather than an untested variant.

A note on internal metrics: local out-of-time holdout CSVs were produced with
`src/score_standalone.py`. Some of those exports have a column-mapping defect (the target
column is read as a timestamp, producing impossible negative "truths"), so **holdout RMSE
figures from those files are not reliable** and are not used as evidence here. Decisions
were validated against the official board scores. `src/calibrate.py` and
`src/calib_blend.py` carry their fit figures in their docstrings; those describe what was
observed at the time and are not independently reproducible from this repository because
the holdout export they were fit on is not redistributed.

---

## 5. Data

Provided by the challenge (OpenSky / Network Manager), not redistributed here:

* Training: `training_2025-<month>.parquet`, twelve monthly files, 2025, 4,167,797
  movements at the ten airports. Instructions:
  <https://ansperformance.eu/study/data-challenge/dc2026/data.html>
* Ranking: `ranking.parquet` (Jan and Jul 2026) and the final-phase ranking
  (Jan, Feb, Jun, Jul 2026), with `BLOCK_TIME_UTC_mvt` and `TAXITIME_SEC_mvt` blanked for
  departures.
* Weather: ERA5 reanalysis (Copernicus CDS), hourly, bounding box
  (52.5 N, 5.0 W)–(39.5 N, 30.0 E), covering all ten airports. Fetch with the CDS API;
  store all variables and select at query time.

Everything in `sql/` runs against a PostgreSQL instance into which the parquet files are
imported. Table names in the scripts are the ones used during the challenge
(`PRC_prc_enriched_prepared`, `PRC_prc_ranking_prepared`, `prc_movements_raw`, …); adjust
them to your own import schema.

## 6. Layout

```
smart-apple/
├── README.md                 this file
├── LICENSE                   MIT
├── requirements.txt
├── smart-apple_final.parquet the submitted entry (670,790 rows)
├── sql/
│   ├── build_2025_stats.sql        2025 delay + taxi-roll aggregates
│   ├── build_ranking_hist.sql      historical taxi aggregates for 2026 rows
│   ├── fill_training_hist.sql      attach history to the training table
│   ├── fill_ranking_hist.sql       attach history to the ranking table
│   ├── build_ret_v20.sql           gate-retention queue state on the real push clock
│   ├── build_tf_v20.sql            take-off/landing event tables feeding the queue features
│   └── predict_export_example.sql  the exact feature vector exported for inference
├── docs/
│   └── FEATURES.md           feature families and their ex-ante justification
└── src/
    ├── ship.py               predictions -> valid board + final submission files
    ├── upload.py             upload to the challenge MinIO bucket
    ├── calibrate.py          fit the shrunk tail calibration on out-of-time residuals
    ├── calib_blend.py        calibration composed with the copy blend (produced the final)
    ├── blend_fill.py         fill a missing copy partition from the calibrated q table
    ├── blend_variants.py     compare blend formulations on the holdout
    ├── anchor_tail.py        test anchor replace/blend rules in the long-tail band
    ├── copy_ceiling.py       measure the ceiling of pure copy behaviour
    ├── compare_holdout.py    compare two sessions on identical held-out rows
    ├── score_standalone.py   score exported Dataiku test folds outside Dataiku
    └── score_s83_standalone.py
```

## 7. Reproducing the submission

```bash
pip install -r requirements.txt

# 1. import the challenge parquet files into PostgreSQL, then build features
psql -f sql/build_2025_stats.sql
psql -f sql/build_ranking_hist.sql
psql -f sql/fill_training_hist.sql
psql -f sql/fill_ranking_hist.sql

# 2. train the per-airport regressors and the copy classifier in Dataiku DSS
#    (time-ordered split on scheduled time, RMSE as the grid-search metric)

# 3. export predictions for the ranking rows, then post-process
python src/calib_blend.py 0.5              # -> preds-calibblend.parquet

# 4. build the submission files (validates row count and id order against the templates)
python src/ship.py preds-calibblend.parquet 13

# 5. upload the board file for scoring; rename final_13 to smart-apple_final.parquet
python src/upload.py smart-apple_v13.parquet smart-apple_v13.parquet
```

## 8. Known limitations

* The final ranking is evaluated on February and June 2026 — months that never appeared on
  the public leaderboard. 48.6 % of the submitted file is therefore not measurable before
  submission. We verified those months are structurally consistent with the measured ones
  (LOBT coverage 98.4–99.1 %, comparable anchor distributions, no clamp saturation, no
  per-airport drift) rather than assuming it.
* The tail calibration was fit on 2025 residuals and applied to 2026. Whether that transfer
  is net-positive can only be decided by the board, and the last board slots were already
  spent. The shrink factor exists precisely to bound the downside if it does not transfer.
* A small number of predictions exceed the 99.9th percentile of observed taxi-out at their
  airport (284 of 670,790 rows). These are cases where the model rejects a suspect LOBT.
  Hard-capping them is worth at most ~3.8 s of RMSE and cannot be validated, so we left
  them as the model produced them.
* Stand→runway distance is represented through historical taxi-time statistics for the
  (airport, stand, runway) key rather than from an airport map, so stands never seen in
  2025 have no such feature.
