"""Isotonic-style calibration of the regressor against its own out-of-time residuals.

The model under-predicts the tail: on the Oct-Dec 2025 holdout it answers 1,258 where the truth is 1,304
(30-60 min band) and 1,456 where the truth is 1,624 (60-90 min band). On the board the tail is larger and
more frequent, so a calibration learned on 2025 residuals should help there at least as much.

Method: bucket by predicted value, compute mean truth per bucket, then apply a *shrunk* piecewise-linear
correction (shrink lambda toward the identity) so a 400k-row fit cannot chase noise. Everything is measured
on the same out-of-time rows the model was never trained on.

Usage: calibrate.py [session]
"""
import sys
import numpy as np, pandas as pd

W = '/root/.hermes/profiles/prc/cache/scratch/'
S = sys.argv[1] if len(sys.argv) > 1 else 's82'
CLAMP = 3606

d = pd.read_csv(f'{W}holdout-{S}-ALL.csv', usecols=['MVT_ID_mvt', 'apt', 'pred', 'y', 'mvt_minus_lobt'])
d = d.dropna(subset=['pred', 'y'])
d['p'] = np.where(np.isfinite(d.mvt_minus_lobt), np.clip(d.pred, d.mvt_minus_lobt - CLAMP, d.mvt_minus_lobt + CLAMP), d.pred)
p = d.p.values
y = d.y.values
print(f'{S}: rows={len(d)}  rmse(clamped)={np.sqrt(np.mean((p-y)**2)):.1f}')

EDGES = [0, 400, 700, 1000, 1300, 1600, 2000, 2500, 3000, 4000, 20000]
b = np.clip(np.searchsorted(EDGES, p, side='right') - 1, 0, len(EDGES) - 2)
print(f'\n{"bucket":>16} {"n":>7} {"mean_pred":>10} {"mean_truth":>11} {"bias":>8}   n_ge_200')
cent, truth = [], []
for i in range(len(EDGES) - 1):
    m = b == i
    if m.sum() < 200:
        continue
    cent.append((p[m].mean(), y[m].mean(), int(m.sum())))
    print(f'{EDGES[i]:6d}-{EDGES[i+1]:6d} {int(m.sum()):7d} {p[m].mean():10.0f} {y[m].mean():11.0f} '
          f'{y[m].mean()-p[m].mean():+8.0f}   {int((y[m] >= 2000).sum())}')

cx = np.array([c[0] for c in cent]); cy = np.array([c[1] for c in cent])
o = np.argsort(cx); cx, cy = cx[o], cy[o]
print('\ncalibration ladder (lambda = shrink toward identity):')
for lam in (0.0, 0.2, 0.35, 0.5, 0.7, 1.0):
    corr = p + lam * (np.interp(p, cx, cy) - p)
    r = float(np.sqrt(np.mean((np.clip(corr, 60, 20000) - y) ** 2)))
    print(f'  lambda={lam:.2f}  rmse={r:.1f}  shift_mean={np.mean(corr-p):+7.1f}  '
          f'p99_shift={np.percentile(corr-p,99):+8.1f}')

# per-airport calibration is the natural next step - measure whether the bias is shared or local
print('\nbias in the >=1600s prediction bucket, by airport:')
m = p >= 1600
for apt, g in pd.DataFrame({'apt': d.apt, 'p': p, 'y': y})[m].groupby('apt'):
    if len(g) >= 50:
        print(f'  {apt}  n={len(g):5d}  mean_pred={g.p.mean():7.0f}  mean_truth={g.y.mean():7.0f}  bias={g.y.mean()-g.p.mean():+8.0f}')
