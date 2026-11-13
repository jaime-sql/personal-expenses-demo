#!/usr/bin/env python3
"""Build and deploy the CONCAPAN 2026 Expenses & Travel Analytics Dashboard."""
import json
import os
import sys
import urllib.error
import urllib.request

HOST = os.environ.get("DATABRICKS_HOST", "https://dbc-6b5953ee-73b5.cloud.databricks.com").rstrip("/")
TOKEN = os.environ["DATABRICKS_TOKEN"]
WAREHOUSE_ID = "de62669408c45fc9"
DASHBOARD_ID = "01f1df80225d108082ecb2b8ace88bd7"

def api(method, path, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{HOST}{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            res_bytes = r.read()
            return r.status, json.loads(res_bytes.decode("utf-8")) if res_bytes else {}
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")

def build_serialized_dashboard():
    return {
        "datasets": [
            {
                "name": "ds_charges",
                "displayName": "CONCAPAN Charges",
                "queryLines": [
                    "SELECT\n",
                    "  charge_date_sv,\n",
                    "  YEAR(charge_date_sv) AS charge_year,\n",
                    "  MONTH(charge_date_sv) AS charge_month,\n",
                    "  amount_usd,\n",
                    "  CASE WHEN is_consumption THEN amount_usd ELSE 0.0 END AS consumption_amount,\n",
                    "  CASE WHEN is_travel_or_event THEN amount_usd ELSE 0.0 END AS event_logistics_usd,\n",
                    "  merchant,\n",
                    "  merchant_norm,\n",
                    "  bank,\n",
                    "  card_last4,\n",
                    "  category,\n",
                    "  movement_type,\n",
                    "  is_consumption,\n",
                    "  is_travel_or_event,\n",
                    "  event_tag\n",
                    "FROM workspace.personal_expenses.concapan_silver_charges\n",
                    "ORDER BY charge_date_sv DESC\n"
                ]
            },
            {
                "name": "ds_event_agg",
                "displayName": "Event Tag Summary",
                "queryLines": [
                    "SELECT\n",
                    "  event_tag,\n",
                    "  ROUND(SUM(amount_usd), 2) AS total_usd,\n",
                    "  COUNT(*) AS total_txns\n",
                    "FROM workspace.personal_expenses.concapan_silver_charges\n",
                    "GROUP BY event_tag\n",
                    "ORDER BY total_usd DESC\n"
                ]
            },
            {
                "name": "ds_category_agg",
                "displayName": "Category Summary",
                "queryLines": [
                    "SELECT\n",
                    "  category,\n",
                    "  ROUND(SUM(amount_usd), 2) AS total_usd,\n",
                    "  COUNT(*) AS total_txns\n",
                    "FROM workspace.personal_expenses.concapan_silver_charges\n",
                    "WHERE is_consumption = true\n",
                    "GROUP BY category\n",
                    "ORDER BY total_usd DESC\n"
                ]
            },
            {
                "name": "ds_monthly_trend",
                "displayName": "Monthly Trend",
                "queryLines": [
                    "SELECT\n",
                    "  DATE_TRUNC('MONTH', charge_date_sv) AS month_date,\n",
                    "  ROUND(SUM(amount_usd), 2) AS total_usd,\n",
                    "  ROUND(SUM(CASE WHEN is_consumption THEN amount_usd ELSE 0 END), 2) AS consumption_usd\n",
                    "FROM workspace.personal_expenses.concapan_silver_charges\n",
                    "GROUP BY 1\n",
                    "ORDER BY month_date ASC\n"
                ]
            },
            {
                "name": "ds_bank_agg",
                "displayName": "Bank Summary",
                "queryLines": [
                    "SELECT\n",
                    "  bank,\n",
                    "  ROUND(SUM(amount_usd), 2) AS total_usd,\n",
                    "  COUNT(*) AS total_txns\n",
                    "FROM workspace.personal_expenses.concapan_silver_charges\n",
                    "GROUP BY bank\n",
                    "ORDER BY total_usd DESC\n"
                ]
            }
        ],
        "pages": [
            {
                "name": "concapan_overview",
                "displayName": "CONCAPAN 2026 Executive Overview",
                "layout": [
                    # Header
                    {
                        "widget": {
                            "name": "header",
                            "multilineTextboxSpec": {
                                "lines": [
                                    "# ⚡ CONCAPAN 2026 — Expenses & Travel Analytics\n",
                                    "\n",
                                    "Panel analítico ejecutivo para la gestión de viáticos, logística de viaje, servicios técnicos y consumos operativos para la convención **CONCAPAN 2026**."
                                ]
                            }
                        },
                        "position": {"x": 0, "y": 0, "width": 12, "height": 3}
                    },
                    # KPI 1: Total Spend
                    {
                        "widget": {
                            "name": "kpi_total_usd",
                            "queries": [{
                                "name": "main_query",
                                "query": {
                                    "datasetName": "ds_charges",
                                    "fields": [{"name": "total_usd", "expression": "SUM(`amount_usd`)"}],
                                    "disaggregated": False
                                }
                            }],
                            "spec": {
                                "version": 2,
                                "widgetType": "counter",
                                "encodings": {
                                    "value": {
                                        "fieldName": "total_usd",
                                        "displayName": "Total Gastos Registrados",
                                        "format": {
                                            "type": "number-currency",
                                            "currencyCode": "USD",
                                            "abbreviation": "compact",
                                            "decimalPlaces": {"type": "max", "places": 2}
                                        }
                                    }
                                }
                            }
                        },
                        "position": {"x": 0, "y": 3, "width": 3, "height": 3}
                    },
                    # KPI 2: Consumption Spend
                    {
                        "widget": {
                            "name": "kpi_consumption_usd",
                            "queries": [{
                                "name": "main_query",
                                "query": {
                                    "datasetName": "ds_charges",
                                    "fields": [{"name": "cons_usd", "expression": "SUM(`consumption_amount`)"}],
                                    "disaggregated": False
                                }
                            }],
                            "spec": {
                                "version": 2,
                                "widgetType": "counter",
                                "encodings": {
                                    "value": {
                                        "fieldName": "cons_usd",
                                        "displayName": "Consumo Operativo (Neto)",
                                        "format": {
                                            "type": "number-currency",
                                            "currencyCode": "USD",
                                            "abbreviation": "compact",
                                            "decimalPlaces": {"type": "max", "places": 2}
                                        }
                                    }
                                }
                            }
                        },
                        "position": {"x": 3, "y": 3, "width": 3, "height": 3}
                    },
                    # KPI 3: Event & Travel Spend
                    {
                        "widget": {
                            "name": "kpi_event_usd",
                            "queries": [{
                                "name": "main_query",
                                "query": {
                                    "datasetName": "ds_charges",
                                    "fields": [{"name": "event_usd", "expression": "SUM(`event_logistics_usd`)"}],
                                    "disaggregated": False
                                }
                            }],
                            "spec": {
                                "version": 2,
                                "widgetType": "counter",
                                "encodings": {
                                    "value": {
                                        "fieldName": "event_usd",
                                        "displayName": "Logística, Viajes & Hoteles",
                                        "format": {
                                            "type": "number-currency",
                                            "currencyCode": "USD",
                                            "abbreviation": "compact",
                                            "decimalPlaces": {"type": "max", "places": 2}
                                        }
                                    }
                                }
                            }
                        },
                        "position": {"x": 6, "y": 3, "width": 3, "height": 3}
                    },
                    # KPI 4: Total Transactions
                    {
                        "widget": {
                            "name": "kpi_total_txns",
                            "queries": [{
                                "name": "main_query",
                                "query": {
                                    "datasetName": "ds_charges",
                                    "fields": [{"name": "total_count", "expression": "COUNT(*)"}],
                                    "disaggregated": False
                                }
                            }],
                            "spec": {
                                "version": 2,
                                "widgetType": "counter",
                                "encodings": {
                                    "value": {
                                        "fieldName": "total_count",
                                        "displayName": "Total Transacciones",
                                        "format": {"type": "number-plain"}
                                    }
                                }
                            }
                        },
                        "position": {"x": 9, "y": 3, "width": 3, "height": 3}
                    },
                    # Chart 1: Event Tag Logistics Breakdown (Bar Horizontal)
                    {
                        "widget": {
                            "name": "chart_event_tag",
                            "queries": [{
                                "name": "main_query",
                                "query": {
                                    "datasetName": "ds_event_agg",
                                    "fields": [
                                        {"name": "event_tag", "expression": "`event_tag`"},
                                        {"name": "total_usd", "expression": "`total_usd`"}
                                    ],
                                    "disaggregated": True
                                }
                            }],
                            "spec": {
                                "version": 3,
                                "widgetType": "bar",
                                "encodings": {
                                    "x": {"fieldName": "total_usd", "displayName": "Total USD", "scale": {"type": "quantitative"}},
                                    "y": {"fieldName": "event_tag", "displayName": "Eje Operativo / Logística", "scale": {"type": "categorical"}}
                                },
                                "frame": {"showTitle": True, "title": "Distribución por Eje Operativo CONCAPAN"}
                            }
                        },
                        "position": {"x": 0, "y": 6, "width": 6, "height": 6}
                    },
                    # Chart 2: Category Breakdown (Bar Horizontal)
                    {
                        "widget": {
                            "name": "chart_category",
                            "queries": [{
                                "name": "main_query",
                                "query": {
                                    "datasetName": "ds_category_agg",
                                    "fields": [
                                        {"name": "category", "expression": "`category`"},
                                        {"name": "total_usd", "expression": "`total_usd`"}
                                    ],
                                    "disaggregated": True
                                }
                            }],
                            "spec": {
                                "version": 3,
                                "widgetType": "bar",
                                "encodings": {
                                    "x": {"fieldName": "total_usd", "displayName": "Total USD", "scale": {"type": "quantitative"}},
                                    "y": {"fieldName": "category", "displayName": "Categoría de Consumo", "scale": {"type": "categorical"}}
                                },
                                "frame": {"showTitle": True, "title": "Consumo por Categoría"}
                            }
                        },
                        "position": {"x": 6, "y": 6, "width": 6, "height": 6}
                    },
                    # Chart 3: Monthly Trend (Line Chart)
                    {
                        "widget": {
                            "name": "chart_monthly_trend",
                            "queries": [{
                                "name": "main_query",
                                "query": {
                                    "datasetName": "ds_monthly_trend",
                                    "fields": [
                                        {"name": "month_date", "expression": "`month_date`"},
                                        {"name": "total_usd", "expression": "`total_usd`"}
                                    ],
                                    "disaggregated": True
                                }
                            }],
                            "spec": {
                                "version": 3,
                                "widgetType": "line",
                                "encodings": {
                                    "x": {"fieldName": "month_date", "displayName": "Mes", "scale": {"type": "temporal"}},
                                    "y": {"fieldName": "total_usd", "displayName": "Total USD", "scale": {"type": "quantitative"}}
                                },
                                "frame": {"showTitle": True, "title": "Tendencia Histórica de Desembolsos (Mensual)"}
                            }
                        },
                        "position": {"x": 0, "y": 12, "width": 8, "height": 6}
                    },
                    # Chart 4: Bank Breakdown (Bar Chart)
                    {
                        "widget": {
                            "name": "chart_bank",
                            "queries": [{
                                "name": "main_query",
                                "query": {
                                    "datasetName": "ds_bank_agg",
                                    "fields": [
                                        {"name": "bank", "expression": "`bank`"},
                                        {"name": "total_usd", "expression": "`total_usd`"}
                                    ],
                                    "disaggregated": True
                                }
                            }],
                            "spec": {
                                "version": 3,
                                "widgetType": "bar",
                                "encodings": {
                                    "x": {"fieldName": "total_usd", "displayName": "Total USD", "scale": {"type": "quantitative"}},
                                    "y": {"fieldName": "bank", "displayName": "Entidad Bancaria", "scale": {"type": "categorical"}}
                                },
                                "frame": {"showTitle": True, "title": "Desembolsos por Banco Emisor"}
                            }
                        },
                        "position": {"x": 8, "y": 12, "width": 4, "height": 6}
                    },
                    # Table: Detail of Purchases
                    {
                        "widget": {
                            "name": "table_charges_detail",
                            "queries": [{
                                "name": "main_query",
                                "query": {
                                    "datasetName": "ds_charges",
                                    "fields": [
                                        {"name": "charge_date_sv", "expression": "`charge_date_sv`"},
                                        {"name": "merchant", "expression": "`merchant`"},
                                        {"name": "event_tag", "expression": "`event_tag`"},
                                        {"name": "category", "expression": "`category`"},
                                        {"name": "bank", "expression": "`bank`"},
                                        {"name": "card_last4", "expression": "`card_last4`"},
                                        {"name": "amount_usd", "expression": "`amount_usd`"}
                                    ],
                                    "disaggregated": True
                                }
                            }],
                            "spec": {
                                "version": 2,
                                "widgetType": "table",
                                "encodings": {
                                    "columns": [
                                        {"fieldName": "charge_date_sv", "displayName": "Fecha (SV)"},
                                        {"fieldName": "merchant", "displayName": "Comercio / Detalle"},
                                        {"fieldName": "event_tag", "displayName": "Eje Operativo"},
                                        {"fieldName": "category", "displayName": "Categoría"},
                                        {"fieldName": "bank", "displayName": "Banco"},
                                        {"fieldName": "card_last4", "displayName": "Tarjeta"},
                                        {
                                            "fieldName": "amount_usd",
                                            "displayName": "Monto (USD)",
                                            "format": {
                                                "type": "number-currency",
                                                "currencyCode": "USD",
                                                "decimalPlaces": {"type": "max", "places": 2}
                                            }
                                        }
                                    ]
                                },
                                "frame": {"showTitle": True, "title": "Auditoría Detallada de Transacciones"}
                            }
                        },
                        "position": {"x": 0, "y": 18, "width": 12, "height": 8}
                    }
                ]
            }
        ]
    }

def main():
    print("Building CONCAPAN dashboard specification...")
    serialized = build_serialized_dashboard()
    
    # 1. Fetch current dashboard etag
    status, cur = api("GET", f"/api/2.0/lakeview/dashboards/{DASHBOARD_ID}")
    if status != 200:
        print(f"Error fetching dashboard: {status} - {cur}")
        sys.exit(1)
    
    etag = cur.get("etag")
    print(f"Current dashboard etag: {etag}")

    # 2. Update dashboard with PATCH
    patch_body = {
        "etag": etag,
        "warehouse_id": WAREHOUSE_ID,
        "serialized_dashboard": json.dumps(serialized)
    }
    status, updated = api("PATCH", f"/api/2.0/lakeview/dashboards/{DASHBOARD_ID}", patch_body)
    if status != 200:
        print(f"Error updating dashboard: {status} - {updated}")
        sys.exit(1)
    print("Dashboard PATCH successful!")

    # 3. Publish dashboard with embed_credentials
    pub_body = {
        "warehouse_id": WAREHOUSE_ID,
        "embed_credentials": True
    }
    status, pub = api("POST", f"/api/2.0/lakeview/dashboards/{DASHBOARD_ID}/published", pub_body)
    if status not in (200, 201):
        print(f"Error publishing dashboard: {status} - {pub}")
        sys.exit(1)
    
    print("Dashboard published successfully!")
    print(f"View live dashboard at:")
    print(f"  Published URL: {HOST}/dashboardsv3/{DASHBOARD_ID}/published")
    print(f"  Edit/Draft URL: {HOST}/sql/dashboardsv3/{DASHBOARD_ID}")

if __name__ == "__main__":
    main()
