"""Download GarmageSet via HF S3 with proxy support."""
import boto3, os, sys, time
from botocore.config import Config
from pathlib import Path

AWS_KEY = "HFAK4ppyQcyNuvaDtj4diuSHtiX5WUz"
AWS_SECRET = "44f5e1997f66fdf5ff7da6ac9d1a230c0016e2bd6946b4957765be266dc87860"
PROXY = "http://127.0.0.1:7897"

os.environ['AWS_ACCESS_KEY_ID'] = AWS_KEY
os.environ['AWS_SECRET_ACCESS_KEY'] = AWS_SECRET
os.environ['HTTP_PROXY'] = PROXY
os.environ['HTTPS_PROXY'] = PROXY

s3 = boto3.client('s3',
    endpoint_url='https://s3.hf.co',
    config=Config(
        signature_version='s3v4',
        s3={'addressing_style': 'virtual'},
        proxies={'http': PROXY, 'https': PROXY},
        connect_timeout=30,
        read_timeout=120,
        retries={'max_attempts': 3},
    ),
    region_name='auto'
)

DOWNLOAD_DIR = Path("D:/ClothesNetData/garmageset_download")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

def list_prefix(prefix):
    """List objects under a prefix."""
    all_keys = []
    paginator = s3.get_paginator('list_objects_v2')
    try:
        for page in paginator.paginate(Bucket='datasets', Prefix=prefix, MaxKeys=100):
            for obj in page.get('Contents', []):
                all_keys.append(obj)
    except Exception as e:
        print(f"List error: {e}")
    return all_keys

def download_file(key, local_path, size):
    """Download a single file with progress."""
    if local_path.exists() and local_path.stat().st_size > 10000:
        sz = local_path.stat().st_size / 1024 / 1024
        if abs(sz - size/1024/1024) < 0.01:  # already complete
            print(f"  [{key.split('/')[-1]}] SKIP (already {sz:.0f}MB)")
            return True

    print(f"  [{key.split('/')[-1]}] Downloading {size/1024/1024:.0f}MB...")
    try:
        s3.download_file('datasets', key, str(local_path))
        sz = local_path.stat().st_size / 1024 / 1024
        print(f"  [{key.split('/')[-1]}] DONE {sz:.0f}MB")
        return True
    except Exception as e:
        print(f"  [{key.split('/')[-1]}] FAILED: {e}")
        return False

if __name__ == "__main__":
    prefix = sys.argv[1] if len(sys.argv) > 1 else "Style3D/GarmageSet"
    print(f"Listing s3://datasets/{prefix} ...")

    objects = list_prefix(prefix)
    print(f"Found {len(objects)} objects")

    if not objects:
        # Try listing just the prefix
        objects = list_prefix(prefix + "/")
        print(f"Found {len(objects)} objects with trailing /")

    if not objects:
        print("Trying common prefixes...")
        resp = s3.list_objects_v2(Bucket='datasets', Prefix='', Delimiter='/', MaxKeys=50)
        for p in resp.get('CommonPrefixes', []):
            print(f"  {p['Prefix']}")
        sys.exit(1)

    # Filter for raw shards
    raw_objects = [o for o in objects if 'raw/' in o['Key'] and o['Key'].endswith('.tar.gz')]
    print(f"Raw shards: {len(raw_objects)}")

    for obj in raw_objects[:5]:  # Test with 5 first
        key = obj['Key']
        fname = key.replace('/', '_')
        download_file(key, DOWNLOAD_DIR / fname, obj['Size'])

    print(f"\nDone. Files in {DOWNLOAD_DIR}:")
    for f in sorted(DOWNLOAD_DIR.glob("*.tar.gz")):
        print(f"  {f.name}: {f.stat().st_size/1024/1024:.0f}MB")
