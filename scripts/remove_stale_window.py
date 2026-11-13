#!/usr/bin/env python3
"""Remove the fixed window subtitle from the Personal Expenses title.

The published title still says ``Window 2025-10-27 → 2026-10-26``. The period
selector already resolves the month, so that range is stale. This deletes
that exact text from the title widget and checks the rest of the dashboard
is unchanged. It does not edit datasets, SQL, or any other widget.

  python3 scripts/remove_stale_window.py --dashboard-json tests/fixtures/dashboard_schema.json

  DATABRICKS_TOKEN=... python3 scripts/remove_stale_window.py
  DATABRICKS_TOKEN=... python3 scripts/remove_stale_window.py --apply

The last successful publish etag was 86217607. PATCH uses the etag from the
fresh GET. --apply is the only path that writes.
"""
import copy, json, os, sys, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path

HOST = os.environ.get("DATABRICKS_HOST", "https://dbc-6b5953ee-73b5.cloud.databricks.com").rstrip("/")
DASHBOARD_ID = "01f1d247cc6e1ea9bd62f41ab5d742b7"
PUBLISHED_ETAG = "86217607"
STALE_WINDOW = "Window 2025-10-27 → 2026-10-26"
HERE = Path(__file__).resolve().parent
BACKUP_ROOT = HERE.parent / "out" / "remove-stale-window"


class StaleWindowError(Exception):
    pass


def _title_items(dashboard):
    hits = []
    for page in dashboard.get("pages") or []:
        for item in page.get("layout") or []:
            widget = item.get("widget") or {}
            if widget.get("name") == "title" or "multilineTextboxSpec" in widget:
                hits.append((page, item))
    return hits


def remove_stale_window(dashboard):
    """Return a copy whose title no longer contains the fixed window dates."""
    if not isinstance(dashboard, dict):
        raise StaleWindowError("dashboard JSON must be an object")
    hits = _title_items(dashboard)
    if len(hits) != 1:
        raise StaleWindowError(f"expected one title widget, found {len(hits)}")
    patched = copy.deepcopy(dashboard)
    item = _title_items(patched)[0][1]
    lines = (item["widget"].get("multilineTextboxSpec") or {}).get("lines")
    if not isinstance(lines, list) or not lines:
        raise StaleWindowError("title widget has no text lines")
    found = sum(line.count(STALE_WINDOW) for line in lines)
    if found != 1:
        raise StaleWindowError(f"expected the window subtitle once in the title, found {found}")
    item["widget"]["multilineTextboxSpec"]["lines"] = [
        line.replace(STALE_WINDOW, "", 1) for line in lines
    ]
    assert_only_subtitle_removed(dashboard, patched)
    return patched


def assert_only_subtitle_removed(before, after):
    """The serialized dashboard may differ only by deleting the stale subtitle."""
    before_json = json.dumps(before, ensure_ascii=False)
    after_json = json.dumps(after, ensure_ascii=False)
    if before_json.count(STALE_WINDOW) != 1 or STALE_WINDOW in after_json:
        raise StaleWindowError("window subtitle was not removed exactly once")
    if before_json.replace(STALE_WINDOW, "", 1) != after_json:
        raise StaleWindowError("a change other than the window subtitle was made")


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


def _load(path):
    payload = json.loads(Path(path).read_text())
    if "serialized_dashboard" in payload:
        raw = payload["serialized_dashboard"]
        return payload, json.loads(raw) if isinstance(raw, str) else raw
    return None, payload


def _publish(warehouse_id):
    _api("POST", f"/api/2.0/lakeview/dashboards/{DASHBOARD_ID}/published", {
        "warehouse_id": warehouse_id,
        "embed_credentials": True,
    })


def main(argv):
    apply = "--apply" in argv
    json_path = None
    if "--dashboard-json" in argv:
        json_path = argv[argv.index("--dashboard-json") + 1]
    if json_path:
        _, dashboard = _load(json_path)
        patched = remove_stale_window(dashboard)
        print(json.dumps({"removed": STALE_WINDOW, "apply": False}, ensure_ascii=False), flush=True)
        print("file check only: dashboard was not modified", flush=True)
        return 0
    live = _api("GET", f"/api/2.0/lakeview/dashboards/{DASHBOARD_ID}")
    raw = live.get("serialized_dashboard")
    etag = live.get("etag")
    if not raw or not etag:
        raise SystemExit("dashboard GET did not include serialized_dashboard and etag")
    if etag != PUBLISHED_ETAG:
        print(f"note: fetched etag {etag} is not the publish etag {PUBLISHED_ETAG}", flush=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUP_ROOT / stamp
    backup.mkdir(parents=True, exist_ok=True)
    (backup / "dashboard.json").write_text(json.dumps(live))
    print(f"backup {backup / 'dashboard.json'} etag {etag}", flush=True)
    dashboard = json.loads(raw)
    patched = remove_stale_window(dashboard)
    if not apply:
        print("dry-run only: dashboard not modified", flush=True)
        return 0
    warehouse_id = live.get("warehouse_id")
    updated = _api("PATCH", f"/api/2.0/lakeview/dashboards/{DASHBOARD_ID}", {
        "etag": etag,
        "serialized_dashboard": json.dumps(patched),
        "warehouse_id": warehouse_id,
    })
    _publish(warehouse_id)
    print(f"published etag {updated.get('etag')} removed {STALE_WINDOW!r}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except StaleWindowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
