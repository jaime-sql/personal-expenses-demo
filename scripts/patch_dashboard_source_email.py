#!/usr/bin/env python3
"""Patch the Personal Expenses YTD Lakeview dashboard.

Changes only dataset ``ds_consumption`` (adds a per-charge Gmail source column)
and widget ``top_merchants`` (shows it as a link). Filters, other datasets, and
other widgets are left as they were. A missing bronze thread is NULL, not a Gmail URL. The column link template is
exactly ``{{@}}`` (the cell value). Lakeview's table Link action uses that
value as the URL, so a NULL cell has no address. A static
``https://mail.google.com/...#all/{{id}}`` prefix is not used: a null id would
still open the mailbox root.

This module does not call Databricks. ``deploy_personal_expenses.py`` fetches
the live dashboard, runs ``patch_serialized_dashboard``, and publishes.
"""
import copy, json, re
from alert_parser import GMAIL_ID_PATTERN, GMAIL_LINK_TEMPLATE, gmail_alert_url

# Documented Lakeview table Link action: templatedURL {{@}} is the cell value
# (https://docs.databricks.com/aws/en/dashboards/manage/visualizations/tables).
SOURCE_LINK_TEMPLATE = "{{@}}"

DATASET = "ds_consumption"
WIDGET = "top_merchants"
MARKER = "-- personal_expenses_source_email"
SILVER_FQN = "workspace.personal_expenses.silver_charges"
BRONZE_FQN = "workspace.personal_expenses.bronze_mail_alerts"

_SUM_AMT = re.compile(r"^SUM\(`?amount_usd`?\)$", re.I)
# The live top_merchants grid uses COUNT(1), not COUNT(*).
_COUNT_MEASURE = re.compile(r"^COUNT\((?:\*|1)\)$", re.I)
_AGG = re.compile(r"\b(SUM|COUNT|AVG|MIN|MAX)\s*\(", re.I)
_FQN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")

# One charge per group (charge_id is a dimension). The cell is the full URL or NULL.
# COUNT ignores nulls, so a charge with no thread stays NULL instead of a partial URL.
SOURCE_EMAIL_URL_EXPR = "`source_email_url`"
SOURCE_EMAIL_URL_GROUP_EXPR = (
    "CASE WHEN COUNT(`source_email_url`) = COUNT(*) "
    "AND COUNT(DISTINCT `source_email_url`) = 1 "
    "THEN MIN(`source_email_url`) ELSE CAST(NULL AS STRING) END"
)


class DashboardPatchError(Exception):
    pass


def validate_source_link_template(template):
    """The Link action URL must be the cell itself.

    Databricks documents ``{{@}}`` as the cell value
    (https://docs.databricks.com/aws/en/dashboards/manage/visualizations/tables).
    A template with a fixed Gmail prefix still resolves to the mailbox root
    when the thread id is NULL, and that root is clickable.
    """
    if template != SOURCE_LINK_TEMPLATE:
        raise DashboardPatchError(
            "source link templatedURL must be exactly {{@}} (the cell value), "
            "not a Gmail URL with a nullable id"
        )
    return template


def validate_gmail_link_template(template, sample_thread="18f0aabbccddeeff"):
    """Check a fully built Gmail URL (SQL value), not a column template.

    Returns the URL. NULL lineage is not a URL and must not be passed here.
    """
    if template is None:
        raise DashboardPatchError("missing lineage has no URL")
    if not isinstance(template, str) or not template:
        raise DashboardPatchError("Gmail URL is empty")
    if "@" in template:
        raise DashboardPatchError("Gmail URL contains a raw @; percent-encode the mailbox")
    if "%2540" in template:
        raise DashboardPatchError("Gmail mailbox is double-encoded (%2540)")
    if template.count("%40") != 1:
        raise DashboardPatchError("Gmail mailbox must be percent-encoded exactly once")
    if "{{" in template:
        raise DashboardPatchError("a stored URL must not contain a Lakeview placeholder")
    if not template.startswith("https://mail.google.com/mail/"):
        raise DashboardPatchError("link must be an absolute https://mail.google.com/mail/ URL")
    if any(c.isspace() for c in template):
        raise DashboardPatchError("Gmail URL contains whitespace")
    expected = gmail_alert_url(sample_thread)
    if not template.endswith("/" + sample_thread):
        raise DashboardPatchError(f"URL {template!r} does not end with the thread id")
    if expected is None or template != expected:
        raise DashboardPatchError(f"URL {template!r} != {expected!r}")
    if not re.fullmatch(
        r"https://mail\.google\.com/mail/\?authuser=jg0592%40gmail\.com#all/[0-9a-fA-F]{15,20}",
        template,
    ):
        raise DashboardPatchError(f"URL failed encoding check: {template}")
    return template


def _check_fqn(fqn):
    if not _FQN.fullmatch(fqn or ""):
        raise DashboardPatchError(f"refusing unsafe table name {fqn!r}")
    return fqn


def _top_level_spans(sql, keyword):
    key = keyword.upper()
    upper = sql.upper()
    depth = 0
    in_str = None
    i = 0
    hits = []
    while i < len(sql):
        ch = sql[i]
        if in_str:
            if ch == in_str and sql[i - 1] != "\\":
                in_str = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            in_str = ch
            i += 1
            continue
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth == 0 and upper.startswith(key, i):
            before_ok = i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")
            after = i + len(key)
            after_ok = after >= len(sql) or not (sql[after].isalnum() or sql[after] == "_")
            if before_ok and after_ok:
                hits.append(i)
                i = after
                continue
        i += 1
    return hits


def _split_top_level_commas(text):
    depth = 0
    in_str = None
    parts, buf = [], []
    for i, ch in enumerate(text):
        if in_str:
            buf.append(ch)
            if ch == in_str and text[i - 1] != "\\":
                in_str = None
            continue
        if ch in ("'", '"', "`"):
            in_str = ch
            buf.append(ch)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    return parts


def _select_list_text(sql):
    starts = _top_level_spans(sql, "SELECT")
    froms = _top_level_spans(sql, "FROM")
    if not starts or not froms or froms[0] < starts[0]:
        return ""
    return sql[starts[0] + len("SELECT"):froms[0]]


def _exposes_column(sql, col):
    items = _split_top_level_commas(_select_list_text(sql))
    for item in items:
        p = item.strip()
        if p == "*" or p.endswith(".*"):
            return True
        if re.fullmatch(rf"(`?{col}`?|[A-Za-z_][A-Za-z0-9_]*\.`?{col}`?)", p, re.I):
            return True
        if re.search(rf"(?i)\bas\s+`?{col}`?\s*$", p):
            return True
    return False


def _strip_trailing_order_by(sql):
    sql = sql.strip().rstrip(";")
    hits = _top_level_spans(sql, "ORDER BY")
    if not hits:
        return sql, None
    i = hits[-1]
    return sql[:i].strip(), sql[i:].strip()


def _inject_columns(sql, cols):
    missing = [c for c in cols if not re.search(rf"\b{c}\b", sql, re.I)]
    if not missing:
        return sql
    if _top_level_spans(sql, "JOIN") or _top_level_spans(sql, "UNION"):
        raise DashboardPatchError(
            "ds_consumption needs charge_id, message_id, and merchant, and the query is not a single SELECT"
        )
    starts = _top_level_spans(sql, "SELECT")
    if len(starts) != 1:
        raise DashboardPatchError("ds_consumption SELECT is not a single statement; not rewriting it")
    i = starts[0] + len("SELECT")
    return sql[:i] + " " + ", ".join(missing) + "," + sql[i:]


def _url_expr(message_expr):
    """Full Gmail URL, or NULL when bronze has no real thread.

    The ELSE branch is NULL. It is not a mailbox URL with an empty fragment.
    """
    pat = GMAIL_ID_PATTERN
    prefix = GMAIL_LINK_TEMPLATE.split("{{source_thread_id}}", 1)[0]
    if "{{" in prefix or not prefix.startswith("https://mail.google.com/mail/") or not prefix.endswith("#all/"):
        raise DashboardPatchError("Gmail URL prefix is not a fixed https mailbox URL")
    cond = (
        "src_bronze.message_id IS NOT NULL"
        f" AND {message_expr} RLIKE '{pat}'"
        f" AND src_bronze.thread_id RLIKE '{pat}'"
    )
    return (
        f"  CASE WHEN {cond} THEN concat('{prefix}', src_bronze.thread_id) "
        "ELSE CAST(NULL AS STRING) END AS source_email_url"
    )


def _bronze_join(bronze_fqn, message_expr):
    return (
        "LEFT JOIN (\n"
        "  SELECT message_id, max_by(thread_id, ingested_at) AS thread_id\n"
        f"  FROM {bronze_fqn}\n"
        "  WHERE message_id IS NOT NULL AND message_id <> ''\n"
        "  GROUP BY message_id\n"
        ") src_bronze\n"
        f"  ON {message_expr} = src_bronze.message_id"
    )


def _inner_of_marked(sql):
    """Query nested in ``FROM ( ... ) base`` of a previously wrapped dataset."""
    marker_at = sql.find(MARKER)
    from_at = sql.find("FROM (", marker_at)
    if marker_at < 0 or from_at < 0:
        return None
    i = from_at + len("FROM (")
    depth = 1
    in_str = None
    while i < len(sql):
        ch = sql[i]
        if in_str:
            if ch == in_str and sql[i - 1] != "\\":
                in_str = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            in_str = ch
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return sql[from_at + len("FROM ("):i].strip()
        i += 1
    return None


def wrap_consumption_sql(sql, silver_fqn=SILVER_FQN, bronze_fqn=BRONZE_FQN):
    """Add source_email_url (full URL or NULL) without dropping existing columns.

    Detail queries stay one row per charge. A grouped query that has no
    message_id gets a NULL URL column so the join cannot multiply totals.
    """
    raw = (sql or "").strip()
    if not raw:
        raise DashboardPatchError("ds_consumption query is empty")
    if MARKER in raw:
        inner = _inner_of_marked(raw)
        if not inner:
            raise DashboardPatchError("marked consumption query has no inner SELECT to refresh")
        raw = inner
    _check_fqn(silver_fqn)
    _check_fqn(bronze_fqn)
    inner, _order = _strip_trailing_order_by(raw)
    grouped = bool(_top_level_spans(inner, "GROUP BY"))
    order = ""
    if _exposes_column(inner, "charge_date_sv") or (
        not grouped and re.search(r"select\s+\*", inner, re.I)
    ):
        # SELECT * exposes charge_date_sv from silver. _exposes_column handles the star.
        if _exposes_column(inner, "charge_date_sv"):
            order = "\nORDER BY base.charge_date_sv DESC"
    if grouped:
        if _exposes_column(inner, "message_id"):
            lineage = _url_expr("base.message_id")
            join = _bronze_join(bronze_fqn, "base.message_id")
            grain = "grouped"
        else:
            lineage = "  CAST(NULL AS STRING) AS source_email_url"
            join = ""
            grain = "grouped_no_message"
    else:
        if not re.search(r"select\s+\*", inner, re.I):
            inner = _inject_columns(inner, ["charge_id", "message_id", "merchant"])
            if _exposes_column(inner, "charge_date_sv"):
                order = "\nORDER BY base.charge_date_sv DESC"
        lineage = _url_expr("coalesce(base.message_id, src_silver.message_id)")
        join = (
            f"LEFT JOIN {silver_fqn} src_silver\n"
            "  ON base.charge_id = src_silver.charge_id\n"
            + _bronze_join(bronze_fqn, "coalesce(base.message_id, src_silver.message_id)")
        )
        grain = "detail"
    wrapped = (
        f"{MARKER}\n"
        "SELECT\n"
        "  base.*,\n"
        f"{lineage}\n"
        "FROM (\n"
        f"{inner}\n"
        ") base\n"
        f"{join}"
        f"{order}\n"
    )
    wrapped = wrapped.replace("\n\n\n", "\n\n")
    return wrapped, grain


def _dataset_sql(ds):
    if ds.get("queryLines"):
        return "".join(ds["queryLines"])
    return ds.get("query") or ""


def _set_dataset_sql(ds, sql):
    if "queryLines" in ds:
        ds["queryLines"] = [sql if sql.endswith("\n") else sql + "\n"]
    elif "query" in ds:
        ds["query"] = sql
    else:
        ds["queryLines"] = [sql if sql.endswith("\n") else sql + "\n"]


def _find_dataset(sd):
    hits = [d for d in sd.get("datasets") or [] if d.get("name") == DATASET]
    if len(hits) != 1:
        found = [d.get("name") for d in sd.get("datasets") or []]
        raise DashboardPatchError(f"expected one dataset {DATASET}, found {found}")
    return hits[0]


def _find_widget(sd):
    hits = []
    for page in sd.get("pages") or []:
        for item in page.get("layout") or []:
            widget = (item or {}).get("widget") or {}
            if widget.get("name") == WIDGET:
                hits.append(widget)
    if len(hits) != 1:
        raise DashboardPatchError(f"expected one widget {WIDGET}, found {len(hits)}")
    return hits[0]


def _compact(expr):
    return re.sub(r"\s+", "", expr or "")


def _upsert_field(fields, name, expression):
    for field in fields:
        if field.get("name") == name:
            field["expression"] = expression
            return
    fields.append({"name": name, "expression": expression})


def _rewrite_merchant_field(field):
    expr = field.get("expression") or ""
    if _AGG.search(expr):
        return False
    compact = _compact(expr)
    name = (field.get("name") or "").lower()
    if compact in ("`merchant_norm`", "merchant_norm") or (
        name == "merchant_norm" and "merchant" in compact
    ):
        field["expression"] = "`merchant`"
        return True
    return False


def _ensure_charge_id_column(columns):
    """Group by charge_id without adding a visible hash column.

    Lakeview groups an aggregated table by its dimension columns. The column
    stays in the encoding so the grain includes it, and ``visible`` is false
    so the existing Merchant / date / bank / category / USD / N columns stay
    the ones on screen. ``visible`` is the eye-toggle the table editor persists.
    """
    for column in columns:
        if column.get("fieldName") == "charge_id":
            column["visible"] = False
            return
    columns.append({
        "fieldName": "charge_id",
        "displayName": "charge_id",
        "visible": False,
    })


def _patch_widget(widget, grain):
    queries = widget.get("queries") or []
    if not queries:
        raise DashboardPatchError("top_merchants has no queries")
    query = queries[0].get("query")
    if not isinstance(query, dict):
        raise DashboardPatchError("top_merchants query is missing")
    if query.get("datasetName") not in (None, DATASET):
        raise DashboardPatchError(
            f"top_merchants reads dataset {query.get('datasetName')!r}, not {DATASET}"
        )
    fields = query.setdefault("fields", [])
    saved_filter = query.get("filter")
    merchant_rewritten = any(_rewrite_merchant_field(f) for f in fields)
    # The live grid is SUM(amount_usd), COUNT(1), grouped by merchant / date /
    # bank / category. Two charges in that group used to share one cell, so the
    # link was unavailable. charge_id is one row in silver, so adding it to the
    # group keeps SUM and COUNT (each charge sums to itself and counts as 1)
    # and gives that row its own thread. A dataset that is already grouped in
    # SQL and has no charge_id cannot be split this way.
    spec = widget.setdefault("spec", {})
    encodings = spec.setdefault("encodings", {})
    columns = encodings.setdefault("columns", [])
    if not isinstance(columns, list):
        raise DashboardPatchError("top_merchants columns encoding is not a list")
    aggs = [f for f in fields if _AGG.search(f.get("expression") or "")]
    if grain == "detail" and aggs:
        _upsert_field(fields, "charge_id", "`charge_id`")
        _ensure_charge_id_column(columns)
        query["disaggregated"] = False
        widget_grain = "per_charge"
        link_aggregate = True
    elif aggs:
        query["disaggregated"] = False
        widget_grain = "grouped_explicit"
        link_aggregate = True
    else:
        query["disaggregated"] = True
        widget_grain = "detail"
        link_aggregate = False
    query["fields"] = [f for f in fields if f.get("name") != "source_thread_id"]
    fields = query["fields"]
    if link_aggregate:
        _upsert_field(fields, "source_email", SOURCE_EMAIL_URL_GROUP_EXPR)
    else:
        _upsert_field(fields, "source_email", SOURCE_EMAIL_URL_EXPR)
    if saved_filter is not None:
        query["filter"] = saved_filter
    validate_source_link_template(SOURCE_LINK_TEMPLATE)
    link = {"templatedURL": SOURCE_LINK_TEMPLATE}
    existing = next((c for c in columns if c.get("fieldName") == "source_email"), None)
    if existing is None:
        columns.append({
            "fieldName": "source_email",
            "displayName": "Source email",
            "link": link,
        })
    else:
        existing["link"] = link
        existing.setdefault("displayName", "Source email")
    # The thread id is an input to the link template, not its own column.
    encodings["columns"] = [c for c in columns if c.get("fieldName") != "source_thread_id"]
    return {"widget_grain": widget_grain, "merchant_shows_original": merchant_rewritten, "dataset_grain": grain}


def assert_patch_is_narrow(before, after):
    """Every node except the consumption query and the merchants widget is unchanged."""
    def blank(sd):
        sd = copy.deepcopy(sd)
        for ds in sd.get("datasets") or []:
            if ds.get("name") == DATASET:
                ds.pop("query", None)
                ds.pop("queryLines", None)
        for page in sd.get("pages") or []:
            for item in page.get("layout") or []:
                widget = (item or {}).get("widget") or {}
                if widget.get("name") == WIDGET:
                    item["widget"] = {"name": WIDGET}
        return sd
    if blank(before) != blank(after):
        raise DashboardPatchError(
            "patch would change something other than ds_consumption's query and widget top_merchants"
        )


def patch_serialized_dashboard(sd, silver_fqn=SILVER_FQN, bronze_fqn=BRONZE_FQN):
    """Return (patched_dashboard, report). Does not mutate ``sd``."""
    if not isinstance(sd, dict):
        raise DashboardPatchError("serialized dashboard is not an object")
    original = copy.deepcopy(sd)
    patched = copy.deepcopy(sd)
    dataset = _find_dataset(patched)
    sql, grain = wrap_consumption_sql(_dataset_sql(dataset), silver_fqn, bronze_fqn)
    if "@" in sql:
        raise DashboardPatchError("consumption SQL contains a raw @")
    null_url = (
        "ELSE CAST(NULL AS STRING) END AS source_email_url" in sql
        or re.search(r"CAST\(NULL AS STRING\) AS source_email_url\s*$", sql, re.M) is not None
    )
    if "AS source_email_url" not in sql or not null_url:
        raise DashboardPatchError("source_email_url must be NULL when lineage is missing")
    _set_dataset_sql(dataset, sql)
    widget = _find_widget(patched)
    report = _patch_widget(widget, grain)
    report.update({
        "dataset": DATASET,
        "widget": WIDGET,
        "link_template": SOURCE_LINK_TEMPLATE,
        "sample_url": validate_gmail_link_template(gmail_alert_url("18f0aabbccddeeff"), "18f0aabbccddeeff"),
        "date_order": "ORDER BY base.charge_date_sv DESC" in sql,
        "silver_fqn": silver_fqn,
        "bronze_fqn": bronze_fqn,
    })
    assert_patch_is_narrow(original, patched)
    # A second apply is a no-op aside from key order inside the widget query.
    return patched, report


def patch_is_idempotent(sd, silver_fqn=SILVER_FQN, bronze_fqn=BRONZE_FQN):
    once, _ = patch_serialized_dashboard(sd, silver_fqn, bronze_fqn)
    twice, _ = patch_serialized_dashboard(once, silver_fqn, bronze_fqn)
    return once == twice
