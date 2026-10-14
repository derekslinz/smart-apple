"""Upload a submission file to the challenge MinIO bucket.

Credentials are read from /root/.hermes/.env at runtime (never typed into a command line).
Usage: upload.py <local.parquet> <object_name.parquet>
"""
import os, sys
import boto3
from botocore.config import Config

ENV = '/root/.hermes/.env'


def env_vals():
    d = {}
    for line in open(ENV):
        line = line.strip()
        if line.startswith('export '):
            line = line[7:]
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


e = env_vals()
keys = [k for k in e if 'MINIO' in k or 'SUB MISSIO' in k or 'SUBMISSION' in k or 'SUBMISSIO' in k or 'TEAM' in k]
print('env keys available:', sorted(keys))
url = e.get('PRC_MINIO_URL')
ak = e.get('PRC_MINIO_API_ACCESS_KEY')
sk = e.get('PRC_MINIO_API_SECRET_KEY')
bucket = e.get('PRC_SUBMISSIO_BUCKET') or e.get('PRC_SUBMISSION_BUCKET')
local, obj = sys.argv[1], sys.argv[2]
endpoint = url if url.startswith('http') else 'http://' + url
print(f'endpoint={endpoint} bucket={bucket} object={obj} local={local} size={os.path.getsize(local)}')

s3 = boto3.client('s3', endpoint_url=endpoint, aws_access_key_id=ak, aws_secret_access_key=sk,
                  config=Config(signature_version='s3v4'), use_ssl=endpoint.startswith('https'))
s3.upload_file(local, bucket, obj)
info = s3.head_object(Bucket=bucket, Key=obj)
print('uploaded:', bucket, obj, 'bytes', info['ContentLength'], 'etag', info['ETag'])
