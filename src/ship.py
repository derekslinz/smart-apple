#!/usr/bin/env python3
"""Ship any per-movement prediction file as a valid PRC submission.

Usage:
  ship.py <preds.parquet> <next_version> [--no-clamp] [--anchor-above N]

<preds.parquet> must contain MVT_ID_mvt + TAXITIME_SEC_mvt for the 670,790
final-phase departures (any superset is fine; rows are selected per template).

Writes:
  /var/tmp/prc/smart-apple_v<version>.parquet          board  (344,841 rows, Jan+Jul)
  /var/tmp/prc/smart-apple_final_<version>.parquet     final (670,790 rows, 4 months)
Both are validated against the real templates in /mnt/tmp/dss (row count, id order).
Upload only the board file as <team>_v<version>.parquet; rename the final one to
smart-apple_final.parquet when you decide the final.
"""
import sys, argparse, numpy as np, pandas as pd

W = 3606
BOARD_TPL = '/mnt/tmp/dss/submitting.parquet'
FINAL_TPL = '/mnt/tmp/dss/final_submitting.parquet'
RANKING = '/mnt/tmp/dss/final_ranking.parquet'
OUT = '/var/tmp/prc/smart-apple_%s.parquet'


def load_bounds():
    dep = pd.read_parquet(RANKING, columns=['MVT_ID_mvt', 'PHASE_mvt', 'MVT_TIME_UTC_mvt', 'LOBT_flt'])
    dep = dep[dep.PHASE_mvt == 'DEP']
    a = (dep.MVT_TIME_UTC_mvt - dep.LOBT_flt).dt.total_seconds().values
    ids = dep.MVT_ID_mvt.astype('int64').values
    return {int(i): (None if np.isnan(v) else (v - W, v + W, v)) for i, v in zip(ids, a)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('preds')
    ap.add_argument('version')
    ap.add_argument('--no-clamp', action='store_true')
    ap.add_argument('--anchor-above', type=float, default=None,
                    help='answer MVT-LOBT instead of the model where the anchor exceeds N seconds')
    ap.add_argument('--no-upload', action='store_true')
    a = ap.parse_args()

    p = pd.read_parquet(a.preds)
    pred = {int(i): float(v) for i, v in zip(p.MVT_ID_mvt, p.TAXITIME_SEC_mvt)}
    bounds = load_bounds()
    print('predictions loaded: %d ids; anchor bounds for %d rows' % (len(pred), len(bounds)))

    def transform(i):
        v = pred[int(i)]
        b = bounds.get(int(i))
        if b is None:
            return v
        lo, hi, anchor = b
        if a.anchor_above is not None and anchor > a.anchor_above:
            v = anchor
        if not a.no_clamp:
            v = min(max(v, lo), hi)
        return v

    for tpl, name in [(BOARD_TPL, 'v%s' % a.version), (FINAL_TPL, 'final_%s' % a.version)]:
        t = pd.read_parquet(tpl)
        ids = t.MVT_ID_mvt.values
        missing = [int(i) for i in ids if int(i) not in pred]
        if missing:
            sys.exit('ERROR: %d template ids missing from predictions (e.g. %s)' % (len(missing), missing[:3]))
        vals = np.array([transform(i) for i in ids], dtype='float64')
        out = OUT % name
        pd.DataFrame({'MVT_ID_mvt': ids, 'TAXITIME_SEC_mvt': vals}).to_parquet(out, index=False)
        chk = pd.read_parquet(out)
        ok = len(chk) == len(t) and bool((chk.MVT_ID_mvt.values == t.MVT_ID_mvt.values).all())
        print('%s: rows %d exact-template %s nulls %d min %.0f max %.0f mean %.1f'
              % (out, len(chk), ok, int(chk.TAXITIME_SEC_mvt.isna().sum()),
                 chk.TAXITIME_SEC_mvt.min(), chk.TAXITIME_SEC_mvt.max(), chk.TAXITIME_SEC_mvt.mean()))
        if not ok:
            sys.exit('ERROR: template match failed')


if __name__ == '__main__':
    main()
