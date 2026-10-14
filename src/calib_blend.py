"""Tail calibration composed with the learned-copy blend.

Two independently validated components, applied in order:
  1. calibrate: the regressor is systematically low in the upper prediction buckets at all ten airports
     (+33 at 1300-1600s, +144 at 1600-2000s, +466 at 2000-2500s, +492 at 2500-3000s on 412k out-of-time
     rows). A shrunk piecewise correction over those buckets takes the 2025 holdout 208.6 -> 206.3.
  2. blend: y = (1-p)*base + p*(MVT - SCHED) with p from the learned per-airport copy classifier,
     falling back to the calibrated airport x operator x band q table where a copy partition is missing.

The calibration is fit on out-of-time 2025 residuals and applied to 2026 predictions; the board is the
only instrument that can decide whether it transfers.

Usage: calib_blend.py <lambda>
"""
import sys, glob
import numpy as np, pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

W = '/root/.hermes/profiles/prc/cache/scratch/'
LAM = float(sys.argv[1]) if len(sys.argv) > 1 else 0.5
CLAMP = 3606
MIN_BUCKET = 200

# --- 1. fit the calibration curve from the out-of-time holdout ---
h = pd.read_csv(f'{W}holdout-s82-ALL.csv', usecols=['pred', 'y', 'mvt_minus_lobt']).dropna()
hp = np.where(np.isfinite(h.mvt_minus_lobt), np.clip(h.pred, h.mvt_minus_lobt - CLAMP, h.mvt_minus_lobt + CLAMP), h.pred)
EDGES = [0, 400, 700, 1000, 1300, 1600, 2000, 2500, 3000, 4000, 20000]
b = np.clip(np.searchsorted(EDGES, hp, side='right') - 1, 0, len(EDGES) - 2)
cx, cy = [], []
for i in range(len(EDGES) - 1):
    m = b == i
    if m.sum() >= MIN_BUCKET:
        cx.append(hp[m].mean()); cy.append(h.y.values[m].mean())
cx, cy = np.array(cx), np.array(cy); o = np.argsort(cx); cx, cy = cx[o], cy[o]
print(f'calibration knots ({len(cx)}): ' + ' '.join(f'{a:.0f}->{bb:.0f}' for a, bb in zip(cx, cy)))
print(f'baseline holdout rmse={np.sqrt(np.mean((hp - h.y.values) ** 2)):.1f}')
for lam in (0.0, LAM):
    c = hp + lam * (np.interp(hp, cx, cy) - hp)
    print(f'  lambda={lam:.2f} -> holdout rmse={np.sqrt(np.mean((np.clip(c,60,20000) - h.y.values) ** 2)):.1f}')

# --- 2. apply to the 2026 ranking rows, then blend with the copy classifier ---
r = pq.read_table('/mnt/tmp/dss/final_ranking.parquet').to_pandas()
dep = r[r.PHASE_mvt == 'DEP'].copy()
dep['MVT_ID_mvt'] = pd.to_numeric(dep['MVT_ID_mvt'], errors='coerce').astype('int64')
for c in ('MVT_TIME_UTC_mvt', 'SCHED_TIME_UTC_mvt', 'LOBT_flt'):
    dep[c] = pd.to_datetime(dep[c], errors='coerce', utc=True)
dep['ms'] = (dep.MVT_TIME_UTC_mvt - dep.SCHED_TIME_UTC_mvt).dt.total_seconds()
dep['ml'] = (dep.MVT_TIME_UTC_mvt - dep.LOBT_flt).dt.total_seconds()


def load(sess):
    frames = []
    for f in glob.glob(f'{W}pred-rank-{sess}-*.csv'):
        d = pd.read_csv(f)
        d['MVT_ID_mvt'] = pd.to_numeric(d['MVT_ID_mvt'], errors='coerce').astype('int64')
        v = [c for c in d.columns if c != 'MVT_ID_mvt'][0]
        frames.append(d.rename(columns={v: 'val'})[['MVT_ID_mvt', 'val']])
    return pd.concat(frames).groupby('MVT_ID_mvt', as_index=False).val.mean()


reg = pq.read_table('/var/tmp/prc/preds-s82.parquet').to_pandas()
reg['MVT_ID_mvt'] = pd.to_numeric(reg['MVT_ID_mvt'], errors='coerce').astype('int64')
dep = dep.merge(reg.rename(columns={'TAXITIME_SEC_mvt': 'reg'})[['MVT_ID_mvt', 'reg']], on='MVT_ID_mvt')
dep = dep.merge(load('copy2').rename(columns={'val': 'p'}), on='MVT_ID_mvt', how='left')
q = pd.read_csv('/var/tmp/prc/egl_board_q.csv', header=None, names=['MVT_ID_mvt', 'q'])
dep = dep.merge(q, on='MVT_ID_mvt', how='left')

base0 = np.where(np.isfinite(dep.ml), np.clip(dep.reg.values, dep.ml - CLAMP, dep.ml + CLAMP), dep.reg.values)
base = base0 + LAM * (np.interp(base0, cx, cy) - base0)
base = np.clip(base, 60, 20000)
p = np.clip(np.nan_to_num(np.where(dep.p.notna(), dep.p, dep.q), nan=0.0), 0.0, 1.0)
anchor = np.where(np.isfinite(dep.ms), dep.ms, base)
y = np.clip((1 - p) * base + p * anchor, 60, 20000)
print(f'calibration shifted {int((np.abs(base - base0) > 1).sum())}/{len(dep)} rows, '
      f'mean shift {np.mean(base - base0):+.1f}s, p99 {np.percentile(base - base0, 99):+.0f}s; '
      f'blend mean p={p.mean():.4f}')

out = pd.DataFrame({'MVT_ID_mvt': dep.MVT_ID_mvt.values, 'TAXITIME_SEC_mvt': y.astype('int32')})
pq.write_table(pa.Table.from_pandas(out), '/var/tmp/prc/preds-calibblend.parquet')
print(f'wrote /var/tmp/prc/preds-calibblend.parquet rows={len(out)}')
