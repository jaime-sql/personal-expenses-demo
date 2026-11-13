#!/usr/bin/env python3
"""Fix Lakeview widgets: query name must be main_query (not main). Uses PATCH + publish."""
import json, os, urllib.request, urllib.error
HOST = os.environ["DATABRICKS_HOST"].rstrip("/")
TOKEN = os.environ["DATABRICKS_TOKEN"]
WH = "de62669408c45fc9"
DASH = "01f1d247cc6e1ea9bd62f41ab5d742b7"

def api(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        HOST + path, data=data, method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            b = r.read(); return r.status, (json.loads(b.decode()) if b else {})
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:5000]

code, cur = api("GET", f"/api/2.0/lakeview/dashboards/{DASH}")
assert code == 200, cur
sd = json.loads(cur["serialized_dashboard"])
changed = 0
for p in sd.get("pages", []):
    for item in p.get("layout", []):
        for qq in item.get("widget", {}).get("queries") or []:
            if qq.get("name") != "main_query":
                qq["name"] = "main_query"; changed += 1
# also ensure table/pie versions
for p in sd.get("pages", []):
    for item in p.get("layout", []):
        spec = item.get("widget", {}).get("spec") or {}
        wt = spec.get("widgetType")
        if wt == "table" and spec.get("version") != 2:
            spec["version"] = 2; changed += 1
        if wt == "pie" and spec.get("version") != 3:
            spec["version"] = 3; changed += 1
print("renames/fixes", changed)
body = {
    "dashboard_id": DASH,
    "display_name": cur.get("display_name", "Personal Expenses YTD"),
    "warehouse_id": WH,
    "etag": cur["etag"],
    "serialized_dashboard": json.dumps(sd),
}
code, res = api("PATCH", f"/api/2.0/lakeview/dashboards/{DASH}", body)
print("PATCH", code)
assert code == 200, res
code, pub = api("POST", f"/api/2.0/lakeview/dashboards/{DASH}/published",
                {"warehouse_id": WH, "embed_credentials": True})
print("PUBLISH", code, pub if isinstance(pub, dict) else pub)
print("URL", f"{HOST}/dashboardsv3/{DASH}/published")
