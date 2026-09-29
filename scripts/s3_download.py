"""Descarga data/ desde S3 a ./data/raw preservando particiones. Idempotente (salta archivos con mismo tamaño)."""
import os, sys, boto3
from concurrent.futures import ThreadPoolExecutor
for l in open(".env"):
    k, v = l.strip().split("=", 1); os.environ[k] = v
s3 = boto3.client("s3"); B = os.environ["DATA_BUCKET"]
FULL = {"branches", "customers", "products", "service_agents", "marketing_campaigns", "daily_exchange_rates",
        "transactions", "call_center_interactions", "call_transcripts", "satisfaction_surveys", "complaints"}
SAMPLE = {"digital_events", "campaign_sends"}   # solo primeros 30 archivos
keys, seen = [], {}
for page in s3.get_paginator("list_objects_v2").paginate(Bucket=B, Prefix="data/"):
    for o in page.get("Contents", []):
        t = o["Key"].split("/")[1].removesuffix(".csv")
        if t in FULL or (t in SAMPLE and seen.setdefault(t, 0) < 30):
            if t in SAMPLE: seen[t] += 1
            keys.append((o["Key"], o["Size"]))
def get(ks):
    k, size = ks
    dst = os.path.join("data", "raw", k.removeprefix("data/"))
    if os.path.exists(dst) and os.path.getsize(dst) == size: return 0
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    s3.download_file(B, k, dst); return size
with ThreadPoolExecutor(32) as ex:
    total = sum(ex.map(get, keys))
print(f"files={len(keys)} downloaded_MB={total/1e6:.1f}")
