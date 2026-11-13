#!/usr/bin/env python3
"""Deploy the Navarra merchant fix and the Gmail source column.

Reads DATABRICKS_TOKEN from the environment. Does not print the token, does not
open a browser, and does not create warehouses, clusters, or other paid resources.

What it changes, after writing local backups:
  1. Workspace notebook used by job 829440227192121 (path taken from the live job).
  2. Lakeview dashboard 01f1d247cc6e1ea9bd62f41ab5d742b7, and only then:
       dataset ds_consumption  — source_email / source_thread_id, date DESC
       widget  top_merchants   — Source email link
     PATCH body is flat: etag, serialized_dashboard, and the live warehouse_id.
  3. Publishes that dashboard with warehouse_id and embed_credentials true.
  4. Triggers the job once, then checks:
       the 2026-11-06 Credicomer 0707 $7.42 row is the coffee shop / restaurants
       rows whose text is the auto workshop stay transport
       row count and USD totals are unchanged
       duplicate charge_id count is zero

Usage (from the repo root, or from scripts/):
  DATABRICKS_TOKEN=... python3 scripts/deploy_personal_expenses.py
  DATABRICKS_TOKEN=... python3 scripts/deploy_personal_expenses.py --dry-run

--dry-run fetches the live dashboard, job, and table schemas, writes backups,
and prints the patch report. It does not import, PATCH, publish, or run the job.

The dashboard is already published. Do not run this script with no flags again.
  --dashboard-only  re-PATCH and publish the dashboard. Does not import or run the job.
  --notebook-only   import the notebook and run job 829440227192121 once.
                    Does not PATCH or publish the dashboard.

After either flag prints "triggered run_id=", do not start another job.
"""
import base64, json, os, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path

from patch_dashboard_source_email import (
    BRONZE_FQN, DATASET, SILVER_FQN, WIDGET,
    DashboardPatchError, patch_serialized_dashboard, validate_source_link_template,
)

HOST = os.environ.get("DATABRICKS_HOST", "https://dbc-6b5953ee-73b5.cloud.databricks.com").rstrip("/")
WAREHOUSE_FALLBACK = "de62669408c45fc9"
DASHBOARD_ID = "01f1d247cc6e1ea9bd62f41ab5d742b7"
JOB_ID = 829440227192121
HERE = Path(__file__).resolve().parent
NOTEBOOK_FILE = HERE / "etl_load_from_volume.py"
PARSER_FILE = HERE / "alert_parser.py"
BACKUP_ROOT = HERE.parent / "out" / "deploy-backups"

REQUIRED_SILVER = {
    "charge_id", "message_id", "merchant", "merchant_norm", "amount_usd",
    "charge_date_sv", "category", "bank", "is_consumption", "card_last4",
}
REQUIRED_BRONZE = {"message_id", "thread_id", "ingested_at"}
# Statement Execution API: wait_timeout is only 0s, or 5s through 50s.
# A longer client-side poll covers warehouse startup; the POST value itself must stay in range.
SQL_WAIT_SECONDS = 50
SQL_POLL_DEADLINE_SECONDS = 180


class DeployError(Exception):
    pass


def _token():
    token = os.environ.get("DATABRICKS_TOKEN")
    if not token:
        raise DeployError(
            "DATABRICKS_TOKEN is not set. Export it in the environment that runs this script. "
            "This process will not prompt for it and will not look in a secrets file."
        )
    return token


def api(method, path, body=None, raw=False):
    token = _token()
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        HOST + path, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            payload = resp.read()
            if raw:
                return resp.status, payload
            if not payload:
                return resp.status, {}
            return resp.status, json.loads(payload.decode())
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:4000]
        raise DeployError(f"{method} {path} -> HTTP {err.code}: {detail}") from None


def statement_wait_timeout(seconds):
    """Return a wait_timeout the SQL Statements API will accept.

    Allowed values are ``0s`` (return immediately) and ``5s``–``50s``.
    ``90s`` is rejected with HTTP 400 before the warehouse runs anything.
    """
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        raise DeployError(f"SQL wait_timeout must be an integer number of seconds, not {seconds!r}")
    if seconds == 0:
        return "0s"
    if seconds < 5 or seconds > 50:
        raise DeployError(
            f"SQL wait_timeout {seconds}s is invalid; the API allows 0s or 5s–50s"
        )
    return f"{seconds}s"


def statement_request(statement, warehouse_id, wait_seconds=SQL_WAIT_SECONDS):
    """Body for POST /api/2.0/sql/statements. Does not send the request."""
    return {
        "warehouse_id": warehouse_id,
        "catalog": "workspace",
        "schema": "personal_expenses",
        "statement": statement,
        "wait_timeout": statement_wait_timeout(wait_seconds),
        "on_wait_timeout": "CONTINUE",
        "disposition": "INLINE",
        "format": "JSON_ARRAY",
    }


def sql(statement, warehouse_id, wait_seconds=SQL_WAIT_SECONDS):
    code, res = api("POST", "/api/2.0/sql/statements", statement_request(statement, warehouse_id, wait_seconds))
    if code != 200:
        raise DeployError(f"SQL submit failed: {res}")
    sid = res.get("statement_id")
    state = (res.get("status") or {}).get("state")
    deadline = time.time() + SQL_POLL_DEADLINE_SECONDS
    while state in ("PENDING", "RUNNING"):
        if time.time() > deadline:
            raise DeployError(f"SQL statement {sid} still {state}")
        time.sleep(2)
        _, res = api("GET", f"/api/2.0/sql/statements/{sid}")
        state = (res.get("status") or {}).get("state")
    if state != "SUCCEEDED":
        raise DeployError(f"SQL {state}: {json.dumps(res)[:2000]}")
    manifest = res.get("manifest") or {}
    chunks = manifest.get("total_chunk_count")
    if isinstance(chunks, int) and chunks > 1:
        raise DeployError(f"SQL result has {chunks} chunks; refusing a partial page")
    columns = [c.get("name") for c in (manifest.get("schema") or {}).get("columns") or []]
    data = (res.get("result") or {}).get("data_array") or []
    return [dict(zip(columns, row)) for row in data]


def describe_columns(table, warehouse_id):
    rows = sql(f"DESCRIBE TABLE {table}", warehouse_id)
    # DESCRIBE returns col_name / data_type, and a blank row before partition info.
    cols = set()
    for row in rows:
        name = (row.get("col_name") or "").strip()
        if not name or name.startswith("#"):
            break
        cols.add(name)
    return cols


def notebook_api_path(path):
    path = (path or "").strip()
    if path.startswith("/Workspace/"):
        path = path[len("/Workspace"):]
    if not path.startswith("/"):
        path = "/" + path
    return path


def assert_parser_embedded():
    etl = NOTEBOOK_FILE.read_text()
    parser = PARSER_FILE.read_text()
    if not parser.endswith("\n"):
        parser += "\n"
    start = etl.index("# --- alert_parser:")
    end = etl.index("# --- end alert_parser ---") + len("# --- end alert_parser ---")
    embedded = etl[start:end] + "\n"
    if embedded != parser:
        raise DeployError("etl_load_from_volume.py parser block does not match alert_parser.py; refusing to upload")


def fetch_notebook_path():
    _, job = api("GET", f"/api/2.1/jobs/get?job_id={JOB_ID}")
    tasks = ((job.get("settings") or {}).get("tasks")) or []
    paths = []
    for task in tasks:
        nb = (task.get("notebook_task") or {}).get("notebook_path")
        if nb:
            paths.append(nb)
    chosen = next((p for p in paths if p.rstrip("/").endswith("etl_load_from_volume")), None)
    if not chosen and len(paths) == 1:
        chosen = paths[0]
    if not chosen:
        raise DeployError(f"job {JOB_ID} has no etl_load_from_volume notebook; paths={paths}")
    return chosen, notebook_api_path(chosen)


def export_notebook(api_path):
    _, res = api("GET", f"/api/2.0/workspace/export?path={urllib.request.quote(api_path)}&format=SOURCE")
    content = res.get("content")
    if not content:
        raise DeployError(f"workspace export returned no content for {api_path}")
    return base64.b64decode(content)


def import_notebook(api_path, raw_bytes):
    api("POST", "/api/2.0/workspace/import", {
        "path": api_path,
        "format": "SOURCE",
        "language": "PYTHON",
        "content": base64.b64encode(raw_bytes).decode("ascii"),
        "overwrite": True,
    })


def totals_sql():
    return f"""
    SELECT
      COUNT(*) AS n_all,
      COUNT(DISTINCT charge_id) AS n_ids,
      ROUND(SUM(amount_usd), 2) AS usd_all,
      ROUND(SUM(CASE WHEN is_consumption THEN amount_usd ELSE 0 END), 2) AS usd_cons,
      SUM(CASE WHEN is_consumption THEN 1 ELSE 0 END) AS n_cons
    FROM {SILVER_FQN}
    """


def _num(value):
    if value is None:
        return None
    return round(float(value), 2)


def _int(value):
    if value is None:
        return None
    return int(float(value))


def snapshot_totals(warehouse_id):
    rows = sql(totals_sql(), warehouse_id)
    if len(rows) != 1:
        raise DeployError(f"totals query returned {len(rows)} rows")
    row = rows[0]
    return {
        "n_all": _int(row.get("n_all")),
        "n_ids": _int(row.get("n_ids")),
        "usd_all": _num(row.get("usd_all")),
        "usd_cons": _num(row.get("usd_cons")),
        "n_cons": _int(row.get("n_cons")),
    }


def coffee_rows(warehouse_id):
    return sql(f"""
    SELECT charge_id, CAST(charge_date_sv AS STRING) AS charge_date_sv,
           amount_usd, bank, card_last4, merchant, merchant_norm, category, movement_type
    FROM {SILVER_FQN}
    WHERE charge_date_sv = DATE '2026-11-06'
      AND bank = 'Credicomer'
      AND card_last4 = '0707'
      AND ABS(amount_usd - 7.42) < 0.001
    """, warehouse_id)


def validate_data(before, warehouse_id):
    after = snapshot_totals(warehouse_id)
    problems = []
    for key in ("n_all", "n_ids", "usd_all", "usd_cons", "n_cons"):
        if before.get(key) != after.get(key):
            problems.append(f"{key} changed from {before.get(key)} to {after.get(key)}")
    if after["n_all"] != after["n_ids"]:
        problems.append(f"duplicate charge_id rows: n_all={after['n_all']} n_ids={after['n_ids']}")
    rows = coffee_rows(warehouse_id)
    if len(rows) != 1:
        problems.append(f"expected one Credicomer 0707 $7.42 row on 2026-11-06, found {len(rows)}: {rows}")
    else:
        row = rows[0]
        merchant = (row.get("merchant") or "").upper()
        norm = (row.get("merchant_norm") or "").upper()
        if "COFF" not in merchant or "CUP" not in merchant:
            problems.append(f"merchant is not the coffee shop: {row.get('merchant')!r}")
        if norm == "AUTO TALLER NAVARRA" or "AUTO TALLER" in norm:
            problems.append(f"merchant_norm still collapsed: {row.get('merchant_norm')!r}")
        if (row.get("category") or "") != "restaurants":
            problems.append(f"category is {row.get('category')!r}, expected restaurants")
    bad_coffee = sql(f"""
    SELECT COUNT(*) AS n
    FROM {SILVER_FQN}
    WHERE upper(merchant) RLIKE 'COFFEE?[ ]+CUP'
      AND (category <> 'restaurants' OR merchant_norm = 'AUTO TALLER NAVARRA')
    """, warehouse_id)
    if _int(bad_coffee[0].get("n")) != 0:
        problems.append(f"coffee-cup rows still mislabeled: {bad_coffee}")
    bad_workshop = sql(f"""
    SELECT COUNT(*) AS n
    FROM {SILVER_FQN}
    WHERE upper(merchant) LIKE '%AUTO TALLER%'
      AND upper(merchant) LIKE '%NAVARRA%'
      AND upper(merchant) NOT LIKE '%COFF%'
      AND (category <> 'transport' OR merchant_norm <> 'AUTO TALLER NAVARRA')
    """, warehouse_id)
    if _int(bad_workshop[0].get("n")) != 0:
        problems.append(f"auto workshop rows changed category or norm: {bad_workshop}")
    if problems:
        raise DeployError("validation failed:\n- " + "\n- ".join(problems) + f"\nafter={after}")
    return after, rows[0]


def trigger_job_once():
    _, res = api("POST", "/api/2.1/jobs/run-now", {"job_id": JOB_ID})
    run_id = res.get("run_id")
    if not run_id:
        raise DeployError(f"run-now returned no run_id: {res}")
    print(f"triggered run_id={run_id}", flush=True)
    deadline = time.time() + 25 * 60
    state = {}
    while time.time() < deadline:
        _, run = api("GET", f"/api/2.1/jobs/runs/get?run_id={run_id}")
        state = run.get("state") or {}
        life = state.get("life_cycle_state")
        if life in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
            if state.get("result_state") != "SUCCESS":
                raise DeployError(f"job run {run_id} finished {state}")
            return run_id
        time.sleep(15)
    raise DeployError(f"job run {run_id} did not finish: {state}")


def main(argv):
    dry = "--dry-run" in argv
    notebook_only = "--notebook-only" in argv
    dashboard_only = "--dashboard-only" in argv
    if notebook_only and dashboard_only:
        raise DeployError("pass only one of --notebook-only or --dashboard-only")
    _token()
    assert_parser_embedded()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUP_ROOT / stamp
    backup.mkdir(parents=True, exist_ok=True)

    _, dashboard = api("GET", f"/api/2.0/lakeview/dashboards/{DASHBOARD_ID}")
    (backup / "dashboard.json").write_text(json.dumps(dashboard))
    etag = dashboard.get("etag")
    if not etag or "serialized_dashboard" not in dashboard:
        raise DeployError("dashboard GET did not include etag and serialized_dashboard")
    warehouse_id = dashboard.get("warehouse_id") or WAREHOUSE_FALLBACK
    live_path, api_path = fetch_notebook_path()
    (backup / "notebook.py").write_bytes(export_notebook(api_path))
    print(f"backup {backup}", flush=True)
    print(f"live notebook {live_path} warehouse {warehouse_id} etag {etag}", flush=True)

    silver_cols = describe_columns(SILVER_FQN, warehouse_id)
    bronze_cols = describe_columns(BRONZE_FQN, warehouse_id)
    (backup / "schema.json").write_text(json.dumps({
        "silver": sorted(silver_cols), "bronze": sorted(bronze_cols),
    }, indent=2))
    missing_s = REQUIRED_SILVER - silver_cols
    missing_b = REQUIRED_BRONZE - bronze_cols
    if missing_s or missing_b:
        raise DeployError(f"schema missing silver={sorted(missing_s)} bronze={sorted(missing_b)}")

    before = snapshot_totals(warehouse_id)
    (backup / "totals_before.json").write_text(json.dumps(before, indent=2))
    print(f"totals before {before}", flush=True)

    serialized = json.loads(dashboard["serialized_dashboard"])
    patched, report = patch_serialized_dashboard(serialized, SILVER_FQN, BRONZE_FQN)
    validate_source_link_template(report["link_template"])
    (backup / "patch_report.json").write_text(json.dumps(report, indent=2))
    (backup / "dashboard_patched.json").write_text(json.dumps(patched))
    print("patch report " + json.dumps(report), flush=True)
    if dry:
        print("dry-run: no import, PATCH, publish, or job", flush=True)
        return 0

    if not dashboard_only:
        import_notebook(api_path, NOTEBOOK_FILE.read_bytes())
        print(f"imported notebook {api_path}", flush=True)
    if notebook_only:
        run_id = trigger_job_once()
        (backup / "run_id.txt").write_text(str(run_id))
        after, coffee = validate_data(before, warehouse_id)
        (backup / "totals_after.json").write_text(json.dumps({"totals": after, "coffee": coffee}, indent=2, default=str))
        print(f"validated totals {after}", flush=True)
        print(
            "validated coffee "
            f"merchant={coffee.get('merchant')!r} norm={coffee.get('merchant_norm')!r} "
            f"category={coffee.get('category')!r} charge_id={coffee.get('charge_id')}",
            flush=True,
        )
        print(f"job run {run_id} succeeded", flush=True)
        return 0

    code, updated = api("PATCH", f"/api/2.0/lakeview/dashboards/{DASHBOARD_ID}", {
        "etag": etag,
        "serialized_dashboard": json.dumps(patched),
        "warehouse_id": warehouse_id,
    })
    if code != 200:
        raise DeployError(f"dashboard PATCH failed: {updated}")
    print(f"patched dashboard etag {updated.get('etag')}", flush=True)
    api("POST", f"/api/2.0/lakeview/dashboards/{DASHBOARD_ID}/published", {
        "warehouse_id": warehouse_id,
        "embed_credentials": True,
    })
    print(f"published {HOST}/dashboardsv3/{DASHBOARD_ID}/published", flush=True)

    _, check = api("GET", f"/api/2.0/lakeview/dashboards/{DASHBOARD_ID}")
    body = check.get("serialized_dashboard") or ""
    if "source_email_url" not in body or "#all/{{source_thread_id}}" in body:
        raise DeployError("published draft still has a prefixed Gmail link or is missing source_email_url")
    if dashboard_only:
        print("dashboard republished; job was not started", flush=True)
        return 0

    run_id = trigger_job_once()
    (backup / "run_id.txt").write_text(str(run_id))
    after, coffee = validate_data(before, warehouse_id)
    (backup / "totals_after.json").write_text(json.dumps({"totals": after, "coffee": coffee}, indent=2, default=str))
    print(f"validated totals {after}", flush=True)
    print(
        "validated coffee "
        f"merchant={coffee.get('merchant')!r} norm={coffee.get('merchant_norm')!r} "
        f"category={coffee.get('category')!r} charge_id={coffee.get('charge_id')}",
        flush=True,
    )
    print(f"job run {run_id} succeeded", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (DeployError, DashboardPatchError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
