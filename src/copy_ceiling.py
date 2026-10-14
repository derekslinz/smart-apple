"""How much is the copy regime worth on the live board population (Jan+Jul 2026)?

Copy regime: BLOCK was recorded as SCHED, so the scored truth is exactly (MVT - SCHED).
Copy-ness is not observable at prediction time, but its per-airport/band rate is measurable
in 2025. This estimates the RMSE of mixing the s14 model with the exact copy anchor using
those rates -- i.e. the ceiling a copy classifier could reach.
"""
import numpy as np, pandas as pd, glob
import pyarrow.parquet as pq

W = '/root/.hermes/profiles/prc/cache/scratch/'
import subprocess
os_env = {'PGPASSWORD': 'postgres'}

# 1. board population (344,841 DEP rows, Jan+Jul 2026)
r = pq.read_table('/mnt/tmp/dss/ranking.parquet').to_pandas()
dep = r[r.PHASE_mvt == 'DEP'].copy()
for c in ('MVT_TIME_UTC_mvt', 'SCHED_TIME_UTC_mvt', 'LOBT_flt', 'AOBT_3_flt'):
    dep[c] = pd.to_datetime(dep[c], errors='coerce', utc=True)
dep['MVT_ID_mvt'] = pd.to_numeric(dep['MVT_ID_mvt'], errors='coerce').astype('int64')
dep['ms'] = (dep.MVT_TIME_UTC_mvt - dep.SCHED_TIME_UTC_mvt).dt.total_seconds()
dep['ml'] = (dep.MVT_TIME_UTC_mvt - dep.LOBT_flt).dt.total_seconds()
print(f'board DEP rows: {len(dep)}  with LOBT: {dep.ml.notna().sum()}')

# 2. 2025 copy rates by airport x band of (MVT - SCHED)
q = subprocess.run(['psql', '-h', '10.0.1.25', '-U', 'postgres', '-d', 'postgres', '-tAF|', '-c',
    """select "ADEP_mvt", width_bucket(coalesce(mvt_minus_sched,0), array[0,600,1200,1800,2700,3600,5400,10800]) band,
           count(*) n, sum(case when abs(mvt_minus_sched - "TAXITIME_SEC_mvt") <= 60 then 1 else 0 end) c
           from prc_enriched group by 1,2"""], capture_output=True, text=True, env={**__import__('os').environ, **os_env}).stdout
rates = {}
for line in q.strip().splitlines():
    apt, band, n, c = line.split('|')
    rates[(apt, int(band))] = int(c) / max(int(n), 1)
print(f'copy-rate table: {len(rates)} airport-band cells')


def copy_rate(row):
    return rates.get((row.ADEP_mvt, int(np.clip(np.searchsorted([0, 600, 1200, 1800, 2700, 3600, 5400, 10800], row.ms), 1, 7)))), 0.0


dep['q'] = [rates.get((a, int(np.clip(np.searchsorted([0, 600, 1200, 1800, 2700, 3606, 5400, 10800], m), 1, 7))), 0.0)
             for a, m in zip(dep.ADEP_mvt, dep.ms.fillna(0))]

# 3. s14 predictions for the board ids
preds = {}
for f in glob.glob(W + 'pred-rank-s14-*.csv'):
    d = pd.read_csv(f)
    d['MVT_ID_mvt'] = pd.to_numeric(d['MVT_ID_mvt'], errors='coerce').astype('int64')
    for i, v in zip(d.MVT_ID_mvt, d.TAXITIME_SEC_mvt):
        preds[int(i)] = float(v)
dep['p'] = [preds.get(int(i), np.nan) for i in dep.MVT_ID_mvt]
print(f's14 predictions matched: {dep.p.notna().sum()} / {len(dep)}')

# 4. proxy truths.  For copy rows the scored truth is ms (= MVT - SCHED); the LOBT proxy
#    measures the REAL taxi-out.  Blend the proxy with the copy anchor by the measured rate.
W_CLAMP = 3606
p_clamped = np.where(np.isfinite(dep.ml), np.clip(dep.p, dep.ml - W_CLAMP, dep.ml + W_CLAMP), dep.p)
y_true_est = dep.q * dep.ms + (1 - dep.q) * dep.ml          # expected scored truth
anchor = dep.ms                                             # exact answer for copy rows


def rmse(p, y):
    m = np.isfinite(p) & np.isfinite(y)
    return float(np.sqrt(((p[m] - y[m]) ** 2).mean())), int(m.sum())


for name, p in [('s14 raw', dep.p.values), ('s14 + LOBT clamp', p_clamped),
                ('s14 + clamp + copy mixture (q from 2025)', (1 - dep.q.values) * p_clamped + dep.q.values * anchor)]:
    r1, n1 = rmse(p.values if hasattr(p, 'values') else p, y_true_est.values)
    print(f'{name:48s} RMSE vs expected-truth model: {r1:7.1f}  (n={n1})')

# 5. per-airport view of the mixture delta
print('\nper-airport delta (mixture - clamp only), and rows where the anchor dominates:')
tot = {'c': 0.0, 'm': 0.0, 'n': 0}
for apt, g in dep.groupby('ADEP_mvt'):
    a, na = rmse((1 - g.q) * np.where(np.isfinite(g.ml), np.clip(g.p, g.ml - W_CLAMP, g.ml + W_CLAMP), g.p) + g.q * g.ms,
                 ((g.q * g.ms + (1 - g.q) * g.ml)).values)
    b, nb = rmse(np.where(np.isfinite(g.ml), np.clip(g.p, g.ml - W_CLAMP, g.ml + W_CLAMP), g.p),
                 ((g.q * g.ms + (1 - g.q) * g.ml)).values)
    tot['c'] += a * a * na; tot['m'] += b * b * nb; tot['n'] += na
    print(f'  {apt}: n={na:6d} q_max={g.q.max():.2f}  clamped {b:7.1f}  mixture {a:7.1f}  delta {a-b:+7.1f}')
print(f'  AGGREGATE clamped {np.sqrt(tot["m"]/tot["n"]):7.1f}  mixture {np.sqrt(tot["c"]/tot["n"]):7.1f}  delta {np.sqrt(tot["c"]/tot["n"])-np.sqrt(tot["m"]/tot["n"]):+7.1f}')
