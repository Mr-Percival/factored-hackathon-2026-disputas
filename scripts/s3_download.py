"""Descarga un prefijo del bucket a ./data/<destino> preservando particiones. Idempotente (salta archivos con mismo tamaño).

    python scripts/s3_download.py                                   # data/ -> data/raw
    python scripts/s3_download.py --prefix data_backup_20260831/ --dest data/raw_backup --tables customers,products,transactions,complaints
"""
import argparse, os, boto3
from concurrent.futures import ThreadPoolExecutor
for l in open(".env"):
    k, v = l.strip().split("=", 1); os.environ[k] = v
s3 = boto3.client("s3"); B = os.environ["DATA_BUCKET"]
FULL = {"branches", "customers", "products", "service_agents", "marketing_campaigns", "daily_exchange_rates",
        "transactions", "call_center_interactions", "call_transcripts", "satisfaction_surveys", "complaints"}
SAMPLE = {"digital_events", "campaign_sends"}   # solo primeros 30 archivos
ap = argparse.ArgumentParser()
ap.add_argument("--prefix", default="data/")
ap.add_argument("--dest", default=os.path.join("data", "raw"))
ap.add_argument("--tables", default=None, help="lista separada por comas; por defecto FULL + muestra de SAMPLE")
a = ap.parse_args()
if a.tables:
    FULL, SAMPLE = set(a.tables.split(",")), set()
keys, seen = [], {}
for page in s3.get_paginator("list_objects_v2").paginate(Bucket=B, Prefix=a.prefix):
    for o in page.get("Contents", []):
        t = o["Key"][len(a.prefix):].split("/")[0].removesuffix(".csv")
        if t in FULL or (t in SAMPLE and seen.setdefault(t, 0) < 30):
            if t in SAMPLE: seen[t] += 1
            keys.append((o["Key"], o["Size"]))
def get(ks):
    k, size = ks
    dst = os.path.join(a.dest, k[len(a.prefix):])
    if os.path.exists(dst) and os.path.getsize(dst) == size: return 0
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    s3.download_file(B, k, dst); return size
with ThreadPoolExecutor(32) as ex:
    total = sum(ex.map(get, keys))
print(f"files={len(keys)} downloaded_MB={total/1e6:.1f}")
