"""Dataset SQL for the Auto period parameter.

Auto is yesterday's calendar date in America/El_Salvador. On the 1st that
date is in the previous month, so January 1 selects the previous December.
From the 2nd onward it is still the current month.

The value is a string parameter, default ``Auto``. ``All`` returns every
month. ``YYYY-MM`` selects that month. Documented as a single-value
parameter with a custom All sentinel:
https://docs.databricks.com/aws/en/dashboards/manage/filters/parameters
"""
import re

PERIOD_KEYWORD = "period"
PERIOD_DEFAULT = "Auto"
PERIOD_ALL = "All"
PERIOD_MARKER = "-- personal_expenses_period"

# America/El_Salvador is UTC-6 all year (no daylight saving). unix_timestamp()
# is the absolute instant, so a session TIMEZONE other than UTC cannot move
# this date. to_date(from_utc_timestamp(...)) follows the session zone and is
# one day off when that zone is not UTC.
# https://docs.databricks.com/aws/en/sql/language-manual/functions/unix_timestamp
YESTERDAY_SQL = (
    "date_sub(date_add(DATE '1970-01-01', CAST(floor(("
    "unix_timestamp(current_timestamp()) - 6 * 3600) / 86400) AS INT)), 1)"
)

# Spark ANSI evaluates CAST inside a CASE ELSE even when :period is All,
# which throws CAST_INVALID_INPUT. TRY_CAST returns NULL for All, Auto, and
# any other non YYYY-MM value.
# https://docs.databricks.com/aws/en/sql/language-manual/functions/try_cast
def _period_part(function, start, length):
    return (
        "CASE\n"
        f"      WHEN :{PERIOD_KEYWORD} = '{PERIOD_DEFAULT}' THEN {function}({YESTERDAY_SQL})\n"
        f"      WHEN :{PERIOD_KEYWORD} RLIKE '^[0-9]{{4}}-[0-9]{{2}}$' "
        f"THEN TRY_CAST(substring(:{PERIOD_KEYWORD}, {start}, {length}) AS INT)\n"
        "      ELSE CAST(NULL AS INT)\n"
        "    END"
    )


PERIOD_PREDICATE = (
    f"{PERIOD_MARKER}\n(\n"
    f"  :{PERIOD_KEYWORD} = '{PERIOD_ALL}'\n"
    "  OR (\n"
    f"    YEAR(charge_date_sv) = {_period_part('YEAR', 1, 4)}\n"
    f"    AND MONTH(charge_date_sv) = {_period_part('MONTH', 6, 2)}\n"
    "  )\n)"
)

# PATCH /api/2.0/lakeview/dashboards rejects a parameter whose displayName
# is missing: INVALID_PARAMETER_VALUE parameters[0].displayName must not be empty.
# The accepted object is displayName, keyword, dataType, and defaultSelection.
PERIOD_PARAMETER = {
    "displayName": "Period",
    "keyword": PERIOD_KEYWORD,
    "dataType": "STRING",
    "defaultSelection": {
        "values": {
            "dataType": "STRING",
            "values": [{"value": PERIOD_DEFAULT}],
        }
    },
}

CHOICES_SQL = """SELECT period_choice
FROM (
  SELECT 'Auto' AS period_choice, 0 AS sort_key
  UNION ALL
  SELECT 'All' AS period_choice, 1 AS sort_key
  UNION ALL
  SELECT concat(
      lpad(CAST(YEAR(charge_date_sv) AS STRING), 4, '0'),
      '-',
      lpad(CAST(MONTH(charge_date_sv) AS STRING), 2, '0')
    ) AS period_choice,
    2 AS sort_key
  FROM workspace.personal_expenses.silver_charges
  WHERE charge_date_sv IS NOT NULL
  GROUP BY YEAR(charge_date_sv), MONTH(charge_date_sv)
) period_choices
ORDER BY sort_key, period_choice DESC
"""

LABEL_SQL = f"""SELECT CASE
  WHEN :{PERIOD_KEYWORD} = '{PERIOD_ALL}' THEN 'All history'
  WHEN :{PERIOD_KEYWORD} = '{PERIOD_DEFAULT}' THEN concat(
    lpad(CAST(YEAR({YESTERDAY_SQL}) AS STRING), 4, '0'),
    '-',
    lpad(CAST(MONTH({YESTERDAY_SQL}) AS STRING), 2, '0')
  )
  ELSE :{PERIOD_KEYWORD}
END AS period_label
"""


def period_label(period, year, month):
    """Label shown beside the selector. ``year``/``month`` are the resolved Auto period."""
    if period == PERIOD_ALL:
        return "All history"
    if period == PERIOD_DEFAULT:
        return f"{int(year):04d}-{int(month):02d}"
    return period


def inject_period_predicate(sql):
    """Add the period predicate once. Existing WHERE clauses stay."""
    if PERIOD_MARKER in sql:
        return sql
    if re.search(r"WHERE\s+is_consumption\s*=\s*true", sql, re.I):
        return re.sub(
            r"WHERE\s+is_consumption\s*=\s*true",
            "WHERE is_consumption = true\nAND " + PERIOD_PREDICATE,
            sql,
            count=1,
            flags=re.I,
        )
    order = re.search(r"\nORDER BY\b", sql, re.I)
    clause = "\nWHERE " + PERIOD_PREDICATE + "\n"
    if order:
        return sql[:order.start()] + clause + sql[order.start():]
    return sql.rstrip() + clause


def quote_period(period):
    if not re.fullmatch(r"Auto|All|\d{4}-\d{2}", period or ""):
        raise ValueError(f"period must be Auto, All, or YYYY-MM, not {period!r}")
    return "'" + period + "'"


def sql_for_engine(sql, period, now_utc):
    """Databricks SQL with :period and current_timestamp bound for a local engine.

    ``now_utc`` is an aware datetime. The yesterday expression is translated
    only for engines that do not have Databricks ``date_sub`` / ``from_utc_timestamp``.
    """
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    stamp = now_utc.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    yesterday = (
        "(CAST(timezone('America/El_Salvador', "
        f"TIMESTAMPTZ '{stamp}+00') AS DATE) - INTERVAL 1 DAY)"
    )
    bound = sql.replace(YESTERDAY_SQL, yesterday)
    bound = bound.replace(f":{PERIOD_KEYWORD}", quote_period(period))
    bound = bound.replace("current_timestamp()", f"TIMESTAMPTZ '{stamp}+00'")
    return bound


def duckdb_sql(sql):
    """Translate the remaining Databricks bits used by the consumption dataset."""
    out = re.sub(
        r"(\S+)\s+RLIKE\s+'([^']*)'",
        r"regexp_full_match(\1, '\2')",
        sql,
    )
    out = out.replace("max_by(thread_id, ingested_at)", "arg_max(thread_id, ingested_at)")
    out = out.replace(" AS STRING", " AS VARCHAR")
    out = out.replace("CAST(NULL AS VARCHAR)", "CAST(NULL AS VARCHAR)")
    return out


# Imported lazily by sql_for_engine's type check. Local import keeps this module
# usable without forcing callers to import datetime names.
from datetime import timezone  # noqa: E402
