"""Test anchor-based tail handling on the full 10-airport out-of-time holdout.

The board error concentrates in ATFM-delayed departures: 26% of board rows have MVT-LOBT over 30 min
and the model predicts ~1,200 s there. On the holdout (Oct-Dec 2025) the same rows exist in smaller
numbers, so this measures the rule honestly for the bulk of the population and is deliberately biased
in favour of the model, not the anchor.

Rules tested, on y_hat = prediction, A = MVT - LOBT (known at inference for 98.6% of rows):
  replace  : answer A where A > N and A > y_hat + gap
  blend    : answer (1-w)*y_hat + w*A where A > N and A > y_hat + gap
  clamp    : the current rule - clip y_hat into [A-3606, A+3606]

Usage: anchor_tail.py [session]
"""
import sys
import numpy as np, pandas as pd

W = '/root/.hermes/profiles/prc/cache/scratch/'
SESS = sys.argv[1] if len(sys.argv) > 1 else 's82'
CLAMP = 3606

d = pd.read_csv(f'{W}holdout-{SESS}-ALL.csv',
                usecols=['MVT_ID_mvt', 'apt', 'pred', 'y', 'mvt_minus_lobt'])
d = d.dropna(subset=['pred', 'y'])
print(f'{SESS} holdout rows={len(d)}  anchor available={d.mvt_minus_lobt.notna().sum()}')


def rmse(p):
    return float(np.sqrt(np.mean((d.y.values - np.clip(p, 60, 20000)) ** 2)))


p = d.pred.values
a = np.nan_to_num(d.mvt_minus_lobt.values, nan=np.nan)
has = np.isfinite(a)
clamped = np.where(has, np.clip(p, a - CLAMP, a + CLAMP), p)
print(f'raw={rmse(p):.1f}  clamped={rmse(clamped):.1f}')

# how big is the tail on this holdout?
print('\nholdout rows by anchor band (same buckets as the board table):')
edges = [0, 1800, 3600, 5400, 7200, 10800]
b = np.clip(np.searchsorted(edges, np.where(has, a, -1)), 0, len(edges) - 1)
for i in range(1, len(edges)):
    m = b == i
    if m.sum():
        print(f'  {edges[i-1]/60:.0f}-{edges[i]/60:.0f} min  n={int(m.sum()):6d}  '
              f'mean_pred={p[m].mean():7.0f}  mean_anchor={a[m].mean():7.0f}  mean_truth={d.y.values[m].mean():7.0f}  '
              f'rmse_here={np.sqrt(np.mean((d.y.values[m]-clamped[m])**2)):6.1f}')

print('\nreplace / blend rules:')
for N in (1800, 2400, 3000, 3600, 4800):
    for gap in (600, 1200, 1800):
        sel = has & (a > N) & (a > clamped + gap)
        if sel.sum() < 50:
            continue
        rep = np.where(sel, a, clamped)
        print(f'  N={N:5d} gap={gap:5d}  rows={int(sel.sum()):6d}  replace={rmse(rep):.1f}', end='')
        for w in (0.3, 0.6):
            bl = np.where(sel, (1 - w) * clamped + w * a, clamped)
            print(f'  blend{w}={rmse(bl):.1f}', end='')
        print()
