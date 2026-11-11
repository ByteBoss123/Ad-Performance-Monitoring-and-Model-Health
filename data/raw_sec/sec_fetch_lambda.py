import urllib.request, json, boto3
UA = {"User-Agent": "marketing-efficiency-research/1.0 research@example.org"}
TICK = ["APP", "PLTK", "SKLZ", "MYPS", "RBLX", "DDI", "U", "TTWO", "EA"]
EXTRA = {"ZNGA": 1439404, "SCPL": 1760717}
REV = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"]
SM = ["SellingAndMarketingExpense", "MarketingExpense", "SellingGeneralAndAdministrativeExpense"]


def get(u):
    return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read())


def handler(e, c):
    t = get("https://www.sec.gov/files/company_tickers.json")
    ciks = {v["ticker"]: v["cik_str"] for v in t.values() if v["ticker"] in TICK} | EXTRA
    out = {"ciks": ciks, "rows": [], "tags": {}}
    for tk, cik in ciks.items():
        try:
            f = get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
        except Exception as ex:
            out["tags"][tk] = repr(ex); continue
        g = f["facts"].get("us-gaap", {})
        used = {}
        for kind, tags in (("revenue", REV), ("sm", SM)):
            for tag in tags:
                if tag in g and "USD" in g[tag]["units"]:
                    used[kind] = tag; break
        out["tags"][tk] = {"name": f["entityName"], **used}
        if len(used) < 2:
            continue
        def q(tag):
            d = {}
            for x in g[tag]["units"]["USD"]:
                if x.get("frame", "").count("Q") == 1 and "I" not in x["frame"]:
                    d[x["frame"]] = x["val"]
            return d
        r, s = q(used["revenue"]), q(used["sm"])
        for fr in sorted(set(r) & set(s)):
            out["rows"].append([tk, fr, r[fr], s[fr]])
    boto3.client("s3").put_object(Bucket="amarg-cpa-emr-2026", Key="sec-marketing/raw.json", Body=json.dumps(out))
    return {"tags": out["tags"], "n_rows": len(out["rows"]), "rows": out["rows"]}
