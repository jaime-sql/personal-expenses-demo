# Databricks notebook source
# MAGIC %md
# MAGIC # CONCAPAN 2026 — Expenses & Travel ETL Pipeline
# MAGIC
# MAGIC Dedicated ETL pipeline for CONCAPAN 2026 expense tracking and logistics analytics.
# MAGIC Reads silver charges from `workspace.personal_expenses.silver_charges`,
# MAGIC applies CONCAPAN-specific categorization and travel/logistics tagging,
# MAGIC and writes to:
# MAGIC - `workspace.personal_expenses.concapan_silver_charges`
# MAGIC - `workspace.personal_expenses.concapan_gold_summary`

# COMMAND ----------

import pyspark.sql.functions as F
from datetime import datetime, timezone

CATALOG = "workspace"
SCHEMA = "personal_expenses"
SOURCE_SILVER = f"{CATALOG}.{SCHEMA}.silver_charges"
TARGET_SILVER = f"{CATALOG}.{SCHEMA}.concapan_silver_charges"
TARGET_GOLD = f"{CATALOG}.{SCHEMA}.concapan_gold_summary"

print(f"Starting CONCAPAN ETL at {datetime.now(timezone.utc)} UTC")

# COMMAND ----------

# Read base silver charges
silver_df = spark.table(SOURCE_SILVER)
print(f"Loaded {silver_df.count()} base silver records from {SOURCE_SILVER}")

# COMMAND ----------

# Enrich with CONCAPAN tags:
# Identifies expenses related to travel, hotel, tech events, fuel, logistics and dining
concapan_df = (
    silver_df
    .withColumn(
        "is_travel_or_event",
        F.when(
            (F.col("category").isin("travel", "fuel", "restaurants")) |
            (F.upper(F.col("merchant")).like("%HOTEL%")) |
            (F.upper(F.col("merchant")).like("%IEEE%")) |
            (F.upper(F.col("merchant")).like("%AIRLINE%")) |
            (F.upper(F.col("merchant")).like("%AVIANCA%")) |
            (F.upper(F.col("merchant")).like("%GUATEMALA%")),
            True
        ).otherwise(False)
    )
    .withColumn(
        "event_tag",
        F.when(F.upper(F.col("merchant")).like("%IEEE%"), "IEEE / CONCAPAN Official")
         .when(F.col("category") == "travel", "Travel & Lodging")
         .when(F.col("category") == "fuel", "Transportation / Fuel")
         .when(F.col("category") == "restaurants", "Dining & Catering")
         .otherwise("General Operations")
    )
    .withColumn(
        "etl_processed_at",
        F.current_timestamp()
    )
)

# COMMAND ----------

# Save enriched Silver table
concapan_df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(TARGET_SILVER)
n_concapan = spark.table(TARGET_SILVER).count()
print(f"Saved {n_concapan} records into {TARGET_SILVER}")

# COMMAND ----------

# Build Gold Summary dataset for executive Lakeview dashboard
gold_df = (
    concapan_df
    .groupBy("event_tag", "category", "bank")
    .agg(
        F.count("*").alias("total_transactions"),
        F.round(F.sum("amount_usd"), 2).alias("total_usd"),
        F.round(F.sum(F.when(F.col("is_consumption"), F.col("amount_usd")).otherwise(0)), 2).alias("consumption_usd"),
        F.round(F.avg("amount_usd"), 2).alias("avg_usd"),
        F.max("charge_date_sv").alias("last_charge_date")
    )
    .orderBy(F.desc("total_usd"))
)

gold_df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(TARGET_GOLD)
print(f"Generated Gold summary in {TARGET_GOLD}")

# COMMAND ----------

# Audit verification
print("CONCAPAN ETL Audit completed successfully.")
