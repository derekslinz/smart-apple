"""Compare the fixed q-table and the learned copy classifier on the SAME rows, and emit both blends.

  y = (1 - p) * clamp(regressor, mvt_minus_lobt -+ 3606) + p * (mvt - sched)

p is either the 2025 airport x operator x band q table (Laplace-shrunk toward airport x band, K pseudo-counts,
exactly the recipe that scored 439.91 as smart-apple_v6) or the learned P(copy) from the copy-regime model, or
max of the two. Rows with no copy model (airports whose partition failed) fall back to q automatically.

Usage: blend_variants.py <regressor_session> <copy_pred_tag> [K]
Writes /var/tmp/prc/preds-<variant>.parquet for q, p, max.
"""
import glob, subprocess, sys
import numpy as np, pandas as pd
import pyarrow as pa, pyarrow.parquet as pq

W = '/root/.hermes/profiles/prc/cache/scratch/'
REG, CTAG = sys.argv[1], sys.argv[2]
K = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
CLAMP = 3606
EDGES = [0, 600, 1200, 1800, 2700, 3606, 5400, 10800]
ARR = f"array[{','.join(str(e) for e in EDGES)}]"
env = {**__import__('os').environ, 'PGPASSWORD': 'postgres'}


def psql(q):
    r = subprocess.run(['psql', '-h', '10.0.1.25', '-U', 'postgres', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1',
                        '-tAF', '|', '-c', q], capture_output=True, text=True, env=env)
    if r.returncode:
        sys.exit('psql failed: ' + r.stderr[:400])
    return r.stdout


def load_preds(tag):
    frames = []
    for f in glob.glob(f'{W}pred-rank-{tag}-*.csv'):
        d = pd.read_csv(f)
        d['MVT_ID_mvt'] = pd.to_numeric(d['MVT_ID_mvt'], errors='coerce').astype('int64')
        val = [c for c in d.columns if c != 'MVT_ID_mvt'][0]
        frames.append(d.rename(columns={val: 'v'})[['MVT_ID_mvt', 'v']])
    if not frames:
        sys.exit(f'no pred-rank-{tag}-*.csv')
    return pd.concat(frames).groupby('MVT_ID_mvt', as_index=False).v.mean()


r = pq.read_table('/mnt/tmp/dss/final_ranking.parquet').to_pandas()
dep = r[r.PHASE_mvt == 'DEP'].copy()
dep['MVT_ID_mvt'] = pd.to_numeric(dep['MVT_ID_mvt'], errors='coerce').astype('int64')
for c in ('MVT_TIME_UTC_mvt', 'SCHED_TIME_UTC_mvt', 'LOBT_flt', 'AOBT_3_flt'):
    dep[c] = pd.to_datetime(dep[c], errors='coerce', utc=True)
dep['ms'] = (dep.MVT_TIME_UTC_mvt - dep.SCHED_TIME_UTC_mvt).dt.total_seconds()
dep['ml'] = (dep.MVT_TIME_UTC_mvt - dep.LOBT_flt).dt.total_seconds()
dep['y_proxy'] = (dep.MVT_TIME_UTC_mvt - dep.AOBT_3_flt).dt.total_seconds()
dep = dep.merge(load_preds(REG).rename(columns={'v': 'reg'}), on='MVT_ID_mvt', how='left')
dep = dep.merge(load_preds(CTAG).rename(columns={'v': 'p'}), on='MVT_ID_mvt', how='left')
print(f'rows={len(dep)} regressor matched={dep.reg.notna().sum()} copy model matched={dep.p.notna().sum()}')

# --- q table: airport x band prior, joint airport x operator x band, shrunk with K pseudo-counts ---
band_q, apt_q, opb = {}, {}, {}
for line in psql(f'select "ADEP_mvt", width_bucket(coalesce(mvt_minus_sched,0), {ARR}) b, count(*), '
                 f'sum(case when abs(mvt_minus_sched - "TAXITIME_SEC_mvt") <= 60 then 1 else 0 end) '
                 f'from prc_enriched group by 1,2').strip().splitlines():
    a, b, n, c = line.split('|')
    band_q[(a, int(b))] = int(c) / max(int(n), 1)
for line in psql('select "ADEP_mvt", count(*), sum(case when abs(mvt_minus_sched - "TAXITIME_SEC_mvt") <= 60 '
                 'then 1 else 0 end) from prc_enriched group by 1').strip().splitlines():
    a, n, c = line.split('|')
    apt_q[a] = int(c) / max(int(n), 1)
for line in psql(f'select "ADEP_mvt", coalesce("AIRCRAFT_OPERATOR_flt",\'NA\'), '
                 f'width_bucket(coalesce(mvt_minus_sched,0), {ARR}) b, count(*), '
                 f'sum(case when abs(mvt_minus_sched - "TAXITIME_SEC_mvt") <= 60 then 1 else 0 end) '
                 f'from prc_enriched group by 1,2,3').strip().splitlines():
    a, o, b, n, c = line.split('|')
    n, c = int(n), int(c)
    prior = band_q.get((a, int(b)), apt_q.get(a, 0.0))
    opb[(a, o, int(b))] = (c + K * prior) / (n + K)

base = np.where(np.isfinite(dep.ml), np.clip(dep.reg.values, dep.ml - CLAMP, dep.ml + CLAMP), dep.reg.values)
anchor = np.where(np.isfinite(dep.ms), dep.ms, base)
band = np.clip(np.searchsorted(EDGES, np.nan_to_num(dep.ms.values)), 1, 7)
q = np.array([opb.get((a, str(o), b), band_q.get((a, b), apt_q.get(a, 0.0)))
              for a, o, b in zip(dep.ADEP_mvt.values, dep.AIRCRAFT_OPERATOR_flt.fillna('NA').values, band)])
p = np.clip(np.nan_to_num(dep.p.values, nan=np.nan), 0.0, 1.0)
has_p = np.isfinite(p)
p_fill = np.where(has_p, p, q)                      # airports with no copy model fall back to q
pmax = np.where(has_p, np.maximum(p, q), q)         # whichever signal is stronger


def out(v):
    return np.clip(v, 60, 20000)


variants = {'q': out((1 - q) * base + q * anchor),
            'p': out((1 - p_fill) * base + p_fill * anchor),
            'max': out((1 - pmax) * base + pmax * anchor)}
print(f'mean q={q.mean():.4f}  mean p={np.nanmean(p):.4f}  mean max={pmax.mean():.4f}  '
      f'rows with a learned p={int(has_p.sum())}')
for name, v in variants.items():
    m = np.isfinite(v) & np.isfinite(dep.y_proxy.values) & (dep.y_proxy > 0)
    print(f'  {name:4}: proxy RMSE {np.sqrt(((v[m] - dep.y_proxy.values[m]) ** 2).mean()):.1f}  '
          f'mean shift vs clamped {np.nanmean(np.abs(v - base)):.1f}s  rows moved {int((np.abs(v - base) > 1).sum())}')
    tab = pd.DataFrame({'MVT_ID_mvt': dep.MVT_ID_mvt.values, 'TAXITIME_SEC_mvt': v.astype('int32')})
    pq.write_table(pa.Table.from_pandas(tab), f'/var/tmp/prc/preds-{name}.parquet')
    print(f'  wrote /var/tmp/prc/preds-{name}.parquet rows={len(tab)}')
dep.groupby('ADEP_mvt').apply(lambda g: print(f"  {g.name}: mean q={q[dep.index.isin(g.index)].mean():.3f} "
      f"mean p={np.nanmean(p[dep.index.isin(g.index)]):.3f}"))
