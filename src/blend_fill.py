"""Fill the missing copy-model airport with the calibrated copy-rate table.

The per-airport copy classifier (session s2) completed 9 of 10 partitions - EGLL failed on a transient
race - so the scored v8 applies no blend at all to EGLL's 39,840 board rows, even though the calibrated
airport x operator x band table assigns them a mean copy probability of 0.097 (median 0.074).

This is a one-airport change against v8: identical everywhere else.

Usage: blend_fill.py <regressor_session> <copy_session> <tag> <q_csv> <ADEP>
"""
import sys, glob
import numpy as np, pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

W = '/root/.hermes/profiles/prc/cache/scratch/'
REG, COPY, TAG, QCSV, APT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
CLAMP = 3606

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
        val = [c for c in d.columns if c != 'MVT_ID_mvt'][0]
        frames.append(d.rename(columns={val: 'v'})[['MVT_ID_mvt', 'v']])
    if not frames:
        sys.exit(f'no pred-rank-{sess}-*.csv')
    return pd.concat(frames).groupby('MVT_ID_mvt', as_index=False).v.mean()


reg, cp = load(REG), load(COPY)
dep = dep.merge(reg.rename(columns={'v': 'reg'}), on='MVT_ID_mvt', how='left') \
         .merge(cp.rename(columns={'v': 'p'}), on='MVT_ID_mvt', how='left')
# psql \copy ... with (format csv) writes no header row
q = pd.read_csv(QCSV, header=None, names=['MVT_ID_mvt', 'qfill'])
dep = dep.merge(q, on='MVT_ID_mvt', how='left')

use_q = (dep.ADEP_mvt == APT) & dep.p.isna()
p = np.where(use_q, np.nan_to_num(dep.qfill.values, nan=0.0), np.nan_to_num(dep.p.values, nan=0.0))
p = np.clip(p, 0.0, 1.0)
print(f'{APT}: rows filled from the q table = {int(use_q.sum())} / {int((dep.ADEP_mvt == APT).sum())}')

base = np.where(np.isfinite(dep.ml), np.clip(dep.reg.values, dep.ml - CLAMP, dep.ml + CLAMP), dep.reg.values)
anchor = np.where(np.isfinite(dep.ms), dep.ms, base)
y = np.clip((1 - p) * base + p * anchor, 60, 20000)
print(f'mean p {p.mean():.4f}  rows moved {int((np.abs(y - base) > 1).sum())}/{len(dep)}')

out = pd.DataFrame({'MVT_ID_mvt': dep.MVT_ID_mvt.values, 'TAXITIME_SEC_mvt': y.astype('int32')})
pq.write_table(pa.Table.from_pandas(out), f'/var/tmp/prc/preds-{TAG}.parquet')
print(f'wrote /var/tmp/prc/preds-{TAG}.parquet rows={len(out)}')
