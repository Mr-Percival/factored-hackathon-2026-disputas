import os, boto3
from collections import defaultdict
for l in open(".env"):
    k, v = l.strip().split("=", 1); os.environ[k] = v
s3 = boto3.client("s3")
b = os.environ["DATA_BUCKET"]
agg = defaultdict(lambda: [0, 0, set()])
for page in s3.get_paginator("list_objects_v2").paginate(Bucket=b):
    for o in page.get("Contents", []):
        parts = o["Key"].split("/")
        top = "/".join(parts[:2])
        a = agg[top]; a[0] += 1; a[1] += o["Size"]; a[2].add(os.path.splitext(o["Key"])[1])
        if a[0] <= 2: print("  ex:", o["Key"], o["Size"])
tot = 0
for k, (n, s, ext) in sorted(agg.items()):
    tot += s; print(f"{k:60s} files={n:6d} MB={s/1e6:9.1f} ext={ext}")
print("TOTAL MB", tot/1e6)
