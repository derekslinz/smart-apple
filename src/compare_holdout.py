"""Compare two regressor sessions on their own out-of-time holdout, joined on MVT_ID_mvt.

Both sessions must have been scored with score_holdout.py, which writes
$W/holdout-<session>-ALL.csv with columns: MVT_ID_mvt, apt, pred, y, mvt_minus_sched,
mvt_minus_lobt, sched.  `y` is that session's own target (TAXITIME_SEC_mvt, or resid_lobt for a
residual-target session - only compare sessions that share a target).

Usage: compare_holdout.py <session_a> <session_b>
"""
import sys
import numpy as np, pandas as pd

W = '/root/.hermes/profiles/prc/cache/scratch/'
A, B = sys.argv[1], sys.argv[2]


def load(sess):
    d = pd.read_csv(f'{W}holdout-{sess}-ALL.csv', usecols=['MVT_ID_mvt', 'apt', 'pred', 'y'])
    d['MVT_ID_mvt'] = pd.to_numeric(d['MVT_ID_mvt'], errors='coerce').astype('int64')
    return d.dropna().rename(columns={'pred': 'p'})


def rmse(y, p):
    return float(np.sqrt(np.mean((y - p) ** 2)))


da, db = load(A), load(B)
m = da.merge(db[['MVT_ID_mvt', 'p']], on='MVT_ID_mvt', how='inner')
print(f'{A}: rows={len(da)}   {B}: rows={len(db)}   comparable={len(m)}')
if len(m) < 1000:
    sys.exit('too few comparable rows - check the holdout exports')

ra, rb = rmse(m.y, m.p_x), rmse(m.y, m.p_y)
print(f'OVERALL  {A}={ra:.1f}  {B}={rb:.1f}  delta={ra - rb:+.1f}')
print(f'{"apt":6} {"n":>7} {A:>9} {B:>9} {"delta":>8}')
for apt, g in m.groupby('apt'):
    a, b = rmse(g.y, g.p_x), rmse(g.y, g.p_y)
    print(f'{apt:6} {len(g):7d} {a:9.1f} {b:9.1f} {a - b:+8.1f}')

print(f'\nblend ladder (w = weight on {B}):')
for w in (0.0, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0):
    print(f'  w={w:.1f}  rmse={rmse(m.y, (1 - w) * m.p_x + w * m.p_y):.1f}')
