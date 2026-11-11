import urllib.request, gzip, os, csv, collections, time, json, boto3
B = "amarg-cpa-emr-2026"


def handler(event, context):
    t0 = time.time(); s3 = boto3.client("s3"); out = {}
    api = "https://huggingface.co/api/datasets/criteo/criteo-attribution-dataset"
    meta = json.loads(urllib.request.urlopen(api, timeout=30).read())
    files = [x["rfilename"] for x in meta.get("siblings", [])]
    out["hf_sha"] = meta.get("sha"); out["files"] = files
    base = "https://huggingface.co/datasets/criteo/criteo-attribution-dataset/resolve/main/"
    readmes = {f: urllib.request.urlopen(base + f, timeout=30).read().decode("utf-8", "replace") for f in files if f.lower().endswith(".md")}
    s3.put_object(Bucket=B, Key="criteo-attribution/agg/readmes.json", Body=json.dumps(readmes))
    gzname = [f for f in files if f.endswith(".gz")][0]
    path = "/tmp/data.gz"
    with urllib.request.urlopen(base + gzname, timeout=120) as r, open(path, "wb") as f:
        while True:
            chunk = r.read(1 << 22)
            if not chunk:
                break
            f.write(chunk)
    out["gz"] = gzname; out["gz_bytes"] = os.path.getsize(path)
    camp = collections.defaultdict(lambda: [0, 0, 0, 0.0])
    day = collections.defaultdict(lambda: [0, 0, 0.0])
    conv = {}
    n = 0
    with gzip.open(path, "rt") as g:
        first = g.readline(); dl = "\t" if "\t" in first else ","
        header = next(csv.reader([first], delimiter=dl)); rd = csv.reader(g, delimiter=dl); ix = {h: k for k, h in enumerate(header)}
        ci, co, cl, cv, ts = ix["campaign"], ix["cost"], ix["click"], ix["conversion"], ix["timestamp"]
        for row in rd:
            n += 1
            c = row[ci]; cost = float(row[co]); clk = int(row[cl]); cvn = int(row[cv]); d = int(row[ts]) // 86400
            a = camp[c]; a[0] += 1; a[1] += clk; a[2] += cvn; a[3] += cost
            dd = day[d]; dd[0] += 1; dd[1] += clk; dd[2] += cost
            if cvn:
                cid = row[ix["conversion_id"]]; att = int(row[ix["attribution"]])
                prev = conv.get(cid)
                if prev is None or att > prev[2]:
                    conv[cid] = (c, float(row[ix["cpo"]]), att, int(row[ix["conversion_timestamp"]]) // 86400)
    out["header"] = header; out["rows"] = n
    rev = collections.defaultdict(lambda: [0, 0, 0.0, 0.0])
    rev_day = collections.defaultdict(lambda: [0, 0.0])
    for cid, (c, cpo, att, cd) in conv.items():
        r_ = rev[c]; r_[0] += 1; r_[1] += att; r_[2] += cpo * att; r_[3] += cpo
        if att:
            rd_ = rev_day[cd]; rd_[0] += 1; rd_[1] += cpo
    rows = [{"campaign": c, "impressions": i, "clicks": k, "converting_impressions": v, "cost": cost,
             "conversions": rev[c][0], "attributed_conversions": rev[c][1],
             "attributed_cpo_revenue": rev[c][2], "all_conversions_cpo": rev[c][3]}
            for c, (i, k, v, cost) in camp.items()]
    daily = [{"day": d, "impressions": v[0], "clicks": v[1], "cost": v[2],
              "attributed_conversions": rev_day.get(d, [0, 0.0])[0], "attributed_cpo_revenue": rev_day.get(d, [0, 0.0])[1]}
             for d, v in sorted(day.items())]
    s3.put_object(Bucket=B, Key="criteo-attribution/agg/campaign.json", Body=json.dumps(rows))
    s3.put_object(Bucket=B, Key="criteo-attribution/agg/daily.json", Body=json.dumps(daily))
    out["campaigns"] = len(rows); out["distinct_conversions"] = len(conv); out["seconds"] = round(time.time() - t0, 1)
    s3.put_object(Bucket=B, Key="criteo-attribution/agg/run.json", Body=json.dumps(out))
    return out
