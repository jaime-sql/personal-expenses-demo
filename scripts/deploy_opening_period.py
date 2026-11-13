#!/usr/bin/env python3
"""Dry-run, deploy, or roll back the Auto period selector.

Dashboard only. Does not write silver, start the ETL job, or create a warehouse.

  # Read the live dashboard, run every changed dataset query, do not PATCH.
  DATABRICKS_TOKEN=... python3 scripts/deploy_opening_period.py

  # Same checks, then PATCH and publish.
  DATABRICKS_TOKEN=... python3 scripts/deploy_opening_period.py --apply

  # Restore a backup written by a previous run, then publish.
  DATABRICKS_TOKEN=... python3 scripts/deploy_opening_period.py --rollback out/opening-period-dry-run/<stamp>/dashboard.json

--dashboard-json checks a file and skips the warehouse. --apply is refused
unless DATABRICKS_TOKEN is set and the warehouse checks have passed.
"""
import json, os, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path

from patch_opening_period import OpeningPeriodError, patch_dashboard
from period_sql import LABEL_SQL, PERIOD_ALL, PERIOD_DEFAULT, PERIOD_KEYWORD, YESTERDAY_SQL

HOST = os.environ.get("DATABRICKS_HOST", "https://dbc-6b5953ee-73b5.cloud.databricks.com").rstrip("/")
DASHBOARD_ID = "01f1d247cc6e1ea9bd62f41ab5d742b7"
WAREHOUSE_FALLBACK = "de62669408c45fc9"
SILVER = "workspace.personal_expenses.silver_charges"
HERE = Path(__file__).resolve().parent
BACKUP_ROOT = HERE.parent / "out" / "opening-period-dry-run"


def _token():
    token = os.environ.get("DATABRICKS_TOKEN")
    if not token:
        raise SystemExit("DATABRICKS_TOKEN is not set. This script does not prompt for it.")
    return token


def _api(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        HOST + path, data=data, method=method,
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            payload = resp.read()
            return json.loads(payload.decode()) if payload else {}
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:2000]
        raise SystemExit(f"{method} {path} -> HTTP {err.code}: {detail}") from None


def _sql(statement, warehouse_id, period=None):
    body = {
        "warehouse_id": warehouse_id,
        "catalog": "workspace",
        "schema": "personal_expenses",
        "statement": statement,
        "wait_timeout": "50s",
        "on_wait_timeout": "CONTINUE",
        "disposition": "INLINE",
        "format": "JSON_ARRAY",
    }
    if period is not None:
        body["parameters"] = [{"name": PERIOD_KEYWORD, "value": period, "type": "STRING"}]
    res = _api("POST", "/api/2.0/sql/statements", body)
    sid = res.get("statement_id")
    state = (res.get("status") or {}).get("state")
    deadline = time.time() + 180
    while state in ("PENDING", "RUNNING"):
        if time.time() > deadline:
            raise SystemExit(f"SQL {sid} still {state}")
        time.sleep(2)
        res = _api("GET", f"/api/2.0/sql/statements/{sid}")
        state = (res.get("status") or {}).get("state")
    if state != "SUCCEEDED":
        raise SystemExit(f"SQL {state}: {json.dumps(res)[:2000]}")
    manifest = res.get("manifest") or {}
    columns = [c.get("name") for c in (manifest.get("schema") or {}).get("columns") or []]
    data = (res.get("result") or {}).get("data_array") or []
    return [dict(zip(columns, row)) for row in data]


def _num(value):
    if value is None:
        return 0.0
    return round(float(value), 2)


def _dataset_sql(dataset):
    return "".join(dataset.get("queryLines") or [])


def _load_file(path):
    payload = json.loads(Path(path).read_text())
    if "serialized_dashboard" in payload:
        raw = payload["serialized_dashboard"]
        return payload, json.loads(raw) if isinstance(raw, str) else raw
    return None, payload


def validate_queries(patched, warehouse_id):
    """Run each changed dataset with Auto, All, and one historical month."""
    by_name = {d["name"]: d for d in patched.get("datasets") or []}
    problems = []
    clock = _sql(
        "SELECT CAST(current_timestamp() AS STRING) AS ts, current_timezone() AS session_tz, "
        f"YEAR({YESTERDAY_SQL}) AS y, MONTH({YESTERDAY_SQL}) AS m",
        warehouse_id,
    )[0]
    auto_label = f"{int(clock['y']):04d}-{int(clock['m']):02d}"
    months = _sql(
        "SELECT YEAR(charge_date_sv) AS y, MONTH(charge_date_sv) AS m "
        f"FROM {SILVER} WHERE charge_date_sv IS NOT NULL "
        "GROUP BY YEAR(charge_date_sv), MONTH(charge_date_sv) "
        "ORDER BY y ASC, m ASC",
        warehouse_id,
    )
    older = [
        row for row in months
        if f"{int(row['y']):04d}-{int(row['m']):02d}" != auto_label
    ]
    if not older:
        raise SystemExit(f"silver_charges has no month other than Auto ({auto_label}) to prove a manual period")
    historical = f"{int(older[0]['y']):04d}-{int(older[0]['m']):02d}"
    expectations = {
        PERIOD_DEFAULT: ("auto", auto_label),
        PERIOD_ALL: ("all", "All history"),
        historical: ("historical", historical),
    }
    for period, (kind, label) in expectations.items():
        shown = _sql(LABEL_SQL, warehouse_id, period)
        got = (shown[0].get("period_label") if shown else None)
        if got != label:
            problems.append(f"{kind} label {got!r} != {label!r}")
        for dataset_name, amount_sql in (
            ("ds_all", "ROUND(SUM(amount_usd), 2)"),
            ("ds_consumption", "ROUND(SUM(amount_usd), 2)"),
        ):
            wrapped = f"SELECT {amount_sql} AS usd, COUNT(*) AS n FROM ({_dataset_sql(by_name[dataset_name])}) q"
            got_row = _sql(wrapped, warehouse_id, period)[0]
            if kind == "all" and dataset_name == "ds_all":
                expect = _sql(f"SELECT ROUND(SUM(amount_usd), 2) AS usd, COUNT(*) AS n FROM {SILVER}", warehouse_id)[0]
            elif kind == "all":
                expect = _sql(
                    "SELECT ROUND(SUM(amount_usd), 2) AS usd, COUNT(*) AS n "
                    f"FROM {SILVER} WHERE is_consumption = true",
                    warehouse_id,
                )[0]
            elif kind == "auto":
                cons = "" if dataset_name == "ds_all" else " AND is_consumption = true"
                expect = _sql(
                    "SELECT ROUND(SUM(amount_usd), 2) AS usd, COUNT(*) AS n FROM "
                    f"{SILVER} WHERE YEAR(charge_date_sv) = {int(clock['y'])} "
                    f"AND MONTH(charge_date_sv) = {int(clock['m'])}{cons}",
                    warehouse_id,
                )[0]
            else:
                cons = "" if dataset_name == "ds_all" else " AND is_consumption = true"
                expect = _sql(
                    "SELECT ROUND(SUM(amount_usd), 2) AS usd, COUNT(*) AS n FROM "
                    f"{SILVER} WHERE YEAR(charge_date_sv) = {int(older[0]['y'])} "
                    f"AND MONTH(charge_date_sv) = {int(older[0]['m'])}{cons}",
                    warehouse_id,
                )[0]
            if _num(got_row.get("usd")) != _num(expect.get("usd")) or int(float(got_row.get("n") or 0)) != int(float(expect.get("n") or 0)):
                problems.append(
                    f"{dataset_name} {kind} usd/n {got_row} != silver {expect}"
                )
    if problems:
        raise SystemExit("validation failed:\n- " + "\n- ".join(problems))
    print(f"warehouse checks passed auto={auto_label} historical={historical}", flush=True)


def _publish(warehouse_id):
    _api("POST", f"/api/2.0/lakeview/dashboards/{DASHBOARD_ID}/published", {
        "warehouse_id": warehouse_id,
        "embed_credentials": True,
    })


def main(argv):
    rollback = None
    apply = "--apply" in argv
    json_path = None
    if "--rollback" in argv:
        rollback = argv[argv.index("--rollback") + 1]
    if "--dashboard-json" in argv:
        json_path = argv[argv.index("--dashboard-json") + 1]
    if rollback:
        wrapper, _ = _load_file(rollback)
        if not wrapper or "serialized_dashboard" not in wrapper:
            raise SystemExit("rollback file must be a dashboard GET response")
        live = _api("GET", f"/api/2.0/lakeview/dashboards/{DASHBOARD_ID}")
        warehouse_id = live.get("warehouse_id") or WAREHOUSE_FALLBACK
        _api("PATCH", f"/api/2.0/lakeview/dashboards/{DASHBOARD_ID}", {
            "etag": live["etag"],
            "serialized_dashboard": wrapper["serialized_dashboard"] if isinstance(wrapper["serialized_dashboard"], str) else json.dumps(wrapper["serialized_dashboard"]),
            "warehouse_id": warehouse_id,
        })
        _publish(warehouse_id)
        print(f"rolled back from {rollback}", flush=True)
        return 0
    if json_path:
        _, dashboard = _load_file(json_path)
        patched, report = patch_dashboard(dashboard)
        print(json.dumps(report, indent=2), flush=True)
        print("file check only: warehouse SQL was not run and the dashboard was not modified", flush=True)
        return 0
    live = _api("GET", f"/api/2.0/lakeview/dashboards/{DASHBOARD_ID}")
    raw = live.get("serialized_dashboard")
    if not raw:
        raise SystemExit("dashboard GET did not include serialized_dashboard")
    dashboard = json.loads(raw)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUP_ROOT / stamp
    backup.mkdir(parents=True, exist_ok=True)
    (backup / "dashboard.json").write_text(json.dumps(live))
    print(f"backup {backup / 'dashboard.json'}", flush=True)
    patched, report = patch_dashboard(dashboard)
    (backup / "patch_report.json").write_text(json.dumps(report, indent=2))
    warehouse_id = live.get("warehouse_id") or WAREHOUSE_FALLBACK
    validate_queries(patched, warehouse_id)
    if not apply:
        print("dry-run only: dashboard not modified", flush=True)
        return 0
    updated = _api("PATCH", f"/api/2.0/lakeview/dashboards/{DASHBOARD_ID}", {
        "etag": live["etag"],
        "serialized_dashboard": json.dumps(patched),
        "warehouse_id": warehouse_id,
    })
    _publish(warehouse_id)
    print(f"published etag {updated.get('etag')} rollback file {backup / 'dashboard.json'}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except OpeningPeriodError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
