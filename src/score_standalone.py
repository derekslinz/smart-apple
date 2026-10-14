"""Standalone holdout scorer: loads clf.pkl models directly, scores exported test CSVs.
Replicates Dataiku preprocessing: imputation + pandas categorical encoding."""
import sys, os, json, glob
import numpy as np, pandas as pd, pickle

SESS = sys.argv[1]
BASE = f'/mnt/tmp/dss/analysis-data/PRC/veDfhgrl/XtrjkX73/sessions/{SESS}'
SCRATCH = '/root/.hermes/profiles/prc/cache/scratch'

all_results = []
for part_dir in sorted(glob.glob(f'{BASE}/pp1-part-*')):
    apt = os.path.basename(part_dir).replace('pp1-part-', '')
    clf_path = f'{part_dir}/m1/clf.pkl'
    if not os.path.exists(clf_path):
        print(f'{apt}: no clf.pkl, skipping'); continue

    ref = json.load(open(f'{part_dir}/split_ref.json'))
    iid = ref['splitInstanceId']
    test_csv = f'{SCRATCH}/{iid}.csv.gz'
    if not os.path.exists(test_csv):
        print(f'{apt}: no test export, skipping'); continue

    sd = json.load(open(f'/mnt/tmp/dss/analysis-data/PRC/veDfhgrl/XtrjkX73/splits/{iid}.json'))
    feature_order = [c['name'] for c in sd['schema']['columns']]

    df = pd.read_csv(test_csv, sep='\t', header=None, names=feature_order, dtype=str)
    print(f'{apt}: loaded {len(df)} rows')

    with open(clf_path, 'rb') as f:
        model = pickle.load(f)

    model_features = list(model.feature_names_in_)
    target_idx = feature_order.index('TAXITIME_SEC_mvt')
    mvt_idx = feature_order.index('MVT_ID_mvt')
    y = pd.to_numeric(df.iloc[:, target_idx], errors='coerce').values
    mvt_ids = pd.to_numeric(df.iloc[:, mvt_idx], errors='coerce').values

    # Build the 168-feature matrix in model's expected order
    X = pd.DataFrame(index=df.index)
    for col in model_features:
        if col in df.columns:
            X[col] = df[col]
        else:
            X[col] = np.nan

    # Apply imputation from imputed.json
    imp = json.load(open(f'{part_dir}/imputed.json'))
    num_cols = imp.get('num_columns', [])
    num_vals = imp.get('num_values', [])
    for col, val in zip(num_cols, num_vals):
        if col in X.columns:
            X[col] = pd.to_numeric(X[col], errors='coerce').fillna(val)

    cat_cols = imp.get('cat_columns', [])
    cat_vals = imp.get('cat_values', [])
    for col, val in zip(cat_cols, cat_vals):
        if col in X.columns:
            X[col] = X[col].fillna(val)

    # Apply pandas categorical encoding from category_levels.json
    cat_levels = json.load(open(f'{part_dir}/category_levels.json'))
    for col in model_features:
        if col in cat_levels:
            levels = cat_levels[col]
            X[col] = pd.Categorical(X[col], categories=levels)

    # Convert non-categorical to float
    for col in model_features:
        if col not in cat_levels:
            X[col] = pd.to_numeric(X[col], errors='coerce')

    # Predict
    try:
        pred = model.predict(X)
    except Exception as e:
        print(f'{apt}: predict failed: {e}')
        continue

    valid = ~np.isnan(y) & ~np.isnan(pred)
    all_results.append(pd.DataFrame({
        'MVT_ID_mvt': mvt_ids[valid], 'apt': apt,
        'pred': pred[valid], 'y': y[valid],
    }))
    rmse = float(np.sqrt(np.mean((y[valid] - pred[valid]) ** 2)))
    print(f'{apt}: n={valid.sum()} RMSE={rmse:.1f}')

if all_results:
    combined = pd.concat(all_results)
    out = f'{SCRATCH}/holdout-{SESS}-ALL.csv'
    combined.to_csv(out, index=False)
    overall = float(np.sqrt(np.mean((combined.y - combined.pred) ** 2)))
    print(f'\nTOTAL: n={len(combined)} pooled RMSE={overall:.1f}')
    print(f'Wrote {out}')
