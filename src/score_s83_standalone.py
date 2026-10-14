"""Standalone s83 ranking scorer - loads pickled models and preprocessing params directly.

No Dataiku runtime needed: the preprocessing is just categorical encoding + imputation + scaling
which we can replicate from the JSON params. The models are standard LightGBM/scikit-learn.
"""
import json, pickle, glob
import numpy as np, pandas as pd

W = '/root/.hermes/profiles/prc/cache/scratch/'
BASE = '/mnt/tmp/dss/analysis-data/PRC/veDfhgrl/XtrjkX73'
SESS = 's83'
APTS = ['LIRF', 'LTFM', 'EGLL', 'LFPG', 'EDDF', 'LEMD', 'EHAM', 'LEBL', 'EDDM', 'LSZH']

# Load ranking features (already exported by export_rank.py)
def load_ranking(apt):
    f = f'{W}rank-{SESS}-{apt}.csv.gz'
    # The export has 196 columns (split schema columns) - first is MVT_ID_mvt, last is target (blank)
    # We need to know the column names from the split definition
    split_ref = json.load(open(f'{BASE}/sessions/{SESS}/pp1-part-{apt}/split_ref.json'))
    sd = json.load(open(f'{BASE}/splits/' + split_ref['splitInstanceId'] + '.json'))
    cols = [c['name'] for c in sd['schema']['columns']]
    df = pd.read_csv(f, compression='gzip', sep='\t', header=None, names=cols)
    return df


def load_preprocessing(apt):
    SESS_DIR = f'{BASE}/sessions/{SESS}/pp1-part-{apt}/'
    pp_params = json.load(open(SESS_DIR + 'rpreprocessing_params.json'))
    modeling_params = json.load(open(SESS_DIR + 'm1/rmodeling_params.json'))
    collector_data = json.load(open(SESS_DIR + 'collector_data.json'))
    return pp_params, modeling_params, collector_data


def load_model(apt):
    with open(f'{BASE}/sessions/{SESS}/pp1-part-{apt}/m1/clf.pkl', 'rb') as f:
        return pickle.load(f)


# The target for s83 is resid_lobt = TAXITIME - (MVT - LOBT)
# We need to reconstruct taxi time: TAXITIME = resid_lobt + (MVT - LOBT)
# MVT-LOBT is available in the ranking data as mvt_minus_lobt

for apt in APTS:
    print(f'\n=== {apt} ===')
    df = load_ranking(apt)
    pp_params, modeling_params, collector_data = load_preprocessing(apt)
    clf = load_model(apt)
    
    # Get target column name
    target = next((k for k, v in pp_params['per_feature'].items() if v.get('role') == 'TARGET'),
                  modeling_params.get('targetVariable', 'TAXITIME_SEC_mvt'))
    print(f'target: {target}')
    
    # Simple preprocessing replication:
    # 1. Drop target column
    X = df.drop(columns=[target], errors='ignore')
    
    # 2. Handle categoricals - dataiku uses ordinal encoding from collector_data
    cat_cols = [k for k, v in pp_params['per_feature'].items() 
                if v.get('role') == 'INPUT' and v.get('type') == 'CATEGORY']
    print(f'categorical cols: {len(cat_cols)}')
    
    for col in cat_cols:
        if col in X.columns:
            mapping = collector_data.get('categories', {}).get(col, {})
            if mapping:
                X[col] = X[col].map(mapping).fillna(-1).astype(int)
            else:
                X[col] = pd.factorize(X[col])[0]
    
    # 3. Handle numeric - impute with mean from collector_data
    num_cols = [k for k, v in pp_params['per_feature'].items() 
                if v.get('role') == 'INPUT' and v.get('type') == 'NUMERIC']
    for col in num_cols:
        if col in X.columns:
            mean_val = collector_data.get('means', {}).get(col, 0)
            X[col] = pd.to_numeric(X[col], errors='coerce').fillna(mean_val)
    
    # 4. Ensure all expected features are present in correct order
    # The model expects features in the order they were trained
    expected_features = [k for k, v in pp_params['per_feature'].items() if v.get('role') == 'INPUT']
    missing = set(expected_features) - set(X.columns)
    if missing:
        print(f'  WARNING: missing features: {missing}')
        for m in missing:
            X[m] = 0
    X = X[expected_features]
    
    # 5. Predict
    if hasattr(clf, 'predict'):
        if hasattr(clf, 'feature_name_'):
            # LightGBM
            X = X[clf.feature_name_]
        p = clf.predict(X.values)
    else:
        print(f'  UNKNOWN MODEL TYPE: {type(clf)}')
        continue
    
    # 6. Reconstruct taxi time: TAXITIME = resid_lobt + (MVT - LOBT)
    mvt_minus_lobt = pd.to_numeric(df.get('mvt_minus_lobt', 0), errors='coerce').fillna(0).values
    taxi_pred = p + mvt_minus_lobt
    taxi_pred = np.clip(taxi_pred, 60, 20000)
    
    ids = pd.to_numeric(df['MVT_ID_mvt'], errors='coerce').astype('int64').values
    out = pd.DataFrame({'MVT_ID_mvt': ids, 'TAXITIME_SEC_mvt': taxi_pred.astype('int32')})
    out.to_csv(f'{W}pred-rank-{SESS}-{apt}.csv', index=False)
    print(f'  n={len(out)} mean={taxi_pred.mean():.1f} min={taxi_pred.min()} max={taxi_pred.max()}')

print('\nDone.')