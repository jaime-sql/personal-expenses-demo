"""Add the Auto period selector and remove the Year and Month dropdowns.

Year and Month are separate single-value field filters. A second predicate
on the same columns would stack with Auto, so those two widgets are removed.
Day, movement type, and every chart, KPI, and the merchants table stay.

The selector is a documented query-based single-value parameter
(https://docs.databricks.com/aws/en/dashboards/manage/filters/parameters):
the choices dataset supplies Auto, All, and each YYYY-MM present in silver.
The default value is the literal Auto. Auto's meaning is calculated in SQL
on every query, not stored as a calendar date.

The resolved month and year is a counter bound to the same parameter, so
the text changes when the query runs instead of a markdown date.
"""
import copy

from period_sql import (
    CHOICES_SQL, LABEL_SQL, PERIOD_DEFAULT, PERIOD_KEYWORD, PERIOD_MARKER,
    PERIOD_PARAMETER, inject_period_predicate,
)

YEAR_WIDGET = "flt_year"
MONTH_WIDGET = "flt_month"
PERIOD_WIDGET = "flt_period"
LABEL_WIDGET = "period_label"
DAY_WIDGET = "flt_day"
MOVEMENT_WIDGET = "flt_movement_type"
CHOICES_DATASET = "ds_period_choices"
LABEL_DATASET = "ds_period_label"
FILTERED_DATASETS = ("ds_all", "ds_consumption")


class OpeningPeriodError(Exception):
    pass


def _dataset(dashboard, name):
    hits = [d for d in dashboard.get("datasets") or [] if d.get("name") == name]
    if len(hits) != 1:
        raise OpeningPeriodError(f"expected one dataset {name}, found {len(hits)}")
    return hits[0]


def _sql(dataset):
    if dataset.get("queryLines"):
        return "".join(dataset["queryLines"])
    return dataset.get("query") or ""


def _set_sql(dataset, sql):
    if not sql.endswith("\n"):
        sql += "\n"
    if "queryLines" in dataset or "query" not in dataset:
        dataset["queryLines"] = [sql]
        dataset.pop("query", None)
    else:
        dataset["query"] = sql


def _ensure_parameter(dataset):
    params = dataset.setdefault("parameters", [])
    for param in params:
        if param.get("keyword") == PERIOD_KEYWORD:
            param.clear()
            param.update(copy.deepcopy(PERIOD_PARAMETER))
            return
    params.append(copy.deepcopy(PERIOD_PARAMETER))


def _pages(dashboard):
    return dashboard.get("pages") or []


def _filter_page(dashboard):
    for page in _pages(dashboard):
        if page.get("pageType") == "PAGE_TYPE_GLOBAL_FILTERS" or page.get("name") == "global_filters":
            return page
    raise OpeningPeriodError("dashboard has no global filters page")


def _drop_widgets(page, names):
    page["layout"] = [
        item for item in page.get("layout") or []
        if ((item.get("widget") or {}).get("name") not in names)
    ]


def _find_widget(dashboard, name):
    for page in _pages(dashboard):
        for item in page.get("layout") or []:
            if (item.get("widget") or {}).get("name") == name:
                return item
    return None


def _period_filter():
    def binding(dataset, query_name):
        return {
            "name": query_name,
            "query": {
                "datasetName": dataset,
                "parameters": [{"name": PERIOD_KEYWORD, "keyword": PERIOD_KEYWORD}],
                "disaggregated": False,
            },
        }
    return {
        "widget": {
            "name": PERIOD_WIDGET,
            "queries": [
                {
                    "name": "q_period_choices",
                    "query": {
                        "datasetName": CHOICES_DATASET,
                        "fields": [{"name": "period_choice", "expression": "`period_choice`"}],
                        "disaggregated": False,
                    },
                },
                binding("ds_all", "q_period_all"),
                binding("ds_consumption", "q_period_cons"),
                binding(LABEL_DATASET, "q_period_label"),
            ],
            "spec": {
                "version": 2,
                "widgetType": "filter-single-select",
                "encodings": {
                    "fields": [
                        {
                            "fieldName": "period_choice",
                            "displayName": "Period",
                            "queryName": "q_period_choices",
                        },
                        {"parameterName": PERIOD_KEYWORD, "queryName": "q_period_all"},
                        {"parameterName": PERIOD_KEYWORD, "queryName": "q_period_cons"},
                        {"parameterName": PERIOD_KEYWORD, "queryName": "q_period_label"},
                    ]
                },
                "selection": {
                    "defaultSelection": copy.deepcopy(PERIOD_PARAMETER["defaultSelection"])
                },
                "frame": {"showTitle": True, "title": "Period"},
            },
        },
        "position": {"x": 0, "y": 0, "width": 4, "height": 2},
    }


def _canvas_page(dashboard):
    for page in _pages(dashboard):
        if page.get("name") == "overview" or page.get("pageType") == "PAGE_TYPE_CANVAS":
            return page
    raise OpeningPeriodError("dashboard has no canvas page")


def _label_table():
    """One-cell table. Counter value encodings in the widget spec are numeric."""
    return {
        "widget": {
            "name": LABEL_WIDGET,
            "queries": [{
                "name": "main_query",
                "query": {
                    "datasetName": LABEL_DATASET,
                    "fields": [{"name": "period_label", "expression": "`period_label`"}],
                    "disaggregated": True,
                },
            }],
            "spec": {
                "version": 2,
                "widgetType": "table",
                "encodings": {
                    "columns": [{
                        "fieldName": "period_label",
                        "displayName": "Period",
                    }]
                },
                "frame": {"showTitle": True, "title": "Showing"},
            },
        },
        "position": {"x": 0, "y": 0, "width": 12, "height": 2},
    }


def _overlaps(left, right):
    return (
        left["x"] < right["x"] + right["width"]
        and right["x"] < left["x"] + left["width"]
        and left["y"] < right["y"] + right["height"]
        and right["y"] < left["y"] + left["height"]
    )


def _assert_no_overlap(page):
    items = page.get("layout") or []
    for index, item in enumerate(items):
        for other in items[index + 1:]:
            if _overlaps(item["position"], other["position"]):
                raise OpeningPeriodError(
                    f"{item['widget']['name']} overlaps {other['widget']['name']} on {page.get('name')}"
                )


def _place_label(page):
    layout = page.setdefault("layout", [])
    already = any((item.get("widget") or {}).get("name") == LABEL_WIDGET for item in layout)
    page["layout"] = [
        item for item in layout
        if (item.get("widget") or {}).get("name") != LABEL_WIDGET
    ]
    if not already:
        for item in page["layout"]:
            item["position"]["y"] = item["position"]["y"] + 2
    page["layout"].insert(0, _label_table())


def _rewrite_title(dashboard):
    item = _find_widget(dashboard, "title")
    if not item:
        return
    spec = item["widget"].get("multilineTextboxSpec") or {}
    lines = spec.get("lines")
    if not lines:
        return
    spec["lines"] = [line.replace("Year / Month / Day", "Period / Day") for line in lines]


def _upsert_dataset(dashboard, name, display, sql, parameter):
    hits = [d for d in dashboard.get("datasets") or [] if d.get("name") == name]
    body = {
        "name": name,
        "displayName": display,
        "queryLines": [sql if sql.endswith("\n") else sql + "\n"],
    }
    if parameter:
        body["parameters"] = [copy.deepcopy(PERIOD_PARAMETER)]
    if hits:
        hits[0].clear()
        hits[0].update(body)
    else:
        dashboard.setdefault("datasets", []).append(body)


def validate_dashboard_schema(dashboard):
    """Check fields the live dashboard already has, plus parameter displayName.

    The PATCH error was ``parameters[0].displayName must not be empty`` on
    ds_all, ds_consumption, and ds_period_label. Keyword, dataType, and
    defaultSelection were not reported, so they are already accepted.
    Widget query bindings stay ``name`` plus ``keyword``; that is the
    documented parameter binding and the error did not mention them.
    """
    for dataset in dashboard.get("datasets") or []:
        for key in ("name", "displayName"):
            if not str(dataset.get(key) or "").strip():
                raise OpeningPeriodError(f"dataset {key} must not be empty")
        if not dataset.get("queryLines"):
            raise OpeningPeriodError(f"{dataset.get('name')} queryLines must not be empty")
        for index, param in enumerate(dataset.get("parameters") or []):
            for key in ("displayName", "keyword", "dataType"):
                if not str(param.get(key) or "").strip():
                    raise OpeningPeriodError(
                        f"{dataset.get('name')} parameters[{index}].{key} must not be empty"
                    )
            values = ((param.get("defaultSelection") or {}).get("values") or {})
            chosen = values.get("values") or []
            if values.get("dataType") != param["dataType"] or not chosen or not str(chosen[0].get("value") or "").strip():
                raise OpeningPeriodError(
                    f"{dataset.get('name')} parameters[{index}].defaultSelection must be a non-empty {param.get('dataType')} value"
                )
    for page in dashboard.get("pages") or []:
        for key in ("name", "displayName", "pageType"):
            if not str(page.get(key) or "").strip():
                raise OpeningPeriodError(f"page {key} must not be empty")
        for item in page.get("layout") or []:
            widget = item.get("widget") or {}
            if not str(widget.get("name") or "").strip():
                raise OpeningPeriodError(f"widget name must not be empty on {page.get('name')}")
            if "spec" in widget and not (widget.get("spec") or {}).get("widgetType"):
                raise OpeningPeriodError(f"{widget.get('name')} widgetType must not be empty")


def patch_dashboard(dashboard):
    """Return ``(patched, report)``. Does not mutate ``dashboard``."""
    if not isinstance(dashboard, dict):
        raise OpeningPeriodError("dashboard JSON must be an object")
    patched = copy.deepcopy(dashboard)
    for name in FILTERED_DATASETS:
        dataset = _dataset(patched, name)
        _ensure_parameter(dataset)
        _set_sql(dataset, inject_period_predicate(_sql(dataset)))
        if PERIOD_MARKER not in _sql(dataset):
            raise OpeningPeriodError(f"{name} is missing the period predicate")
    _upsert_dataset(patched, CHOICES_DATASET, "Period choices", CHOICES_SQL, False)
    _upsert_dataset(patched, LABEL_DATASET, "Resolved period", LABEL_SQL, True)

    page = _filter_page(patched)
    _drop_widgets(page, {YEAR_WIDGET, MONTH_WIDGET, PERIOD_WIDGET, LABEL_WIDGET})
    page.setdefault("layout", []).insert(0, _period_filter())
    _place_label(_canvas_page(patched))
    _rewrite_title(patched)
    for item in page.get("layout") or []:
        kind = ((item.get("widget") or {}).get("spec") or {}).get("widgetType") or ""
        if not kind.startswith("filter-"):
            raise OpeningPeriodError(f"global filters page has non-filter widget {item['widget'].get('name')}")
    for check_page in _pages(patched):
        _assert_no_overlap(check_page)

    if _find_widget(patched, YEAR_WIDGET) or _find_widget(patched, MONTH_WIDGET):
        raise OpeningPeriodError("Year or Month filter is still on the dashboard")
    if not _find_widget(patched, "flt_day") or not _find_widget(patched, "flt_movement_type"):
        raise OpeningPeriodError("Day or movement filter was removed")
    label_page = None
    for candidate in _pages(patched):
        if any((item.get("widget") or {}).get("name") == LABEL_WIDGET for item in candidate.get("layout") or []):
            label_page = candidate
    if label_page is None or label_page.get("pageType") == "PAGE_TYPE_GLOBAL_FILTERS":
        raise OpeningPeriodError("resolved period label must sit on the canvas page")
    label = _find_widget(patched, LABEL_WIDGET)
    if label["widget"]["spec"]["widgetType"] != "table":
        raise OpeningPeriodError("resolved period label is not a string table")
    validate_dashboard_schema(patched)
    report = {
        "period_default": PERIOD_DEFAULT,
        "period_keyword": PERIOD_KEYWORD,
        "removed_widgets": [YEAR_WIDGET, MONTH_WIDGET],
        "added_widgets": [PERIOD_WIDGET, LABEL_WIDGET],
        "datasets": [d.get("name") for d in patched.get("datasets") or []],
        "history_option": "All",
        "manual_periods": "YYYY-MM values present in silver_charges",
    }
    return patched, report


def patch_is_idempotent(dashboard):
    once, _ = patch_dashboard(dashboard)
    twice, _ = patch_dashboard(once)
    return once == twice
