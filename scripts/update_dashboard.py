#!/usr/bin/env python3
"""Historical one-shot. It replaces the entire dashboard definition.

Do not run it. Use deploy_personal_expenses.py, which patches dataset
ds_consumption and widget top_merchants and leaves every other widget alone.
"""
import json, os, urllib.request
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
            b = r.read()
            return r.status, (json.loads(b.decode()) if b else {})
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:3000]

code, cur = api("GET", f"/api/2.0/lakeview/dashboards/{DASH}")
print("GET", code, "etag", cur.get("etag") if isinstance(cur, dict) else cur)

def counter(name, field, label, x, y):
    return {
        "widget": {
            "name": name,
            "queries": [{
                "name": "main",
                "query": {
                    "datasetName": "silver_all",
                    "fields": [{"name": field, "expression": field if field.startswith("SUM") else f"SUM(`amount_usd`)" if "usd" in field else "COUNT(*)"}],
                    "disaggregated": False,
                },
            }],
            "spec": {
                "version": 2,
                "widgetType": "counter",
                "encodings": {"value": {"fieldName": field, "displayName": label}},
            },
        },
        "position": {"x": x, "y": y, "width": 2, "height": 2},
    }

# Build with explicit expressions
serialized = {
    "datasets": [{
        "name": "silver_all",
        "displayName": "All movements",
        "query": (
            "SELECT charge_date_sv, amount_usd, merchant, merchant_norm, bank, card_last4, "
            "category, movement_type, is_consumption "
            "FROM workspace.personal_expenses.silver_charges"
        ),
    }],
    "pages": [{
        "name": "overview",
        "displayName": "Overview",
        "layout": [
            {
                "widget": {
                    "name": "kpi_all_usd",
                    "queries": [{"name": "main", "query": {
                        "datasetName": "silver_all",
                        "fields": [{"name": "total_usd", "expression": "SUM(`amount_usd`)"}],
                        "disaggregated": False,
                    }}],
                    "spec": {"version": 2, "widgetType": "counter",
                             "encodings": {"value": {"fieldName": "total_usd", "displayName": "All movements USD"}}},
                },
                "position": {"x": 0, "y": 0, "width": 2, "height": 2},
            },
            {
                "widget": {
                    "name": "kpi_cons_usd",
                    "queries": [{"name": "main", "query": {
                        "datasetName": "silver_all",
                        "fields": [{"name": "consumption_usd",
                                    "expression": "SUM(CASE WHEN `is_consumption` THEN `amount_usd` ELSE 0 END)"}],
                        "disaggregated": False,
                    }}],
                    "spec": {"version": 2, "widgetType": "counter",
                             "encodings": {"value": {"fieldName": "consumption_usd", "displayName": "Consumption USD"}}},
                },
                "position": {"x": 2, "y": 0, "width": 2, "height": 2},
            },
            {
                "widget": {
                    "name": "kpi_n_all",
                    "queries": [{"name": "main", "query": {
                        "datasetName": "silver_all",
                        "fields": [{"name": "n_all", "expression": "COUNT(*)"}],
                        "disaggregated": False,
                    }}],
                    "spec": {"version": 2, "widgetType": "counter",
                             "encodings": {"value": {"fieldName": "n_all", "displayName": "All movements N"}}},
                },
                "position": {"x": 4, "y": 0, "width": 1, "height": 2},
            },
            {
                "widget": {
                    "name": "kpi_n_cons",
                    "queries": [{"name": "main", "query": {
                        "datasetName": "silver_all",
                        "fields": [{"name": "n_cons",
                                    "expression": "SUM(CASE WHEN `is_consumption` THEN 1 ELSE 0 END)"}],
                        "disaggregated": False,
                    }}],
                    "spec": {"version": 2, "widgetType": "counter",
                             "encodings": {"value": {"fieldName": "n_cons", "displayName": "Consumption N"}}},
                },
                "position": {"x": 5, "y": 0, "width": 1, "height": 2},
            },
            {
                "widget": {
                    "name": "by_movement",
                    "queries": [{"name": "main", "query": {
                        "datasetName": "silver_all",
                        "fields": [
                            {"name": "movement_type", "expression": "`movement_type`"},
                            {"name": "usd", "expression": "SUM(`amount_usd`)"},
                        ],
                        "disaggregated": False,
                    }}],
                    "spec": {"version": 2, "widgetType": "pie",
                             "encodings": {
                                 "angle": {"fieldName": "usd", "displayName": "USD"},
                                 "color": {"fieldName": "movement_type", "displayName": "Type"},
                             }},
                },
                "position": {"x": 0, "y": 2, "width": 2, "height": 4},
            },
            {
                "widget": {
                    "name": "monthly_trend",
                    "queries": [{"name": "main", "query": {
                        "datasetName": "silver_all",
                        "fields": [
                            {"name": "month", "expression": "DATE_TRUNC('MONTH', `charge_date_sv`)"},
                            {"name": "usd", "expression": "SUM(`amount_usd`)"},
                        ],
                        "disaggregated": False,
                    }}],
                    "spec": {"version": 2, "widgetType": "line",
                             "encodings": {
                                 "x": {"fieldName": "month", "scale": {"type": "temporal"}, "displayName": "Month"},
                                 "y": {"fieldName": "usd", "scale": {"type": "quantitative"}, "displayName": "USD"},
                             }},
                },
                "position": {"x": 2, "y": 2, "width": 4, "height": 4},
            },
            {
                "widget": {
                    "name": "by_category",
                    "queries": [{"name": "main", "query": {
                        "datasetName": "silver_all",
                        "fields": [
                            {"name": "category", "expression": "`category`"},
                            {"name": "usd", "expression": "SUM(`amount_usd`)"},
                        ],
                        "filter": "`is_consumption`",
                        "disaggregated": False,
                    }}],
                    "spec": {"version": 2, "widgetType": "bar",
                             "encodings": {
                                 "x": {"fieldName": "usd", "scale": {"type": "quantitative"}, "displayName": "USD"},
                                 "y": {"fieldName": "category", "scale": {"type": "categorical"}, "displayName": "Category"},
                             }},
                },
                "position": {"x": 0, "y": 6, "width": 3, "height": 5},
            },
            {
                "widget": {
                    "name": "by_bank",
                    "queries": [{"name": "main", "query": {
                        "datasetName": "silver_all",
                        "fields": [
                            {"name": "bank", "expression": "`bank`"},
                            {"name": "usd", "expression": "SUM(`amount_usd`)"},
                        ],
                        "disaggregated": False,
                    }}],
                    "spec": {"version": 2, "widgetType": "bar",
                             "encodings": {
                                 "x": {"fieldName": "bank", "scale": {"type": "categorical"}, "displayName": "Bank"},
                                 "y": {"fieldName": "usd", "scale": {"type": "quantitative"}, "displayName": "USD"},
                             }},
                },
                "position": {"x": 3, "y": 6, "width": 3, "height": 5},
            },
            {
                "widget": {
                    "name": "top_merchants",
                    "queries": [{"name": "main", "query": {
                        "datasetName": "silver_all",
                        "fields": [
                            {"name": "merchant_norm", "expression": "`merchant_norm`"},
                            {"name": "category", "expression": "`category`"},
                            {"name": "usd", "expression": "SUM(`amount_usd`)"},
                            {"name": "n", "expression": "COUNT(*)"},
                        ],
                        "filter": "`is_consumption`",
                        "disaggregated": False,
                    }}],
                    "spec": {"version": 1, "widgetType": "table",
                             "encodings": {"columns": [
                                 {"fieldName": "merchant_norm", "displayName": "Merchant"},
                                 {"fieldName": "category", "displayName": "Category"},
                                 {"fieldName": "usd", "displayName": "USD"},
                                 {"fieldName": "n", "displayName": "N"},
                             ]}},
                },
                "position": {"x": 0, "y": 11, "width": 6, "height": 6},
            },
        ],
    }],
}

# Fallback: textbox-only if rich widgets fail
fallback = {
    "pages": [{
        "name": "overview",
        "displayName": "Overview",
        "layout": [{
            "widget": {
                "name": "intro",
                "textbox_spec": {
                    "lines": [{
                        "text": (
                            "Personal Expenses YTD (2025-10-27 → 2026-10-26 SV)\\n"
                            "Source: workspace.personal_expenses.silver_charges\\n"
                            "All movements: 734 / $25,564.60 · Consumption: 731 / $24,819.60\\n"
                            "Filter by movement_type (purchase|transfer|card_payment) or is_consumption.\\n"
                            "SQL queries: personal_expenses__monthly / by_category / by_bank / "
                            "top_merchants / by_movement_type / trend_daily"
                        )
                    }]
                },
            },
            "position": {"x": 0, "y": 0, "width": 6, "height": 3},
        }],
    }]
}

for label, ser in [("rich", serialized), ("fallback", fallback)]:
    code, cur = api("GET", f"/api/2.0/lakeview/dashboards/{DASH}")
    etag = cur.get("etag") if isinstance(cur, dict) else None
    body = {
        "dashboard_id": DASH,
        "display_name": "Personal Expenses YTD",
        "warehouse_id": WH,
        "etag": etag,
        "serialized_dashboard": json.dumps(ser),
    }
    code, res = api("PUT", f"/api/2.0/lakeview/dashboards/{DASH}", body)
    print(label, code, str(res)[:900])
    if code == 200:
        open("/workspace/personal_expenses/out/dashboard.json", "w").write(json.dumps(res, indent=2))
        break

print("URL", f"{HOST}/sql/dashboardsv3/{DASH}")
print("URL2", f"{HOST}/dashboardsv3/{DASH}")
print("QUERY_MONTHLY", f"{HOST}/sql/editor/{q}" if False else f"{HOST}/sql/queries/c4fca739-a2b1-4666-88f6-7b07b56dc090")
