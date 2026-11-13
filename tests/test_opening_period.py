"""Auto period: El Salvador calendar boundaries, and the dashboard SQL those boundaries run."""
import copy, sys, unittest
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import duckdb  # noqa: E402

from opening_period import opening_period  # noqa: E402
from patch_opening_period import (  # noqa: E402
    patch_dashboard, patch_is_idempotent, validate_dashboard_schema,
)
from period_sql import (  # noqa: E402
    LABEL_SQL, PERIOD_MARKER, PERIOD_PARAMETER, YESTERDAY_SQL, duckdb_sql,
    period_label, quote_period, sql_for_engine,
)

UTC = timezone.utc


def at(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _filter(name, field, title, x, y, width, height, kind="filter-single-select"):
    return {
        "widget": {
            "name": name,
            "queries": [{
                "name": f"q_{name}",
                "query": {
                    "datasetName": "ds_all",
                    "fields": [{"name": field, "expression": f"`{field}`"}],
                    "disaggregated": False,
                },
            }],
            "spec": {
                "version": 2,
                "widgetType": kind,
                "encodings": {"fields": [{"fieldName": field, "displayName": title, "queryName": f"q_{name}"}]},
                "frame": {"showTitle": True, "title": title},
            },
        },
        "position": {"x": x, "y": y, "width": width, "height": height},
    }


def fixture():
    return {
        "datasets": [
            {
                "name": "ds_all",
                "displayName": "All movements",
                "queryLines": [
                    "SELECT charge_date_sv, YEAR(charge_date_sv) AS charge_year, "
                    "MONTH(charge_date_sv) AS charge_month, DAY(charge_date_sv) AS charge_day, "
                    "amount_usd, "
                    "CASE WHEN is_consumption THEN amount_usd ELSE CAST(0 AS DOUBLE) END AS consumption_amount, "
                    "merchant, bank, category, movement_type, is_consumption\n"
                    "FROM workspace.personal_expenses.silver_charges\n",
                ],
            },
            {
                "name": "ds_consumption",
                "displayName": "Consumption only",
                "queryLines": [
                    "-- personal_expenses_source_email\n",
                    "SELECT base.*, CAST(NULL AS STRING) AS source_email_url\n",
                    "FROM (\n",
                    "SELECT charge_id, message_id, charge_date_sv, "
                    "YEAR(charge_date_sv) AS charge_year, MONTH(charge_date_sv) AS charge_month, "
                    "DAY(charge_date_sv) AS charge_day, amount_usd, merchant, bank, category, "
                    "movement_type, is_consumption\n",
                    "FROM workspace.personal_expenses.silver_charges\n",
                    "WHERE is_consumption = true\n",
                    ") base\n",
                    "ORDER BY base.charge_date_sv DESC\n",
                ],
            },
        ],
        "pages": [
            {
                "name": "global_filters",
                "displayName": "Filters",
                "pageType": "PAGE_TYPE_GLOBAL_FILTERS",
                "layout": [
                    _filter("flt_year", "charge_year", "Year", 0, 0, 4, 2),
                    _filter("flt_month", "charge_month", "Month (1-12)", 4, 0, 4, 2),
                    _filter("flt_day", "charge_day", "Day (1-31)", 8, 0, 4, 2),
                    _filter("flt_movement_type", "movement_type", "Movement type", 0, 2, 6, 2, "filter-multi-select"),
                ],
            },
            {
                "name": "overview",
                "displayName": "Overview",
                "pageType": "PAGE_TYPE_CANVAS",
                "layout": [
                    {
                        "widget": {
                            "name": "title",
                            "multilineTextboxSpec": {"lines": ["Filters: Year / Month / Day + movement_type.\n"]},
                        },
                        "position": {"x": 0, "y": 0, "width": 12, "height": 2},
                    },
                    {
                        "widget": {
                            "name": "kpi_all_usd",
                            "queries": [{
                                "name": "main_query",
                                "query": {
                                    "datasetName": "ds_all",
                                    "fields": [{"name": "sum(amount_usd)", "expression": "SUM(`amount_usd`)"}],
                                    "disaggregated": False,
                                },
                            }],
                            "spec": {"version": 2, "widgetType": "counter"},
                        },
                        "position": {"x": 0, "y": 2, "width": 3, "height": 3},
                    },
                    {
                        "widget": {
                            "name": "top_merchants",
                            "queries": [{
                                "name": "main_query",
                                "query": {
                                    "datasetName": "ds_consumption",
                                    "fields": [
                                        {"name": "merchant_norm", "expression": "`merchant`"},
                                        {"name": "source_email", "expression": "MIN(`source_email_url`)"},
                                    ],
                                    "disaggregated": False,
                                    "orders": [{"direction": "DESC", "expression": "`charge_date_sv`"}],
                                },
                            }],
                            "spec": {
                                "version": 2,
                                "widgetType": "table",
                                "encodings": {"columns": [
                                    {"fieldName": "source_email", "displayName": "Source email", "link": {"templatedURL": "{{@}}"}},
                                ]},
                            },
                        },
                        "position": {"x": 0, "y": 18, "width": 12, "height": 8},
                    },
                ],
            },
        ],
    }


def _widget(dashboard, name):
    for page in dashboard["pages"]:
        for item in page["layout"]:
            if item["widget"]["name"] == name:
                return item
    return None


def _run(sql, period, now, rows):
    bound = duckdb_sql(sql_for_engine(sql, period, now))
    bound = bound.replace("workspace.personal_expenses.silver_charges", "silver_charges")
    bound = bound.replace("workspace.personal_expenses.bronze_mail_alerts", "bronze_mail_alerts")
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE silver_charges (charge_id VARCHAR, message_id VARCHAR, charge_date_sv DATE, "
        "amount_usd DOUBLE, merchant VARCHAR, bank VARCHAR, category VARCHAR, movement_type VARCHAR, "
        "is_consumption BOOLEAN)"
    )
    con.executemany("INSERT INTO silver_charges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.execute("CREATE TABLE bronze_mail_alerts (message_id VARCHAR, thread_id VARCHAR, ingested_at TIMESTAMP)")
    return con.execute(bound).fetchall(), [d[0] for d in con.description]


class PeriodTests(unittest.TestCase):
    def test_boundaries(self):
        cases = {
            at(2026, 11, 7, 23, 20): (2026, 11),   # ordinary yesterday Nov 6
            at(2026, 11, 2, 6, 30): (2026, 11),    # the 2nd stays in November
            at(2026, 11, 1, 6, 30): (2026, 10),    # the 1st selects October
            at(2026, 1, 1, 6, 30): (2025, 12),     # Jan 1 selects previous December
            at(2026, 1, 2, 6, 30): (2026, 1),      # Jan 2 stays in January
            at(2026, 12, 1, 6, 30): (2026, 11),    # Dec 1 selects November
            at(2026, 12, 2, 6, 30): (2026, 12),    # Dec 2 stays in December
            at(2024, 3, 1, 6, 30): (2024, 2),      # leap day is yesterday
            at(2025, 3, 1, 6, 30): (2025, 2),      # non-leap Feb 28 is yesterday
            at(2024, 3, 2, 6, 30): (2024, 3),      # March 2 stays in March
            at(2026, 11, 1, 0, 30): (2026, 10),    # UTC already November, SV still October
        }
        for now, expected in cases.items():
            self.assertEqual(opening_period(now), expected, now.isoformat())

    def test_sql_matches_the_python_period(self):
        rows = [
            ("a", "m1", "2025-12-15", 10.0, "A", "BI", "other", "purchase", True),
            ("b", "m2", "2026-01-01", 3.0, "B", "BI", "other", "purchase", True),
            ("c", "m3", "2026-02-28", 4.0, "C", "Promerica", "fuel", "purchase", True),
            ("e", "m5", "2026-11-06", 7.0, "E", "Credicomer", "restaurants", "purchase", True),
            ("f", "m6", "2024-02-29", 8.0, "F", "BI", "other", "purchase", True),
        ]
        dash, _ = patch_dashboard(fixture())
        sql = "".join(next(d["queryLines"] for d in dash["datasets"] if d["name"] == "ds_all"))
        self.assertIn(YESTERDAY_SQL, sql)
        for now, (year, month) in (
            (at(2026, 1, 1, 6, 30), (2025, 12)),
            (at(2026, 1, 2, 6, 30), (2026, 1)),
            (at(2026, 12, 1, 6, 30), (2026, 11)),
            (at(2026, 12, 2, 6, 30), (2026, 12)),
            (at(2024, 3, 1, 6, 30), (2024, 2)),
            (at(2025, 3, 1, 6, 30), (2025, 2)),
            (at(2026, 11, 1, 0, 30), (2026, 10)),
            (at(2026, 11, 1, 6, 0), (2026, 10)),
        ):
            got, _ = _run(f"SELECT YEAR({YESTERDAY_SQL}) AS y, MONTH({YESTERDAY_SQL}) AS m", "All", now, rows)
            self.assertEqual(got, [(year, month)], now.isoformat())
            filtered, _ = _run(sql, "Auto", now, rows)
            expected_usd = round(sum(r[3] for r in rows if r[2].startswith(f"{year:04d}-{month:02d}")), 2)
            self.assertEqual(round(sum(r[4] for r in filtered), 2), expected_usd, now.isoformat())
            label_rows, _ = _run(LABEL_SQL, "Auto", now, rows)
            self.assertEqual(label_rows, [(period_label("Auto", year, month),)])

    def test_all_and_historical_totals_and_labels(self):
        rows = [
            ("a", "m1", "2024-02-29", 8.0, "F", "BI", "other", "purchase", True),
            ("b", "m2", "2025-12-31", 10.0, "A", "BI", "other", "transfer", False),
            ("c", "m3", "2026-11-06", 7.0, "E", "Credicomer", "restaurants", "purchase", True),
        ]
        dash, _ = patch_dashboard(fixture())
        all_sql = "".join(next(d["queryLines"] for d in dash["datasets"] if d["name"] == "ds_all"))
        cons_sql = "".join(next(d["queryLines"] for d in dash["datasets"] if d["name"] == "ds_consumption"))
        now = at(2026, 11, 7, 23, 20)
        everyone, _ = _run(all_sql, "All", now, rows)
        self.assertEqual(round(sum(r[4] for r in everyone), 2), 25.0)
        history, _ = _run(all_sql, "2024-02", now, rows)
        self.assertEqual([r[0].isoformat() for r in history], ["2024-02-29"])
        self.assertEqual(round(sum(r[4] for r in history), 2), 8.0)
        cons, _ = _run(cons_sql, "All", now, rows)
        self.assertEqual(sorted(r[2].isoformat() for r in cons), ["2024-02-29", "2026-11-06"])
        self.assertIn("ORDER BY base.charge_date_sv DESC", cons_sql)
        self.assertIn("source_email_url", cons_sql)
        label, _ = _run(LABEL_SQL, "All", now, rows)
        self.assertEqual(label, [("All history",)])
        label, _ = _run(LABEL_SQL, "2025-12", now, rows)
        self.assertEqual(label, [("2025-12",)])

    def test_dashboard_keeps_day_movement_kpis_and_source_link(self):
        original = fixture()
        day = copy.deepcopy(_widget(original, "flt_day"))
        movement = copy.deepcopy(_widget(original, "flt_movement_type"))
        kpi = copy.deepcopy(_widget(original, "kpi_all_usd"))
        merchants = copy.deepcopy(_widget(original, "top_merchants"))
        patched, report = patch_dashboard(original)
        self.assertTrue(patch_is_idempotent(original))
        self.assertIsNone(_widget(patched, "flt_year"))
        self.assertIsNone(_widget(patched, "flt_month"))
        self.assertEqual(_widget(patched, "flt_day"), day)
        self.assertEqual(_widget(patched, "flt_movement_type"), movement)
        self.assertEqual(_widget(patched, "kpi_all_usd")["widget"], kpi["widget"])
        self.assertEqual(_widget(patched, "kpi_all_usd")["position"]["y"], kpi["position"]["y"] + 2)
        self.assertEqual(_widget(patched, "top_merchants")["widget"], merchants["widget"])
        self.assertEqual(_widget(patched, "top_merchants")["position"]["y"], merchants["position"]["y"] + 2)
        self.assertEqual(report["period_default"], "Auto")
        period = _widget(patched, "flt_period")
        self.assertEqual(period["widget"]["spec"]["widgetType"], "filter-single-select")
        self.assertNotIn("disallowAll", period["widget"]["spec"])
        self.assertEqual(
            period["widget"]["spec"]["selection"]["defaultSelection"]["values"]["values"][0]["value"],
            "Auto",
        )
        for query in period["widget"]["queries"]:
            for binding in (query["query"].get("parameters") or []):
                self.assertEqual(binding, {"name": "period", "keyword": "period"})
        label = _widget(patched, "period_label")
        self.assertEqual(label["widget"]["spec"]["widgetType"], "table")
        self.assertEqual(label["position"], {"x": 0, "y": 0, "width": 12, "height": 2})
        self.assertNotIn("parameters", label["widget"]["queries"][0]["query"])
        self.assertEqual(_widget(patched, "title")["position"]["y"], 2)
        self.assertEqual(_widget(patched, "kpi_all_usd")["position"]["y"], 4)
        self.assertEqual(_widget(patched, "title")["widget"]["multilineTextboxSpec"]["lines"], ["Filters: Period / Day + movement_type.\n"])
        cons = "".join(next(d["queryLines"] for d in patched["datasets"] if d["name"] == "ds_consumption"))
        self.assertEqual(cons.count(PERIOD_MARKER), 1)
        self.assertIn("WHERE is_consumption = true", cons)
        choices = "".join(next(d["queryLines"] for d in patched["datasets"] if d["name"] == "ds_period_choices"))
        self.assertIn("'Auto'", choices)
        self.assertIn("'All'", choices)
        self.assertNotIn(":period", choices)


def _widget(dashboard, name):
    for page in dashboard["pages"]:
        for item in page["layout"]:
            if item["widget"]["name"] == name:
                return item
    return None


def _page(dashboard, name):
    return next(page for page in dashboard["pages"] if page["name"] == name)


class RealSchemaTests(unittest.TestCase):
    def test_live_dashboard_shape(self):
        dashboard = json.loads((ROOT / "tests" / "fixtures" / "dashboard_schema.json").read_text())
        validate_dashboard_schema(dashboard)
        day = copy.deepcopy(_widget(dashboard, "flt_day"))
        movement = copy.deepcopy(_widget(dashboard, "flt_movement_type"))
        merchants = copy.deepcopy(_widget(dashboard, "top_merchants"))
        before = {item["widget"]["name"]: dict(item["position"]) for item in _page(dashboard, "overview")["layout"]}
        patched, _ = patch_dashboard(dashboard)
        self.assertTrue(patch_is_idempotent(dashboard))
        filters = _page(patched, "global_filters")
        kinds = [item["widget"]["spec"]["widgetType"] for item in filters["layout"]]
        self.assertTrue(all(kind.startswith("filter-") for kind in kinds), kinds)
        self.assertIsNone(_widget(patched, "flt_year"))
        self.assertEqual(_widget(patched, "flt_day"), day)
        self.assertEqual(_widget(patched, "flt_movement_type"), movement)
        self.assertEqual(_widget(patched, "flt_period")["position"], {"x": 0, "y": 0, "width": 4, "height": 2})
        label = _widget(patched, "period_label")
        self.assertEqual(_page_of(patched, "period_label"), "overview")
        self.assertEqual(label["widget"]["spec"]["widgetType"], "table")
        self.assertEqual(label["widget"]["spec"]["encodings"]["columns"][0]["fieldName"], "period_label")
        self.assertNotIn("parameters", label["widget"]["queries"][0]["query"])
        for name, position in before.items():
            moved = _widget(patched, name)["position"]
            self.assertEqual(moved["y"], position["y"] + 2, name)
            self.assertEqual(moved["x"], position["x"], name)
        self.assertEqual(_widget(patched, "top_merchants")["widget"], merchants["widget"])
        for dataset in patched["datasets"]:
            if dataset["name"] in ("ds_all", "ds_consumption", "ds_period_label"):
                self.assertEqual(dataset["parameters"], [PERIOD_PARAMETER])
                self.assertEqual(dataset["parameters"][0]["displayName"], "Period")
                self.assertEqual(
                    list(dataset["parameters"][0]),
                    ["displayName", "keyword", "dataType", "defaultSelection"],
                )
            else:
                self.assertNotIn("parameters", dataset)
            sql = "".join(dataset["queryLines"])
            if dataset["name"] in ("ds_all", "ds_consumption"):
                self.assertIn("TRY_CAST(substring(:period, 1, 4) AS INT)", sql)
                self.assertNotIn("ELSE CAST(substring(:period", sql)
                self.assertIn("unix_timestamp(current_timestamp()) - 6 * 3600", sql)
        link = next(c for c in merchants["widget"]["spec"]["encodings"]["columns"] if c["fieldName"] == "source_email")
        self.assertEqual(link["link"]["templatedURL"], "{{@}}")


def _page_of(dashboard, name):
    for page in dashboard["pages"]:
        for item in page["layout"]:
            if item["widget"]["name"] == name:
                return page["name"]
    return None


class SparkAnsiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pyspark.sql import SparkSession
        cls.spark = (
            SparkSession.builder.master("local[1]")
            .config("spark.ui.enabled", "false")
            .config("spark.sql.ansi.enabled", "true")
            .config("spark.sql.session.timeZone", "UTC")
            .getOrCreate()
        )
        cls.spark.sparkContext.setLogLevel("ERROR")
        cls.spark.sql("""
            CREATE OR REPLACE TEMP VIEW silver_charges AS
            SELECT * FROM VALUES
              ('a', 'm1', DATE '2025-12-31', 10.0, 'A', 'A', 'BI', '1111', 'other', 'transfer', true),
              ('b', 'm2', DATE '2026-11-06', 7.0, 'E', 'E', 'Credicomer', '0707', 'restaurants', 'purchase', true),
              ('c', 'm3', DATE '2024-02-29', 8.0, 'F', 'F', 'BI', '2222', 'other', 'purchase', false)
            AS t(charge_id, message_id, charge_date_sv, amount_usd, merchant, merchant_norm, bank, card_last4, category, movement_type, is_consumption)
        """)

    @classmethod
    def tearDownClass(cls):
        cls.spark.stop()

    def test_bare_cast_of_all_throws(self):
        with self.assertRaises(Exception) as caught:
            self.spark.sql("SELECT CAST(substring('All', 1, 4) AS INT)").collect()
        self.assertIn("CAST_INVALID_INPUT", str(caught.exception))

    def test_shipped_sql_keeps_all_history_and_an_older_month(self):
        dashboard = json.loads((ROOT / "tests" / "fixtures" / "dashboard_schema.json").read_text())
        patched, _ = patch_dashboard(dashboard)
        self.spark.conf.set("spark.sql.session.timeZone", "UTC")
        self.spark.sql(
            "CREATE OR REPLACE TEMP VIEW bronze_mail_alerts AS "
            "SELECT CAST(NULL AS STRING) message_id, CAST(NULL AS STRING) thread_id, "
            "TIMESTAMP '2026-01-01' ingested_at WHERE false"
        )
        now = datetime(2026, 11, 7, 23, 20, tzinfo=UTC)
        for period, dates in (("All", ["2024-02-29", "2025-12-31", "2026-11-06"]), ("2024-02", ["2024-02-29"])):
            for name in ("ds_all", "ds_consumption"):
                sql = "".join(next(d["queryLines"] for d in patched["datasets"] if d["name"] == name))
                sql = sql.replace(":period", quote_period(period))
                sql = sql.replace("workspace.personal_expenses.silver_charges", "silver_charges")
                sql = sql.replace("workspace.personal_expenses.bronze_mail_alerts", "bronze_mail_alerts")
                sql = sql.replace("current_timestamp()", f"TIMESTAMP '{now.strftime('%Y-%m-%d %H:%M:%S')}'")
                rows = self.spark.sql(sql).collect()
                got = sorted(row.charge_date_sv.isoformat() for row in rows)
                expect = dates if name == "ds_all" or period == "All" else ["2024-02-29"]
                if name == "ds_consumption" and period == "All":
                    expect = ["2025-12-31", "2026-11-06"]
                if name == "ds_consumption" and period == "2024-02":
                    expect = []
                self.assertEqual(got, expect, f"{name} {period}")

    def test_yesterday_ignores_session_timezone(self):
        cases = [
            datetime(2026, 1, 1, 6, 30, tzinfo=UTC),
            datetime(2026, 1, 1, 5, 30, tzinfo=UTC),
            datetime(2026, 1, 2, 6, 30, tzinfo=UTC),
            datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
            datetime(2026, 12, 1, 6, 30, tzinfo=UTC),
            datetime(2024, 3, 1, 6, 30, tzinfo=UTC),
            datetime(2025, 3, 1, 6, 30, tzinfo=UTC),
        ]
        zones = ["UTC", "America/Los_Angeles", "Asia/Tokyo", "America/El_Salvador", "Pacific/Kiritimati"]
        sv = ZoneInfo("America/El_Salvador")
        for instant in cases:
            expected = instant.astimezone(sv).date() - timedelta(days=1)
            for zone in zones:
                self.spark.conf.set("spark.sql.session.timeZone", zone)
                wall = instant.astimezone(ZoneInfo(zone)).strftime("%Y-%m-%d %H:%M:%S")
                expr = YESTERDAY_SQL.replace("current_timestamp()", f"to_timestamp('{wall}')")
                got = self.spark.sql(f"SELECT {expr} AS yest").collect()[0].yest
                self.assertEqual(got.isoformat(), expected.isoformat(), f"{instant} {zone}")


if __name__ == "__main__":
    unittest.main()
